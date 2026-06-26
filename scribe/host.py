from __future__ import annotations

import msvcrt
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from .color import colorize_error, colorize_prompt, colorize_scribe, colorize_sql, strip_color
from .config import Config, normalize_command

_CLEAR_SCREEN_CMDS: set[str] = {
    normalize_command("CLEAR SCREEN"),
}

_ANSI_CLEAR = "\033[2J\033[3J\033[H"
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
        self._prompt = ""
        self._prompt_colored = ""
        self._history: list[str] = []
        self._history_index: int = -1
        self._history_draft: str = ""

    def run(self) -> int:
        self.session.save()
        print(colorize_scribe(f"[scribe] config: {len(self.config.bootstrap_commands)} bootstrap command(s)"))
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
                        if self._process.stdin:
                            self._process.stdin.write(b"\n")
                            self._process.stdin.flush()
                        continue

                    if is_password:
                        self._process.stdin.write((line + "\n").encode("utf-8"))
                        self._process.stdin.flush()
                        continue

                    forwarded = self._expand_alias(line)
                    self._record_command(forwarded)
                    self._log_line(self._log, f"> {forwarded}\n")
                    if normalize_command(forwarded) in _CLEAR_SCREEN_CMDS:
                        self._clear_screen()
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
                if self.config.ctrl_c_exit:
                    raise KeyboardInterrupt
                continue
            if ch[0] < 32:
                continue
            pwd.append(ch.decode("utf-8", errors="replace"))
            out.write(mask_bytes)
            out.flush()

    def _read_line(self):
        buf: list[str] = []
        cursor: int = 0
        out = sys.stdout.buffer
        while True:
            self._drain_output(self._log)
            if "password:" in self._output_buf.casefold():
                self._output_buf = ""
                return self._read_password(), True
            if not self._bootstrap_done and "sql>" in self._output_buf.casefold():
                sys.stdout.write("\r           \r")
                sys.stdout.flush()
                self._trigger_bootstrap()
            if self._process.poll() is not None:
                raise EOFError
            if not msvcrt.kbhit():
                time.sleep(0.02)
                continue
            ch = msvcrt.getch()
            if ch in {b"\x00", b"\xe0"}:
                arrow = msvcrt.getch()
                if not self._prompt:
                    continue
                if arrow == b"H":
                    self._history_navigate(buf, out, -1)
                    cursor = len(buf)
                elif arrow == b"P":
                    self._history_navigate(buf, out, 1)
                    cursor = len(buf)
                elif arrow == b"K":
                    if cursor > 0:
                        cursor -= 1
                        self._redraw_input(buf, cursor, out)
                elif arrow == b"M":
                    if cursor < len(buf):
                        cursor += 1
                        self._redraw_input(buf, cursor, out)
                elif arrow == b"S":
                    if cursor < len(buf):
                        del buf[cursor]
                        self._redraw_input(buf, cursor, out)
                continue
            if ch in {b"\r", b"\n"}:
                out.write(b"\n")
                out.flush()
                line = "".join(buf)
                if line.strip():
                    self._history.append(line)
                self._history_index = len(self._history)
                self._prompt = ""
                return line, False
            if ch == b"\x08":
                if buf:
                    if self._prompt:
                        cursor -= 1
                        del buf[cursor]
                        self._redraw_input(buf, cursor, out)
                    else:
                        buf.pop()
                        out.write(b"\b \b")
                        out.flush()
                continue
            if ch == b"\x03":
                if self.config.ctrl_c_exit:
                    raise KeyboardInterrupt
                continue
            if ch[0] < 32:
                continue
            text = ch.decode("utf-8", errors="replace")
            if self._prompt:
                buf.insert(cursor, text)
                cursor += 1
                while msvcrt.kbhit():
                    next_ch = msvcrt.getch()
                    if next_ch in {b"\r", b"\n", b"\x08", b"\x03"} or next_ch[0] < 32:
                        break
                    if next_ch in {b"\x00", b"\xe0"}:
                        msvcrt.getch()
                        break
                    buf.insert(cursor, next_ch.decode("utf-8", errors="replace"))
                    cursor += 1
                self._redraw_input(buf, cursor, out)
            else:
                buf.append(text)
                out.write(text.encode("utf-8"))
                out.flush()

    def _redraw_input(self, buf: list[str], cursor: int, out) -> None:
        text = "".join(buf)
        # Terminal width for computing line wrapping
        try:
            cols = os.get_terminal_size().columns
        except OSError:
            cols = 80
        prompt_len = len(strip_color(self._prompt_colored or self._prompt))
        # How many visual lines above the cursor line does the input span?
        lines_above = (prompt_len + cursor) // cols
        # Move up to the first line of the input, then go to column 0
        if lines_above > 0:
            out.write(f"\033[{lines_above}A".encode("utf-8"))
        out.write(b"\r")
        # Clear from cursor position to end of screen (handles all wrapped lines)
        out.write(b"\033[J")
        # Redraw prompt
        if self._prompt_colored:
            out.write(self._prompt_colored.encode("utf-8"))
        else:
            out.write(self._prompt.encode("utf-8"))
        # Redraw text with SQL syntax highlighting
        if text:
            out.write(colorize_sql(text).encode("utf-8"))
        # Position cursor
        move_back = len(buf) - cursor
        if move_back > 0:
            out.write(b"\b" * move_back)
        out.flush()

    def _history_navigate(self, buf: list[str], out, direction: int) -> None:
        if not self._history:
            return
        new_index = self._history_index + direction
        if new_index < 0 or new_index > len(self._history):
            return
        if self._history_index == len(self._history) and direction == -1:
            self._history_draft = "".join(buf)
        self._history_index = new_index
        buf.clear()
        if new_index == len(self._history):
            line = self._history_draft
        else:
            line = self._history[new_index]
        if line:
            buf.extend(line)
        self._redraw_input(buf, len(buf), out)

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
        for i, cmd in enumerate(self.config.bootstrap_commands):
            try:
                process.stdin.write((cmd + "\n").encode("utf-8"))
                process.stdin.flush()
            except (OSError, BrokenPipeError):
                break
            time.sleep(0.3)
            if i == len(self.config.bootstrap_commands) - 1:
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
                    print(self._colorize_output(buf), end="", flush=True)
                    self._log_line(log, strip_color(buf))
                    self._output_buf += buf
                    self._pending_output += buf
                break
            buf += chunk
        if buf:
            print(self._colorize_output(buf), end="", flush=True)
            self._log_line(log, strip_color(buf))
            self._output_buf += buf
            self._pending_output += buf
            if len(self._output_buf) > 100:
                self._output_buf = self._output_buf[-100:]
            stripped = strip_color(buf).rstrip("\n\r")
            # Match primary prompts (Ø SQL>) or continuation prompts (  2  )
            m = re.search(r"^(.*?>\s?)$", stripped, re.MULTILINE)
            if not m:
                m = re.search(r"^(\s*\d+\s+)", stripped, re.MULTILINE)
            if m:
                raw = m.group(1)
                self._prompt = raw
                self._prompt_colored = colorize_prompt(raw)

    def _handle_internal(self, line: str) -> bool:
        stripped = line.strip()
        casefolded = stripped.casefold()
        if casefolded.startswith("/scribe"):
            _, _, remainder = stripped.partition(" ")
            command, _, argument = remainder.strip().partition(" ")
            command = command.casefold()
        elif casefolded.startswith("scribe"):
            _, _, remainder = stripped.partition(" ")
            command, _, argument = remainder.strip().partition(" ")
            command = command.casefold()
        else:
            return False

        if command == "note":
            self.session.notes.append(SessionEvent("note", argument, iso_now()))
            self.session.save()
            print(colorize_scribe("Scribe note added."))
        elif command == "export":
            count = export_markdown(
                self.session,
                self.config.export_title,
                self.config.ignore_export_commands,
            )
            print(colorize_scribe(f"Scribe exported {count} command(s) to {self.session.markdown_path}."))
        elif command == "search":
            matches = search_sessions(self.config.sessions_dir, argument.strip('"'))
            print("\n".join(matches[:50]) if matches else colorize_scribe("No matches found."))
        elif command == "history":
            print(render_history(self.session.commands))
        elif command == "status":
            print(colorize_scribe(f"Scribe session {self.session.id}"))
            print(colorize_scribe(f"Transcript: {self.session.log_path}"))
            print(colorize_scribe(f"Notebook:   {self.session.markdown_path}"))
            print(colorize_scribe(f"Commands:   {len(self.session.commands)}"))
            print(colorize_scribe(f"Notes:      {len(self.session.notes)}"))
        elif command == "bootstrap":
            self._trigger_bootstrap()
        elif command in {"help", ""}:
            print(colorize_scribe("Scribe commands:"))
            print(colorize_scribe("  scribe status             Show session info"))
            print(colorize_scribe("  scribe note <text>        Attach a note to this session"))
            print(colorize_scribe("  scribe export             Export session to markdown"))
            print(colorize_scribe("  scribe search <term>      Search past sessions"))
            print(colorize_scribe("  scribe history            Show recent commands"))
            print(colorize_scribe("  scribe bootstrap          Re-run setup commands"))
            print(colorize_scribe("  scribe help               This help"))
            if self.config.aliases:
                print(colorize_scribe("\nAliases:"))
                for alias, expansion in self.config.aliases.items():
                    print(colorize_scribe(f"  {alias:<20} -> {expansion}"))
        else:
            print(f"Unknown Scribe command: {command}", file=sys.stderr)
        return True

    def _expand_alias(self, line: str) -> str:
        normalized = normalize_command(line)
        for alias, expansion in self.config.aliases.items():
            if normalize_command(alias) == normalized:
                print(colorize_scribe(f"Scribe alias: {alias} -> {expansion}"))
                return expansion
        return line

    def _record_command(self, command: str) -> None:
        # Save accumulated output to the previous command
        if self.session.commands and self._pending_output:
            self.session.commands[-1].output = self._pending_output
            self._pending_output = ""
        self.session.commands.append(SessionEvent("command", command, iso_now()))
        self.session.save()

    def _clear_screen(self) -> None:
        out = sys.stdout.buffer
        out.write(_ANSI_CLEAR.encode("utf-8"))
        out.flush()
        self._output_buf = ""
        self._pending_output = ""

    @staticmethod
    def _colorize_output(text: str) -> str:
        lines = text.splitlines(keepends=True)
        result = []
        for line in lines:
            # Error lines: color entire line red, skip SQL colorization
            error_colored = colorize_error(line)
            if error_colored != line:
                result.append(error_colored)
                continue
            # Prompt lines: split prompt from SQL, colorize each part separately
            m = re.match(r"(\S+\s+\S+>\s?)", line)
            if m:
                prompt_part = colorize_prompt(line[:m.end()])
                sql_part = colorize_sql(line[m.end():])
                result.append(prompt_part + sql_part)
                continue
            # Plain output: apply SQL colorization
            result.append(colorize_sql(line))
        return "".join(result)

    @staticmethod
    def _log_line(log, text: str) -> None:
        log.write(text)
        log.flush()
