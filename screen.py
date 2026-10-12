"""Seeing the user's desktop: the window list and one downscaled screenshot.

Two tools, deliberately different in cost:

* `list_windows` -- which app is in front and what every window is titled. A
  few hundred bytes, no pixels, and it answers "what am I looking at".
* `capture_screen` -- one PNG of one display, shrunk so the brain is shown at
  most `SHOT_MAX_EDGE` pixels on its long side (images are charged by area).

Captured only on a turn the user drove, never persisted, never on a timer. A
screenshot of someone's desk can hold a password; it is taken when they have
just asked and on no other turn.

Windows has no permission model to probe: any desktop process may read the
screen it is on. Both jobs are one fixed PowerShell script each (below), with
their inputs in the environment -- never in script source. Stdlib only.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path

import winutil

log = logging.getLogger("jarvis.screen")

# Each of these must finish WELL inside `jarvis_mcp.TIMEOUT_SEC` (20s), and
# the caller puts its own hard deadline on top: a handler that outlives it
# tells the brain the server is unreachable while the work carries on anyway.
CAPTURE_TIMEOUT_SEC = 8.0
WINDOWS_TIMEOUT_SEC = 5.0

# The longest edge the brain is shown. Images are charged by AREA -- roughly
# width*height/750 tokens -- so a 4K capture is not a neutral thing to put in
# a context this project already budgets and rotates:
#
#   1920x1080  ~2,765 tokens
#   1280x720   ~1,229 tokens   (what is actually sent)
#   1024x576     ~786 tokens
#
# 1280 is the same width `browser.LOOK_VIEWPORT` uses, and the point below
# which terminal text and menu bars stop being legible.
SHOT_MAX_EDGE = 1280

# A PNG bigger than this is not going through the tool channel; say so rather
# than sending something the CLI will choke on. Same bound as browser.py.
MAX_SHOT_BYTES = 4_000_000

# The window list is a tool result like any other, and every one of those is
# cut at `server.TOOL_RESULT_CAP`. Bound the list here so the cut never lands
# mid-way through the untrusted block the caller wraps it in.
MAX_WINDOWS = 12


class ScreenError(Exception):
    """Something JARVIS could not see. The message is meant to be spoken."""


@dataclass
class Shot:
    png: bytes
    width: int
    height: int


@dataclass
class Window:
    app: str
    title: str
    frontmost: bool


# ── the one subprocess boundary ────────────────────────────────────────────

async def _run(*args: str, timeout: float,
               env: dict[str, str] | None = None) -> tuple[int, str, str]:
    """Run one command, bounded by `timeout`. Never raises.

    The single seam every process in this module is spawned through, so tests
    mock one thing instead of `asyncio.create_subprocess_exec` per call.
    Argument lists only: nothing here is ever a shell string.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **({"env": env} if env is not None else {}),
        )
    except OSError as e:
        return -1, "", f"failed to spawn {args[0] if args else '?'}: {e}"

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.communicate()
        except Exception:
            pass
        return -1, "", f"{args[0] if args else '?'} timed out after {timeout}s"

    return (proc.returncode if proc.returncode is not None else -1,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"))


_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _png_size(png: bytes) -> tuple[int, int] | None:
    """(width, height) from a PNG's IHDR, or None if that is not a PNG.

    Doubles as the answer to "did the capture actually write a picture?".
    """
    if len(png) < 24 or not png.startswith(_PNG_MAGIC) or png[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", png[16:24])
    if width <= 0 or height <= 0:
        return None
    return width, height


async def capture_screen(display: int | None = None) -> Shot:
    """A PNG of one display, shrunk to `SHOT_MAX_EDGE`.

    `display` is a 1-based index; None means the main display. Without it a
    two-screen desk could only ever be asked about one of its screens.

    Raises ScreenError -- with a sentence fit to be spoken -- rather than ever
    handing back something the brain would describe wrongly. Call this ONLY on
    a turn the user drove.
    """
    return await _capture_screen_windows(display)


async def list_windows() -> list[Window]:
    """Open windows: app name, window title, and which app is in front."""
    return await _list_windows_windows()


# ── Windows ────────────────────────────────────────────────────────────────
# No permission model to probe: any desktop process may read the screen it is
# on. The whole job (capture, downscale, PNG) is one fixed PowerShell script,
# with its three inputs in the environment.

_WINDOWS_SHOT_SCRIPT = """\
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
public static class JarvisDpi { [DllImport("user32.dll")] public static extern bool SetProcessDPIAware(); }
'@
[void][JarvisDpi]::SetProcessDPIAware()
$screens = [System.Windows.Forms.Screen]::AllScreens
$want = 0
[void][int]::TryParse($env:JARVIS_SHOT_DISPLAY, [ref]$want)
if ($want -ge 1 -and $want -le $screens.Length) { $b = $screens[$want - 1].Bounds }
else { $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds }
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
$g.Dispose()
$max = [int]$env:JARVIS_SHOT_MAX
$edge = [Math]::Max($b.Width, $b.Height)
if ($edge -gt $max) {
    $scale = $max / $edge
    $w = [int][Math]::Max(1, [Math]::Round($b.Width * $scale))
    $h = [int][Math]::Max(1, [Math]::Round($b.Height * $scale))
    $small = New-Object System.Drawing.Bitmap $w, $h
    $sg = [System.Drawing.Graphics]::FromImage($small)
    $sg.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $sg.DrawImage($bmp, 0, 0, $w, $h)
    $sg.Dispose()
    $bmp.Dispose()
    $bmp = $small
}
$bmp.Save($env:JARVIS_SHOT_PATH, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
"""

_WINDOWS_LIST_SCRIPT = """\
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class JarvisFg {
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
}
'@
$fgPid = [uint32]0
[void][JarvisFg]::GetWindowThreadProcessId([JarvisFg]::GetForegroundWindow(), [ref]$fgPid)
Get-Process | Where-Object { $_.MainWindowTitle } | ForEach-Object {
    $front = ($_.Id -eq $fgPid)
    Write-Output ($_.ProcessName + '|||' + $_.MainWindowTitle + '|||' + $front)
}
"""


async def _capture_screen_windows(display: int | None) -> Shot:
    workdir = Path(tempfile.mkdtemp(prefix="jarvis-screen-"))
    try:
        shot_path = workdir / "screen.png"
        rc, _out, err = await _run(
            *winutil.powershell_argv(_WINDOWS_SHOT_SCRIPT),
            timeout=CAPTURE_TIMEOUT_SEC,
            env=winutil.with_env(JARVIS_SHOT_PATH=str(shot_path),
                                 JARVIS_SHOT_DISPLAY=str(display or 0),
                                 JARVIS_SHOT_MAX=str(SHOT_MAX_EDGE)))
        if rc != 0 or not shot_path.exists():
            log.warning(f"windows screen capture failed: {err.strip()[:200]}")
            raise ScreenError("I couldn't get a picture of your screen, sir")
        png = shot_path.read_bytes()
        size = _png_size(png)
        if size is None:
            raise ScreenError("I couldn't get a picture of your screen, sir")
        if len(png) > MAX_SHOT_BYTES:
            raise ScreenError("that picture came out far too large to send, sir")
        return Shot(png=png, width=size[0], height=size[1])
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


async def _list_windows_windows() -> list[Window]:
    rc, stdout, stderr = await _run(
        *winutil.powershell_argv(_WINDOWS_LIST_SCRIPT),
        timeout=WINDOWS_TIMEOUT_SEC + 5)
    if rc != 0:
        log.warning(f"list_windows failed: {stderr.strip()[:200]}")
        raise ScreenError("I couldn't read what's open, sir")
    windows: list[Window] = []
    for line in stdout.splitlines():
        parts = line.split("|||")
        if len(parts) < 3:
            continue
        windows.append(Window(app=parts[0].strip(), title=parts[1].strip(),
                              frontmost=parts[2].strip().lower() == "true"))
        if len(windows) >= MAX_WINDOWS:
            break
    return windows
