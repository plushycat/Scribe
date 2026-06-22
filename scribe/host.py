from __future__ import annotations

import msvcrt
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

from .config import Config, normalize_command
from .exporter import export_markdown, render_history
from .search import search_sessions
from .session import SessionEvent, SessionState, iso_now


class ScribeHost:
    def __init__(self, config: Config, sqlplus_path: str, sqlplus_args: list[str]) -> None:
        self.config = config
        self.sqlplus_path = sqlplus_path
        self.sqlplus_args = sqlplus_args
        self.session = SessionState.create(config.sessions_dir)
        self.output_queue: queue.Queue[str | None] = queue.Queue()
        self._process: subprocess.Popen[str] | None = None
        self._log: None = None
        self._output_buf = ""
        self._bootstrap_done = False
        self._pending_output = ""

    def run(self) -> int:
        self.session.save()
        with self.session.log_path.open("a", encoding="utf-8", errors="replace", newline="") as self._log:
            self._log_line(self._log, f"[scribe] session started {self.session.started_at}\n")

            self._process = subprocess.Popen(
                [self.sqlplus_path, *self.sqlplus_args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=False,
                bufsize=0,
            )

            reader = threading.Thread(target=self._read_output, args=(self._process,), daemon=True)
            reader.start()

            try:
                while self._process.poll() is None:
                    try:
                        line, is_password = self._read_line()
                    except EOFError:
                        break

                    if self._handle_internal(line):
                        continue

                    if is_password:
                        self._process.stdin.write((line + "\n").encode("utf-8"))
                        self._process.stdin.flush()
                        continue

                    forwarded = self._expand_alias(line)
                    self._record_command(forwarded)
                    self._log_line(self._log, f"> {forwarded}\n")
                    if self._process.stdin:
                        try:
                            self._process.stdin.write((forwarded + "\n").encode("utf-8"))
                            self._process.stdin.flush()
                        except (OSError, BrokenPipeError):
                            break

                    if normalize_command(forwarded) in {"exit", "quit"}:
                        break
            finally:
                if self._process.poll() is None and self._process.stdin:
                    self._process.stdin.close()
                self._process.wait()
                self._drain_output(self._log)
                if self.session.commands and self._pending_output:
                    self.session.commands[-1].output = self._pending_output
                self.session.ended_at = iso_now()
                self.session.exit_code = self._process.returncode
                self.session.save()
                self._log_line(self._log, f"[scribe] session ended {self.session.ended_at} exit={self._process.returncode}\n")

        return int(self.session.exit_code or 0)

    def _read_password(self):
        pwd = []
        mask = "∎"
        mask_bytes = mask.encode("utf-8")
        out = sys.stdout.buffer
        while True:
            ch = msvcrt.getch()
            if ch in {b"\r", b"\n"}:
                out.write(b"\n")
                out.flush()
                return "".join(pwd)
            if ch == b"\x08":
                if pwd:
                    pwd.pop()
                    out.write(b"\b \b")
                continue
            if ch == b"\x03":
                raise KeyboardInterrupt
            if ch[0] < 32:
                continue
            pwd.append(ch.decode("utf-8", errors="replace"))
            out.write(mask_bytes)
            out.flush()

    def _read_line(self):
        while True:
            self._drain_output(self._log)
            if "password:" in self._output_buf.casefold():
                self._output_buf = ""
                return self._read_password(), True
            if not self._bootstrap_done and "sql>" in self._output_buf.casefold():
                # Erase the initial SQL> prompt so (Scribe) SQL> appears cleanly
                sys.stdout.write("\r           \r")
                sys.stdout.flush()
                self._trigger_bootstrap()
            if msvcrt.kbhit():
                return input(), False
            if self._process.poll() is not None:
                raise EOFError
            time.sleep(0.05)

    def _read_output(self, process: subprocess.Popen[bytes]) -> None:
        assert process.stdout is not None
        while True:
            chunk = process.stdout.read(65536)
            if not chunk:
                break
            self.output_queue.put(chunk.decode("utf-8", errors="replace"))
        self.output_queue.put(None)

    def _trigger_bootstrap(self) -> None:
        if not self.config.bootstrap_commands or self._process is None or not self._process.stdin:
            return
        self._bootstrap_done = True
        process = self._process
        log = self._log
        cmds = self.config.bootstrap_commands
        for i, cmd in enumerate(cmds):
            try:
                process.stdin.write((cmd + "\n").encode("utf-8"))
                process.stdin.flush()
            except (OSError, BrokenPipeError):
                break
            time.sleep(0.3)
            if i == len(cmds) - 1:
                self._drain_output(log)
            else:
                self._drain_silent(log)

    def _drain_silent(self, log) -> None:
        while True:
            try:
                chunk = self.output_queue.get_nowait()
            except queue.Empty:
                break
            if chunk is None:
                break
            self._log_line(log, chunk)

    def _drain_output(self, log) -> None:
        buf = ""
        while True:
            try:
                chunk = self.output_queue.get_nowait()
            except queue.Empty:
                break
            if chunk is None:
                if buf:
                    print(buf, end="", flush=True)
                    self._log_line(log, buf)
                    self._output_buf += buf
                    self._pending_output += buf
                break
            buf += chunk
        if buf:
            print(buf, end="", flush=True)
            self._log_line(log, buf)
            self._output_buf += buf
            self._pending_output += buf
            if len(self._output_buf) > 100:
                self._output_buf = self._output_buf[-100:]

    def _handle_internal(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped.casefold().startswith("/scribe"):
            return False

        _, _, remainder = stripped.partition(" ")
        command, _, argument = remainder.strip().partition(" ")
        command = command.casefold()

        if command == "note":
            self.session.notes.append(SessionEvent("note", argument, iso_now()))
            self.session.save()
            print("Scribe note added.")
        elif command == "export":
            count = export_markdown(
                self.session,
                self.config.export_title,
                self.config.ignore_export_commands,
            )
            print(f"Scribe exported {count} command(s) to {self.session.markdown_path}.")
        elif command == "search":
            matches = search_sessions(self.config.sessions_dir, argument.strip('"'))
            print("\n".join(matches[:50]) if matches else "No matches found.")
        elif command == "history":
            print(render_history(self.session.commands))
        elif command == "status":
            print(f"Scribe session {self.session.id}")
            print(f"Transcript: {self.session.log_path}")
            print(f"Notebook:   {self.session.markdown_path}")
            print(f"Commands:   {len(self.session.commands)}")
            print(f"Notes:      {len(self.session.notes)}")
        elif command == "bootstrap":
            self._trigger_bootstrap()
        elif command in {"help", ""}:
            print("Scribe commands:")
            print("  /scribe status             Show session info")
            print("  /scribe note <text>        Attach a note to this session")
            print("  /scribe export             Export session to markdown")
            print("  /scribe search <term>      Search past sessions")
            print("  /scribe history            Show recent commands")
            print("  /scribe bootstrap          Re-run setup commands")
            print("  /scribe help               This help")
        else:
            print(f"Unknown Scribe command: {command}", file=sys.stderr)
        return True

    def _expand_alias(self, line: str) -> str:
        normalized = normalize_command(line)
        for alias, expansion in self.config.aliases.items():
            if normalize_command(alias) == normalized:
                print(f"Scribe alias: {alias} -> {expansion}")
                return expansion
        return line

    def _record_command(self, command: str) -> None:
        # Save accumulated output to the previous command
        if self.session.commands and self._pending_output:
            self.session.commands[-1].output = self._pending_output
            self._pending_output = ""
        self.session.commands.append(SessionEvent("command", command, iso_now()))
        self.session.save()

    @staticmethod
    def _log_line(log, text: str) -> None:
        log.write(text)
        log.flush()
