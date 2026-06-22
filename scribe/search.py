from __future__ import annotations

from pathlib import Path


def search_sessions(sessions_dir: Path, term: str) -> list[str]:
    needle = term.casefold()
    matches: list[str] = []
    if not sessions_dir.exists():
        return matches

    for path in sorted(sessions_dir.glob("*.*")):
        if path.suffix.casefold() not in {".log", ".md"}:
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, start=1):
            if needle in line.casefold():
                matches.append(f"{path}:{number}: {line}")
    return matches
