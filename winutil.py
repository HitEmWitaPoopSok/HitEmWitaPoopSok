"""Windows helpers: running a fixed PowerShell script safely.

JARVIS drives the parts of the desktop it needs (notifications, screenshots,
the window list) through PowerShell on Windows, the way it drives `osascript`
on macOS, and with the same rule: the script is a constant, and anything
attacker-influenced (a session title, a transcript line) reaches it only as
an environment variable, never as script source.
"""
from __future__ import annotations

import base64
import os
import shlex
import shutil
import sys


def is_windows() -> bool:
    # A function, not a constant: tests flip sys.platform.
    return sys.platform == "win32"


def powershell_argv(script: str) -> list[str]:
    """argv that runs `script` in Windows PowerShell, no profile, no prompt.

    `-EncodedCommand` (base64 of UTF-16LE) so there is no quoting layer for
    the script text to get wrong.
    """
    exe = shutil.which("powershell.exe") or shutil.which("powershell") \
        or shutil.which("pwsh") or "powershell.exe"
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return [exe, "-NoLogo", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded]


def with_env(**extra: str) -> dict[str, str]:
    """A copy of the environment with `extra` added."""
    env = dict(os.environ)
    env.update(extra)
    return env


def cd_command(path: str) -> str:
    """`cd` into `path`, quoted for the shell open_terminal will hand it to.

    POSIX shells get `cd <shlex-quoted>`. On Windows the console is cmd.exe,
    where `cd /d` is needed to cross drives and double quotes are the only
    quoting; a Windows path cannot contain `"`, and `%` is doubled so
    the variable expansion cmd does inside quotes cannot rewrite the path.
    """
    if is_windows():
        safe = str(path).replace('"', "").replace("%", "%%")
        return f'cd /d "{safe}"'
    return f"cd {shlex.quote(str(path))}"
