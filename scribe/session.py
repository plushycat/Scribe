from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class SessionEvent:
    kind: str
    text: str
    timestamp: str
    output: str = ""


@dataclass
class SessionState:
    id: str
    started_at: str
    log_path: Path
    markdown_path: Path
    metadata_path: Path
    notes: list[SessionEvent] = field(default_factory=list)
    commands: list[SessionEvent] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    exported_commands_count: int = 0
    exported_notes_count: int = 0
    ended_at: str | None = None
    exit_code: int | None = None

    @classmethod
    def create(cls, sessions_dir: Path) -> "SessionState":
        sessions_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        return cls(
            id=stamp,
            started_at=iso_now(),
            log_path=sessions_dir / f"{stamp}.log",
            markdown_path=sessions_dir / f"{stamp}.md",
            metadata_path=sessions_dir / f"{stamp}.json",
        )

    def save(self) -> None:
        data = asdict(self)
        data["log_path"] = str(self.log_path)
        data["markdown_path"] = str(self.markdown_path)
        data["metadata_path"] = str(self.metadata_path)
        self.metadata_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")
