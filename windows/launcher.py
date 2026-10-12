r"""JARVIS for Windows -- launcher (frozen into JARVIS.exe by PyInstaller).

Layout it expects, as the installer lays it down:

    <root>\JARVIS.exe        this program
    <root>\python\           an embeddable CPython with every dependency in it
    <root>\app\              server.py, frontend\dist, ...

What it does, in order: make sure the server is running (starting it with no
console window if not), wait for the port, open Chrome on it. The server
itself is a separate, hidden python.exe -- so closing a browser tab never
stops JARVIS, and `JARVIS.exe --stop` does.

Stdlib only, on purpose: this file is frozen, and anything it imports ships
inside the exe.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

PORT = int(os.environ.get("JARVIS_PORT", "8340"))
HOST = "127.0.0.1"
URL = f"http://localhost:{PORT}/"
START_TIMEOUT_SEC = 90

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200

TITLE = "JARVIS"


def root_dir() -> Path:
    override = os.environ.get("JARVIS_ROOT")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def data_root() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "JARVIS"


def message(text: str, icon: int = 0x40) -> None:
    """A native message box (0x40 info, 0x30 warning, 0x10 error)."""
    try:
        ctypes.windll.user32.MessageBoxW(0, text, TITLE, icon)
    except Exception:
        print(text, file=sys.stderr)


def port_open() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=0.5):
            return True
    except OSError:
        return False


def server_env(data: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update({
        # Every text file the code opens without an explicit encoding is
        # UTF-8, not the Windows code page.
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "JARVIS_DATA_DIR": str(data / "data"),
        "JARVIS_ENV_FILE": str(data / ".env"),
        "JARVIS_PID_FILE": str(data / "jarvis.pid"),
    })
    return env


def start_server(root: Path, data: Path) -> subprocess.Popen:
    python = root / "python" / "python.exe"
    server = root / "app" / "server.py"
    if not python.is_file() or not server.is_file():
        raise FileNotFoundError(f"JARVIS is not installed correctly: missing {python if not python.is_file() else server}")
    (data / "data").mkdir(parents=True, exist_ok=True)
    log = open(data / "jarvis.log", "ab")
    return subprocess.Popen(
        # -X utf8: the bundled interpreter runs isolated (python312._pth),
        # which ignores PYTHONUTF8; the flag does not.
        [str(python), "-X", "utf8", str(server), "--host", HOST, "--port", str(PORT)],
        cwd=str(root / "app"),
        env=server_env(data),
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )


def find_chrome() -> str | None:
    found = shutil.which("chrome.exe")
    if found:
        return found
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            candidate = Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
            if candidate.is_file():
                return str(candidate)
    return None


def open_ui() -> None:
    chrome = find_chrome()
    if chrome:
        subprocess.Popen([chrome, URL], close_fds=True)
        return
    message("Google Chrome was not found.\n\nJARVIS listens through Chrome's "
            "speech recognition; other browsers cannot hear you. Opening your "
            "default browser instead -- install Chrome to talk to him.", 0x30)
    webbrowser.open(URL)


def check_claude() -> None:
    if shutil.which("claude"):
        return
    message("Claude Code is not installed (or not on PATH).\n\nJARVIS's brain "
            "is Claude Code running on your Claude subscription. Install it "
            "from https://docs.claude.com/en/docs/claude-code/setup , run "
            "`claude` once in a terminal to log in, then start JARVIS again.\n\n"
            "He will still open, but he cannot think until then.", 0x30)


def stop() -> int:
    pid_file = data_root() / "jarvis.pid"
    try:
        pid = int(pid_file.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        if port_open():
            message("JARVIS is running but its pid file is missing; end "
                    "'python.exe' for JARVIS in Task Manager.", 0x30)
            return 1
        message("JARVIS is not running.")
        return 0
    # /T: the server's children too (the brain, any run).
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                   capture_output=True, creationflags=CREATE_NO_WINDOW)
    try:
        pid_file.unlink()
    except OSError:
        pass
    message("JARVIS has been stopped.")
    return 0


def main(argv: list[str]) -> int:
    if "--stop" in argv:
        return stop()

    root, data = root_dir(), data_root()
    data.mkdir(parents=True, exist_ok=True)

    if not port_open():
        check_claude()
        try:
            proc = start_server(root, data)
        except OSError as e:
            message(f"JARVIS could not start:\n\n{e}", 0x10)
            return 1
        deadline = time.monotonic() + START_TIMEOUT_SEC
        while time.monotonic() < deadline:
            if port_open():
                break
            if proc.poll() is not None:
                message("JARVIS stopped while starting. The log is at:\n\n"
                        f"{data / 'jarvis.log'}", 0x10)
                return 1
            time.sleep(0.4)
        else:
            message("JARVIS did not come up in time. The log is at:\n\n"
                    f"{data / 'jarvis.log'}", 0x10)
            return 1

    if "--no-browser" not in argv:
        open_ui()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
