"""
JARVIS Action Executor -- system actions on Windows.

Each function returns {"success": bool, "confirmation": str}: a visible
console window, the browser's own executable, `os.startfile`.
"""

import asyncio
import logging
import os
import re
import shutil
import subprocess

import winutil

log = logging.getLogger("jarvis.actions")

# subprocess.CREATE_NEW_CONSOLE, spelled out so this imports on any platform.
_CREATE_NEW_CONSOLE = 0x00000010

cd_command = winutil.cd_command


def _windows_open_terminal(command: str) -> bool:
    """A new, visible cmd.exe console running `command` and staying open."""
    comspec = os.environ.get("COMSPEC") or "cmd.exe"
    # One string, not an argv: list2cmdline would backslash-escape the quotes
    # inside `command`, which cmd.exe does not understand. /S makes cmd strip
    # exactly the outer pair of quotes and leave the rest alone.
    line = f'"{comspec}" /S /K "{command}"' if command else f'"{comspec}"'
    subprocess.Popen(line, creationflags=_CREATE_NEW_CONSOLE, close_fds=True)
    return True


def _windows_browser_exe(browser: str) -> str | None:
    """Path to chrome.exe / firefox.exe, or None."""
    exe = "firefox.exe" if browser == "firefox" else "chrome.exe"
    found = shutil.which(exe)
    if found:
        return found
    roots = [os.environ.get(v) for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
    rel = (("Mozilla Firefox", "firefox.exe") if browser == "firefox"
           else ("Google", "Chrome", "Application", "chrome.exe"))
    for root in roots:
        if root:
            candidate = os.path.join(root, *rel)
            if os.path.isfile(candidate):
                return candidate
    return None


async def open_terminal(command: str = "") -> dict:
    """Open a console window and optionally run a command in it."""
    try:
        await asyncio.to_thread(_windows_open_terminal, command)
    except OSError as e:
        log.error(f"open_terminal failed: {e}")
        return {"success": False,
                "confirmation": "I had trouble opening a terminal, sir."}
    return {"success": True, "confirmation": "A terminal is open, sir."}


async def open_browser(url: str, browser: str = "chrome") -> dict:
    """Open URL in the user's browser (Chrome or Firefox).

    The URL becomes an argv entry of the browser executable, so a leading dash
    would be a browser flag; only real addresses go through. The URL arrives
    from a model, out of speech, possibly echoing a page or a README.
    """
    app_name = "Firefox" if browser.lower() == "firefox" else "Chrome"
    if not re.match(r"(?i)^(https?|file)://", url or ""):
        log.error(f"open_browser refused a non-URL: {url!r}")
        return {"success": False,
                "confirmation": f"{app_name} ran into a problem, sir."}
    exe = _windows_browser_exe(browser.lower())
    try:
        if exe:
            subprocess.Popen([exe, url], close_fds=True)
        else:
            import webbrowser
            if not webbrowser.open(url):
                raise OSError("no browser found")
    except OSError as e:
        log.error(f"open_browser ({app_name}) failed: {e}")
        return {"success": False,
                "confirmation": f"{app_name} ran into a problem, sir."}
    return {"success": True, "confirmation": f"Pulled that up in {app_name}, sir."}


# --- Opening code where the user actually reads it -----------------------
#
# VS Code first when it is installed, the file's registered handler otherwise.
# No shell: the path is its own argv entry, so a filename cannot be quoted out
# of a command line. Containment and the sensitive-file wall are the CALLER's
# job and have already run by the time this is reached -- see
# server.tool_open_in_editor.


def _vscode_command(path: str) -> list[str] | None:
    """The argv that opens `path` in VS Code, or None if it is not installed."""
    binary = shutil.which("code")
    if binary:
        return [binary, str(path)]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidate = os.path.join(local, "Programs", "Microsoft VS Code", "bin", "code.cmd")
        if os.path.isfile(candidate):
            return [candidate, str(path)]
    return None


async def open_in_editor(path: str) -> dict:
    """Open a file or directory in VS Code, else in the system default."""
    argv = _vscode_command(path)
    if argv is None:
        try:
            os.startfile(str(path))          # the file's registered handler
        except OSError as e:
            log.error(f"open_in_editor could not launch: {e}")
            return {"success": False, "editor": "your editor",
                    "confirmation": "I couldn't open an editor, sir."}
        return {"success": True, "editor": "your editor",
                "confirmation": "Opened that in your editor, sir."}

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        success = proc.returncode == 0
    except OSError as e:
        log.error(f"open_in_editor could not launch: {e}")
        return {"success": False, "editor": "VS Code",
                "confirmation": "I couldn't open an editor, sir."}

    if not success:
        log.error(f"open_in_editor failed: {stderr.decode(errors='replace')}")
    return {
        "success": success,
        "editor": "VS Code",
        "confirmation": "Opened that in VS Code, sir." if success
        else "VS Code wouldn't open that, sir.",
    }


def _generate_project_name(prompt: str) -> str:
    """Generate a kebab-case project folder name from the prompt."""
    # First: check for a quoted name like "tiktok-analytics-dashboard"
    quoted = re.search(r'"([^"]+)"', prompt)
    if quoted:
        name = quoted.group(1).strip()
        # Already kebab-case or close to it
        name = re.sub(r"[^a-zA-Z0-9\s-]", "", name).strip()
        if name:
            return re.sub(r"[\s]+", "-", name.lower())

    # Second: check for "called X" or "named X" pattern
    called = re.search(r'(?:called|named)\s+(\S+(?:[-_]\S+)*)', prompt, re.IGNORECASE)
    if called:
        name = re.sub(r"[^a-zA-Z0-9-]", "", called.group(1))
        if len(name) > 3:
            return name.lower()

    # Fallback: extract meaningful words
    words = re.sub(r"[^a-zA-Z0-9\s]", "", prompt.lower()).split()
    skip = {"a", "the", "an", "me", "build", "create", "make", "for", "with", "and",
            "to", "of", "i", "want", "need", "new", "project", "directory", "called",
            "on", "desktop", "that", "application", "app", "full", "stack", "simple",
            "web", "page", "site", "named"}
    meaningful = [w for w in words if w not in skip and len(w) > 2][:4]
    return "-".join(meaningful) if meaningful else "jarvis-project"
