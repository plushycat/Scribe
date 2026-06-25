from __future__ import annotations

from .config import normalize_command
from .session import SessionEvent, SessionState, iso_now


def export_markdown(session: SessionState, title: str, ignore_commands: set[str]) -> int:
    sections: list[str] = []
    if not session.markdown_path.exists():
        sections.append(f"# {title}\n")
        sections.append(f"Started: {session.started_at}\n")

    sections.append(f"\n## Export\n\nGenerated: {iso_now()}\n")

    new_notes = session.notes[session.exported_notes_count:]
    for note in new_notes:
        sections.append("\n## Note\n\n")
        sections.append(note.text.strip() + "\n")

    exported = 0
    new_commands = session.commands[session.exported_commands_count:]
    for event in new_commands:
        if should_ignore(event.text, ignore_commands):
            continue
        sections.append("\n## Query\n\n```sql\n")
        sections.append(event.text.rstrip() + "\n")
        sections.append("```\n")

        output = _strip_prompt(event.output)
        if output:
            sections.append("\n```\n")
            sections.append(output)
            sections.append("\n```\n")

        exported += 1

    if exported == 0 and not new_notes:
        sections.append("\n_No exportable commands or notes yet._\n")

    with session.markdown_path.open("a", encoding="utf-8", newline="\n") as output:
        output.write("".join(sections))

    session.exports.append(iso_now())
    session.exported_commands_count = len(session.commands)
    session.exported_notes_count = len(session.notes)
    session.save()
    return exported


def _strip_prompt(output: str) -> str:
    if not output:
        return ""
    for marker in ["(Scribe) SQL> ", "(Scribe) SQL>", "SQL> "]:
        idx = output.rstrip().rfind(marker)
        if idx >= 0:
            output = output[:idx]
    return output.strip()


def should_ignore(command: str, ignore_commands: set[str]) -> bool:
    return normalize_command(command) in ignore_commands


def render_history(events: list[SessionEvent], limit: int = 20) -> str:
    recent = events[-limit:]
    if not recent:
        return "No commands recorded yet."
    return "\n".join(f"{event.timestamp}  {event.text}" for event in recent)
