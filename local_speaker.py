"""Play audio through the PC's own speakers, with no browser page involved.

Used when JARVIS has to be heard and nobody has his page open: a message
relayed from the phone, a reminder. The mp3 bytes come from the same Fish Audio
synthesis the page uses; Windows' own MediaPlayer plays them.
"""
import asyncio
import os
import tempfile
from pathlib import Path

import winutil

SCRIPT = r"""
if (-not (Test-Path -LiteralPath $env:JARVIS_AUDIO)) { Write-Output 'missing'; exit 0 }
Add-Type -AssemblyName PresentationCore
$p = New-Object System.Windows.Media.MediaPlayer
$p.Open([Uri]$env:JARVIS_AUDIO)
$t = 0
while (-not $p.NaturalDuration.HasTimeSpan -and $t -lt 50) { Start-Sleep -Milliseconds 100; $t++ }
$p.Play()
$ms = 8000
if ($p.NaturalDuration.HasTimeSpan) { $ms = [int]$p.NaturalDuration.TimeSpan.TotalMilliseconds }
Start-Sleep -Milliseconds ($ms + 400)
$p.Close()
Write-Output 'ok'
"""

_lock = asyncio.Lock()


async def play(mp3: bytes, timeout: float = 90.0) -> bool:
    """True if it played. One clip at a time, so two messages never overlap."""
    if not mp3 or os.name != "nt":
        return False
    async with _lock:
        fd, name = tempfile.mkstemp(suffix=".mp3", prefix="jarvis-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(mp3)
            proc = await asyncio.create_subprocess_exec(
                *winutil.powershell_argv(SCRIPT), env=winutil.with_env(JARVIS_AUDIO=name),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return False
            return out.decode("utf-8", "replace").strip() == "ok"
        except OSError:
            return False
        finally:
            try:
                Path(name).unlink()
            except OSError:
                pass
