from __future__ import annotations

import argparse
import sys

from .config import Config, ensure_config
from .elevation import is_elevated, relaunch_elevated
from .host import ScribeHost


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scribe",
        description="Record and export Oracle 11g SQL*Plus terminal sessions.",
    )
    parser.add_argument(
        "--config",
        default="scribe.config.json",
        help="Path to the Scribe JSON configuration file.",
    )
    parser.add_argument(
        "--sqlplus",
        default=None,
        help="SQL*Plus executable path. Overrides config sqlplus_path.",
    )
    parser.add_argument(
        "--elevate",
        action="store_true",
        help="Relaunch Scribe in an elevated PowerShell window before starting SQL*Plus.",
    )
    parser.add_argument(
        "sqlplus_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to SQL*Plus. Prefix with -- when needed.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.elevate and not is_elevated():
        elevated_argv = [item for item in argv if item != "--elevate"]
        return relaunch_elevated(elevated_argv)

    ensure_config(args.config)
    config = Config.load(args.config)
    sqlplus_path = args.sqlplus or config.sqlplus_path
    sqlplus_args = args.sqlplus_args
    if sqlplus_args and sqlplus_args[0] == "--":
        sqlplus_args = sqlplus_args[1:]

    try:
        host = ScribeHost(config=config, sqlplus_path=sqlplus_path, sqlplus_args=sqlplus_args)
        return host.run()
    except KeyboardInterrupt:
        return 130
    except FileNotFoundError:
        print(f"Scribe could not find SQL*Plus executable: {sqlplus_path}", file=sys.stderr)
        print("Use --sqlplus or update scribe.config.json.", file=sys.stderr)
        return 1
    except OSError as error:
        if getattr(error, "winerror", None) == 740:
            print("SQL*Plus requires elevation on this machine.", file=sys.stderr)
            print("Run again with: python -m scribe --elevate -- <your-sqlplus-login>", file=sys.stderr)
            return 1
        raise
