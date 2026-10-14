"""Window management: list, focus, minimise, maximise, restore, close, and open apps.

One tool, `manage_window`, in `server.py`; everything that touches Windows is
here, behind two fixed PowerShell scripts and one process seam.

The rules, each of which has a test:

* **The script never contains attacker text.** A window title is somebody
  else's words, and a spoken target is the model's. Neither is ever put into a
  script: matching happens in Python, and the only thing the action script
  receives is a window handle that has been through `int()`, plus an action
  name from a closed list.
* **Exactly one window.** An action runs only when the target matches one
  window. Two matches is a question ("which one?"), never a guess, the same
  rule `list_sessions` follows.
* **Closing is a polite request** (`WM_CLOSE`), so an app with unsaved work
  gets to ask about it. There is no force-kill here.
* **The desktop itself is off limits**: the taskbar, the desktop window and
  JARVIS's own server are never matched.
* **Opening is an allowlist.** A built-in set of everyday apps, plus whatever
  the user writes in `apps.json` in JARVIS's data folder. It is never "run this
  string": a name that is on neither list is refused and the known names are
  said.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import data_paths
import winutil

log = logging.getLogger("jarvis.windows")

LIST_TIMEOUT_SEC = 8.0
ACT_TIMEOUT_SEC = 8.0
MAX_LISTED = 40

ACTIONS = ("list", "open", "focus", "minimize", "maximize", "restore",
           "close", "minimize_all")

# Window classes that are the shell itself.
SHELL_CLASSES = frozenset({"Progman", "WorkerW", "Shell_TrayWnd",
                           "Shell_SecondaryTrayWnd", "NotifyIconOverflowWindow"})

# Programs whose windows are never matched at all.
PROTECTED_PROCESSES = frozenset({"csrss", "winlogon", "dwm", "lsass", "services",
                                 "system", "svchost", "searchhost",
                                 "startmenuexperiencehost", "shellexperiencehost",
                                 "textinputhost", "lockapp"})

_LIST_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class JarvisWin {
    public delegate bool EnumProc(IntPtr h, IntPtr l);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc p, IntPtr l);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] static extern bool IsZoomed(IntPtr h);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] static extern int GetWindowTextLength(IntPtr h);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern int GetWindowLong(IntPtr h, int i);
    [DllImport("dwmapi.dll")] static extern int DwmGetWindowAttribute(IntPtr h, int a, out int v, int s);
    public static List<string> Windows() {
        var rows = new List<string>();
        IntPtr fg = GetForegroundWindow();
        EnumWindows((h, l) => {
            if (!IsWindowVisible(h)) return true;
            int len = GetWindowTextLength(h);
            if (len == 0) return true;
            if ((GetWindowLong(h, -20) & 0x80) != 0) return true;   // tool window
            int cloaked; DwmGetWindowAttribute(h, 14, out cloaked, 4);
            if (cloaked != 0) return true;
            var t = new StringBuilder(len + 1); GetWindowText(h, t, t.Capacity);
            var c = new StringBuilder(256); GetClassName(h, c, 256);
            uint pid; GetWindowThreadProcessId(h, out pid);
            string state = IsIconic(h) ? "minimized" : (IsZoomed(h) ? "maximized" : "normal");
            rows.Add(h.ToInt64() + "|||" + pid + "|||" + c + "|||" + state + "|||" + (h == fg ? "front" : "") + "|||" + t.ToString().Replace("\r", " ").Replace("\n", " "));
            return true;
        }, IntPtr.Zero);
        return rows;
    }
}
'@
foreach ($row in [JarvisWin]::Windows()) {
    $parts = $row -split '\|\|\|', 6
    $name = ''
    try { $name = (Get-Process -Id ([int]$parts[1]) -ErrorAction Stop).ProcessName } catch {}
    Write-Output ($parts[0] + '|||' + $name + '|||' + $parts[2] + '|||' + $parts[3] + '|||' + $parts[4] + '|||' + $parts[5])
}
"""

_ACT_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class JarvisAct {
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
}
'@
$h = [IntPtr][int64]$env:JARVIS_WIN_HWND
if (-not [JarvisAct]::IsWindow($h)) { Write-Output 'gone'; exit 0 }
switch ($env:JARVIS_WIN_ACTION) {
    'minimize' { [void][JarvisAct]::ShowWindow($h, 6) }
    'maximize' { [void][JarvisAct]::ShowWindow($h, 3) }
    'restore'  { [void][JarvisAct]::ShowWindow($h, 9) }
    'focus'    { if ([JarvisAct]::IsIconic($h)) { [void][JarvisAct]::ShowWindow($h, 9) }; [void][JarvisAct]::SetForegroundWindow($h) }
    'close'    { [void][JarvisAct]::PostMessage($h, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) }
    default    { Write-Output 'bad action'; exit 2 }
}
Write-Output 'ok'
"""

_SHOW_DESKTOP_SCRIPT = "(New-Object -ComObject Shell.Application).MinimizeAll(); Write-Output 'ok'"


@dataclass
class Win:
    hwnd: int
    process: str
    cls: str
    state: str
    front: bool
    title: str


# ── the one process seam ───────────────────────────────────────────────────

async def _powershell(script: str, env: Optional[dict] = None,
                      timeout: float = LIST_TIMEOUT_SEC) -> tuple[int, str, str]:
    """Run one fixed script. Never raises."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *winutil.powershell_argv(script),
            env=winutil.with_env(**(env or {})),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except OSError as e:
        return -1, "", f"could not start PowerShell: {e}"
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.communicate()
        except Exception:
            pass
        return -1, "", f"PowerShell timed out after {timeout}s"
    return (proc.returncode if proc.returncode is not None else -1,
            out.decode("utf-8", "replace"), err.decode("utf-8", "replace"))


class WindowError(Exception):
    """Something that could not be done. The message is meant to be spoken."""


# ── listing and matching ───────────────────────────────────────────────────

def parse_listing(text: str) -> list[Win]:
    rows: list[Win] = []
    for line in text.splitlines():
        parts = line.rstrip("\r").split("|||", 5)
        if len(parts) != 6:
            continue
        try:
            hwnd = int(parts[0])
        except ValueError:
            continue
        process = parts[1].strip().lower()
        if parts[2] in SHELL_CLASSES or process in PROTECTED_PROCESSES:
            continue
        rows.append(Win(hwnd=hwnd, process=process, cls=parts[2], state=parts[3],
                        front=parts[4] == "front", title=parts[5].strip()))
    return rows


async def list_windows() -> list[Win]:
    code, out, err = await _powershell(_LIST_SCRIPT, timeout=LIST_TIMEOUT_SEC)
    if code != 0:
        log.warning("window listing failed: %s", err.strip()[:200])
        raise WindowError("I couldn't read your windows just now")
    return parse_listing(out)[:MAX_LISTED]


def _norm(text: str) -> str:
    return " ".join(str(text).lower().replace(".exe", "").split())


def match(windows: list[Win], target: str) -> list[Win]:
    """The windows a spoken target means. Process name beats title, and an
    exact name beats a substring."""
    want = _norm(target)
    if not want:
        return []
    exact_process = [w for w in windows if _norm(w.process) == want]
    if exact_process:
        return exact_process
    exact_title = [w for w in windows if _norm(w.title) == want]
    if exact_title:
        return exact_title
    return [w for w in windows if want in _norm(w.process) or want in _norm(w.title)]


# ── acting ─────────────────────────────────────────────────────────────────

async def act(win: Win, action: str) -> None:
    if action not in ("minimize", "maximize", "restore", "focus", "close"):
        raise WindowError("That's not something I do to a window")
    code, out, err = await _powershell(
        _ACT_SCRIPT, {"JARVIS_WIN_HWND": str(int(win.hwnd)), "JARVIS_WIN_ACTION": action},
        timeout=ACT_TIMEOUT_SEC)
    result = out.strip()
    if code != 0 or result not in ("ok", "gone"):
        log.warning("window action %s failed: %s %s", action, result, err.strip()[:200])
        raise WindowError("Windows wouldn't do that")
    if result == "gone":
        raise WindowError("That window has already gone")


async def show_desktop() -> None:
    code, out, err = await _powershell(_SHOW_DESKTOP_SCRIPT, timeout=ACT_TIMEOUT_SEC)
    if code != 0 or out.strip() != "ok":
        raise WindowError("Windows wouldn't minimise everything")


# ── opening apps ───────────────────────────────────────────────────────────

def _builtin_apps() -> dict[str, tuple[str, ...]]:
    """Spoken name -> argv or a single URI. Everyday apps that ship with Windows."""
    return {
        "notepad": ("notepad.exe",),
        "calculator": ("calc.exe",),
        "paint": ("mspaint.exe",),
        "file explorer": ("explorer.exe",),
        "explorer": ("explorer.exe",),
        "files": ("explorer.exe",),
        "task manager": ("taskmgr.exe",),
        "snipping tool": ("snippingtool.exe",),
        "settings": ("ms-settings:",),
        "terminal": ("wt.exe",),
        "command prompt": ("cmd.exe",),
        "powershell": ("powershell.exe",),
        "chrome": ("chrome.exe",),
        "google chrome": ("chrome.exe",),
        "edge": ("msedge.exe",),
        "firefox": ("firefox.exe",),
        "word": ("winword.exe",),
        "excel": ("excel.exe",),
        "vs code": ("code",),
        "visual studio code": ("code",),
    }


def apps_file() -> Path:
    return data_paths.data_dir() / "apps.json"


def user_apps() -> dict[str, str]:
    """`apps.json`: {"spotify": "C:\\\\...\\\\Spotify.exe", "steam": "steam://open/main"}.

    Values are an absolute path to an existing program, or a URI with a custom
    scheme. Anything else is dropped and logged: the file is the user's, but a
    typo must not become a command.
    """
    try:
        raw = json.loads(apps_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, str] = {}
    if not isinstance(raw, dict):
        return out
    for name, target in raw.items():
        if not isinstance(name, str) or not isinstance(target, str):
            continue
        key = _norm(name)
        if os.path.isabs(target) and os.path.isfile(target):
            out[key] = target
        elif ":" in target and not os.path.isabs(target) and "://" in target \
                and target.split(":", 1)[0].isalpha() \
                and target.split(":", 1)[0].lower() not in ("http", "https", "file", "javascript", "data"):
            out[key] = target
        else:
            log.warning("apps.json: %r is not a program path or app link; ignored", name)
    return out


def known_app_names() -> list[str]:
    return sorted(set(_builtin_apps()) | set(user_apps()))


def resolve_app(name: str) -> tuple[str, ...]:
    """The argv (or one-element URI) for a spoken app name, or raise."""
    key = _norm(name)
    mine = user_apps()
    if key in mine:
        return (mine[key],)
    builtin = _builtin_apps()
    if key in builtin:
        return builtin[key]
    raise WindowError(f"I don't have an app called that — I know {', '.join(known_app_names()[:14])}")


def _launch_sync(argv: tuple[str, ...]) -> None:
    target = argv[0]
    if len(argv) == 1 and ":" in target and not os.path.isabs(target) and "." not in target.split(":", 1)[0]:
        os.startfile(target)                        # a URI: ms-settings:, steam://
        return
    exe = target if os.path.isabs(target) else (shutil.which(target) or target)
    subprocess.Popen([exe, *argv[1:]], close_fds=True)


async def open_app(name: str) -> str:
    argv = resolve_app(name)
    try:
        await asyncio.to_thread(_launch_sync, argv)
    except OSError as e:
        log.warning("could not open %s: %s", name, e)
        raise WindowError("That wouldn't start — it may not be installed")
    return _norm(name)
