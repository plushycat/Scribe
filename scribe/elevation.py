from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path


def is_windows() -> bool:
    return os.name == "nt"


def is_elevated() -> bool:
    if not is_windows():
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def relaunch_elevated(argv: list[str]) -> int:
    if not is_windows():
        print("--elevate is only supported on Windows.", file=sys.stderr)
        return 1

    cwd = str(Path.cwd())
    
    # Build the scribe command, removing --elevate to avoid recursion
    scribe_args = [arg for arg in argv if arg != "--elevate"]
    arg_list = "-m scribe" + (" " + subprocess.list2cmdline(scribe_args) if scribe_args else "")
    
    # Launch an elevated Windows Terminal window running Scribe.
    # wt.exe -d <cwd> runs the command in that directory.
    # Start-Process -Verb RunAs elevates the whole Windows Terminal window.
    wt_args = f'-d "{cwd}" {sys.executable} {arg_list}'
    ps_cmd = (
        f'Start-Process -FilePath "wt.exe"'
        f' -ArgumentList \'{wt_args}\''
        f' -Verb RunAs'
        f' -Wait'
    )
    
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            check=False,
        )
        return result.returncode
    except Exception as e:
        print(f"Scribe could not elevate: {e}", file=sys.stderr)
        return 1
