from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "sqlplus_path": "sqlplus",
    "sessions_dir": "sessions",
    "bootstrap_commands": [
        "SET LINESIZE 200",
        "SET PAGESIZE 1000",
        "SET SERVEROUTPUT ON",
        "SET SQLPROMPT '(Scribe) SQL> '",
    ],
    "aliases": {
        "cls": "CLEAR SCREEN",
        "clrscr": "CLEAR SCREEN",
        "wipe": "CLEAR SCREEN",
        "show tables": "SELECT table_name\nFROM user_tables\nORDER BY table_name;",
    },
    "ignore_export_commands": ["CLEAR SCREEN", "cls", "clrscr", "wipe"],
    "export": {"title": "Session"},
    "ctrl_c_exit": True,
}


@dataclass(frozen=True)
class Config:
    sqlplus_path: str = "sqlplus"
    sessions_dir: Path = Path("sessions")
    bootstrap_commands: list[str] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)
    ignore_export_commands: set[str] = field(default_factory=set)
    export_title: str = "Session"
    ctrl_c_exit: bool = True

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        export = data.get("export", {})
        return cls(
            sqlplus_path=str(data.get("sqlplus_path", "sqlplus")),
            sessions_dir=Path(data.get("sessions_dir", "sessions")),
            bootstrap_commands=[str(c) for c in data.get("bootstrap_commands", [])],
            aliases={str(k): str(v) for k, v in data.get("aliases", {}).items()},
            ignore_export_commands={normalize_command(v) for v in data.get("ignore_export_commands", [])},
            export_title=str(export.get("title", "Session")),
            ctrl_c_exit=bool(data.get("ctrl_c_exit", True)),
        )


def ensure_config(path: str | Path) -> None:
    config_path = Path(path)
    if config_path.exists():
        return
    config_path.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")


def normalize_command(command: str) -> str:
    return " ".join(command.strip().split()).casefold()
