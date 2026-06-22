# Scribe

Scribe is a lightweight Windows-first SQL*Plus session recorder.

The MVP launches Oracle 11g SQL*Plus as the child process, records a live raw
transcript, supports local `/scribe` commands, and stores session files on disk.

## Quick Start

```powershell
python -m scribe
```

Pass SQL*Plus arguments after `--`:

```powershell
python -m scribe -- scott/tiger@orcl
```

Use a custom SQL*Plus executable:

```powershell
python -m scribe --sqlplus C:\oracle\product\11.2.0\dbhome_1\BIN\sqlplus.exe -- scott/tiger@orcl
```

If Windows reports that SQL*Plus requires elevation, relaunch Scribe through UAC:

```powershell
python -m scribe --elevate -- scott/tiger@orcl
```

## Internal Commands

Internal commands are consumed by Scribe and are not forwarded to SQL*Plus.

```text
/scribe status
/scribe note Practicing joins
/scribe export
/scribe search "GROUP BY"
/scribe history
```

## Files

Scribe writes human-readable files under `sessions/`:

```text
sessions/
  2026-06-14_103012.log
  2026-06-14_103012.md
  2026-06-14_103012.json
```

The raw `.log` file is the canonical transcript and is never discarded by
exports.

## Configuration

Default configuration is created at `scribe.config.json` on first run.

Aliases are visible and deterministic:

```json
{
  "aliases": {
    "cls": "CLEAR SCREEN",
    "clrscr": "CLEAR SCREEN",
    "wipe": "CLEAR SCREEN"
  }
}
```

Ignored commands remain in raw transcripts but are omitted from Markdown
exports.
