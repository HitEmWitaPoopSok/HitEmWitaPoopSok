"""
JARVIS Notifier -- Windows notification fallback.

When JARVIS needs the user's attention but no browser tab is connected to
speak through, this posts a Windows notification (a balloon/toast from a
short-lived NotifyIcon) instead.

Notification titles/messages surface a Claude Code session's title or its
last message -- text that originates in someone else's transcript, not text
JARVIS wrote itself. So the script never contains the untrusted text at all:
it is a fixed constant, and the title/message/subtitle reach it as
environment variables, which PowerShell hands to the script as plain data.
There is no escaping step to get wrong because there is nothing to escape: a
value containing `"; Remove-Item ...; "` is just a string with those
characters in it.
"""

import asyncio
import logging
import shutil

import winutil

log = logging.getLogger("jarvis.notifier")

# A notification is a glance, not an essay -- keep it short. These bound what
# we pass to the notification regardless of how long the source text (a
# session title, a transcript line) actually is.
_TITLE_MAX = 120
_SUBTITLE_MAX = 120
_MESSAGE_MAX = 300

# PowerShell takes a second to start and the balloon is held for a few more.
_TIMEOUT_SECONDS = 20.0

# Fixed script, no untrusted text ever enters this string.
_NOTIFY_SCRIPT = """\
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$n = New-Object System.Windows.Forms.NotifyIcon
$n.Icon = [System.Drawing.SystemIcons]::Information
$n.Visible = $true
$title = $env:JARVIS_NOTIFY_TITLE
if (-not $title) { $title = 'JARVIS' }
$text = $env:JARVIS_NOTIFY_MESSAGE
if ($env:JARVIS_NOTIFY_SUBTITLE) { $text = $env:JARVIS_NOTIFY_SUBTITLE + [Environment]::NewLine + $text }
if (-not $text) { $text = ' ' }
$n.BalloonTipTitle = $title
$n.BalloonTipText = $text
$n.ShowBalloonTip(8000)
Start-Sleep -Seconds 5
$n.Visible = $false
$n.Dispose()
"""


def _truncate(text: str, limit: int) -> str:
    """Bound text length for a glanceable notification, marking any cut."""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"  # ellipsis


def available() -> bool:
    """Whether posting a notification is plausible right now.

    Cheap and side-effect free: PowerShell is on PATH. This is a precondition
    check, not a delivery guarantee -- Focus Assist or per-app notification
    settings can still silently drop the notification.
    """
    return shutil.which("powershell.exe") is not None


async def notify(title: str, message: str, *, subtitle: str = "") -> bool:
    """Post a notification. Returns whether it was handed off successfully.

    This is a fallback path for when nobody is listening on the voice channel,
    so it must never raise: any failure (no PowerShell, non-zero exit,
    timeout, spawn error) is logged as a warning and reported back as False.
    The process runs as a subprocess so it never blocks the event loop, and is
    bounded by _TIMEOUT_SECONDS so a wedged one cannot hang the caller.
    """
    try:
        if not available():
            log.warning("notifier: notifications unavailable (no PowerShell)")
            return False
        return await _notify_windows(
            _truncate(str(title or ""), _TITLE_MAX),
            _truncate(str(message or ""), _MESSAGE_MAX),
            _truncate(str(subtitle or ""), _SUBTITLE_MAX))
    except Exception as e:
        # Belt and suspenders: this path must never raise into the caller.
        log.warning(f"notifier: unexpected error posting notification: {e}")
        return False


async def _notify_windows(title: str, message: str, subtitle: str) -> bool:
    """Post the notification through PowerShell. Never raises."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *winutil.powershell_argv(_NOTIFY_SCRIPT),
            env=winutil.with_env(JARVIS_NOTIFY_TITLE=title,
                                 JARVIS_NOTIFY_MESSAGE=message,
                                 JARVIS_NOTIFY_SUBTITLE=subtitle),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as e:
        log.warning(f"notifier: failed to spawn powershell: {e}")
        return False
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(),
                                           timeout=_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        log.warning("notifier: powershell timed out, killing it")
        try:
            proc.kill()
            await proc.communicate()
        except Exception:
            pass
        return False
    if proc.returncode != 0:
        log.warning(f"notifier: powershell exited {proc.returncode}: "
                    f"{stderr.decode(errors='replace').strip()}")
        return False
    return True
