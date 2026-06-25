from __future__ import annotations

import ctypes
import re
import sys

# ---------------------------------------------------------------------------
# Hex colour palette
# ---------------------------------------------------------------------------

COLORS: dict[str, str] = {
    "keyword":  "#61AFEF",
    "string":   "#98C379",
    "number":   "#D19A66",
    "operator": "#56B6C2",
    "error":    "#E06C75",
    "scribe":   "#C678DD",
    "prompt":   "#61AFEF",
}

# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------

_RESET = "\033[0m"


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _fg(hex_color: str) -> str:
    r, g, b = _hex_to_rgb(hex_color)
    return f"\033[38;2;{r};{g};{b}m"


def _bg(hex_color: str) -> str:
    r, g, b = _hex_to_rgb(hex_color)
    return f"\033[48;2;{r};{g};{b}m"


def reset(text: str) -> str:
    return f"{_RESET}{text}{_RESET}"


def fg(text: str, hex_color: str) -> str:
    return f"{_fg(hex_color)}{text}{_RESET}"

# ---------------------------------------------------------------------------
# Console capability detection
# ---------------------------------------------------------------------------

_enabled: bool | None = None


def _enable_vt_processing() -> None:
    """Enable Windows VT processing so ANSI escape codes render."""
    if sys.platform != "win32":
        return
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        # Get current mode
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except OSError:
        pass


def is_enabled() -> bool:
    global _enabled
    if _enabled is None:
        _enabled = sys.stdout.isatty()
        if _enabled and sys.platform == "win32":
            _enable_vt_processing()
    return _enabled


def set_enabled(value: bool) -> None:
    global _enabled
    _enabled = value

# ---------------------------------------------------------------------------
# SQL token colourizer
# ---------------------------------------------------------------------------

_SQL_KEYWORDS = frozenset({
    "select", "from", "where", "and", "or", "not", "in", "is", "null",
    "as", "on", "join", "left", "right", "inner", "outer", "cross",
    "group", "by", "order", "having", "limit", "offset", "union", "all",
    "distinct", "into", "values", "insert", "update", "delete", "set",
    "create", "alter", "drop", "table", "view", "index", "sequence",
    "grant", "revoke", "commit", "rollback", "savepoint", "begin", "end",
    "case", "when", "then", "else", "decode", "exists", "between", "like",
    "any", "some", "fetch", "row", "rows", "only", "with", "for",
    "no", "data", "cursor", "open", "close", "loop", "exit", "when",
    "pragma", "exception", "raise", "if", "elsif", "elsif", "while",
    "declare", "function", "procedure", "package", "body", "return",
    "returns", "language", "plsql", "exec", "execute", "immediate",
    "sysdate", "systimestamp", "current_date", "current_timestamp",
    "rownum", "rowid", "dual", "user", "tablespace", "temporary",
    "constraint", "primary", "key", "foreign", "references", "unique",
    "check", "default", "auto_increment", "identity", "column",
    "true", "false", "number", "varchar2", "varchar", "char", "clob",
    "blob", "date", "timestamp", "integer", "int", "smallint", "float",
    "double", "precision", "raw", "long", "nchar", "nvarchar2", "nclob",
})

_SQL_OPERATORS = frozenset({
    "=", "<", ">", "<=", ">=", "<>", "!=", "+", "-", "*", "/", "%",
    "||", ":=", "=>", "..", "**",
})

_TOKEN_RE = re.compile(
    r"(?P<string>'[^']*'|\"[^\"]*\")"
    r"|(?P<number>\b\d+(?:\.\d+)?\b)"
    r"|(?P<operator>\.\.|:=|=>|[<>=!+\-*/%|]{1,2})"
    r"|(?P<word>[A-Za-z_]\w*)"
    r"|(?P<other>\S|\s)",
    re.DOTALL,
)


def colorize_sql(text: str) -> str:
    if not is_enabled():
        return text
    parts: list[str] = []
    for m in _TOKEN_RE.finditer(text):
        if m.group("string"):
            parts.append(fg(m.group(), COLORS["string"]))
        elif m.group("number"):
            parts.append(fg(m.group(), COLORS["number"]))
        elif m.group("operator"):
            parts.append(fg(m.group(), COLORS["operator"]))
        elif m.group("word"):
            word = m.group()
            if word.lower() in _SQL_KEYWORDS:
                parts.append(fg(word, COLORS["keyword"]))
            else:
                parts.append(word)
        else:
            parts.append(m.group())
    return "".join(parts)

# ---------------------------------------------------------------------------
# Line-level colourizers
# ---------------------------------------------------------------------------

_ORA_RE = re.compile(r"^(ORA-\d+|SP2-\d+)", re.IGNORECASE)


def colorize_error(text: str) -> str:
    if not is_enabled():
        return text
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    for line in lines:
        if _ORA_RE.search(line):
            out.append(fg(line, COLORS["error"]))
        else:
            out.append(line)
    return "".join(out)


def colorize_scribe(text: str) -> str:
    if not is_enabled():
        return text
    return fg(text, COLORS["scribe"])


_PROMPT_RE = re.compile(r"(\S+\s+SQL>\s?)")


def colorize_prompt(text: str) -> str:
    if not is_enabled():
        return text
    return _PROMPT_RE.sub(lambda m: fg(m.group(), COLORS["prompt"]), text)

# ---------------------------------------------------------------------------
# Strip ANSI for logs / export
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def strip_color(text: str) -> str:
    return _ANSI_RE.sub("", text)
