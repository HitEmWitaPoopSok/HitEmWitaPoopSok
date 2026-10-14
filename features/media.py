"""Media keys: play/pause, next, previous, volume, mute — works with Spotify, YouTube, anything."""
from features import _ps
import toolkit

KEYS = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "volume_up": 0xAF,
        "volume_down": 0xAE, "mute": 0xAD}
SCRIPT = r"""
Add-Type -Namespace J -Name K -MemberDefinition '[DllImport("user32.dll")] public static extern void keybd_event(byte b, byte s, int f, int e);'
$vk = [int]$env:JARVIS_VK
$n = [Math]::Max(1, [Math]::Min(10, [int]$env:JARVIS_TIMES))
for ($i = 0; $i -lt $n; $i++) { [J.K]::keybd_event($vk, 0, 0, 0); [J.K]::keybd_event($vk, 0, 2, 0); Start-Sleep -Milliseconds 30 }
Write-Output ok
"""


async def handler(args: dict) -> str:
    action = str(args.get("action") or "").lower()
    if action not in KEYS:
        return "I can play, pause, skip, go back, or change the volume, sir."
    try:
        times = max(1, min(10, int(args.get("times") or (5 if action.startswith("volume") else 1))))
    except (TypeError, ValueError):
        times = 1
    code, out, _ = await _ps.run(SCRIPT, {"JARVIS_VK": str(KEYS[action]), "JARVIS_TIMES": str(times)})
    return "Done, sir." if code == 0 and out.strip() == "ok" else "Windows wouldn't take that, sir."


toolkit.register(toolkit.Tool(
    name="media_control",
    description=("Control whatever is playing, with the media keys: play_pause, next, "
                 "previous, volume_up, volume_down, mute. `times` repeats volume steps "
                 "(each is about 2%; default 5)."),
    schema={"type": "object", "properties": {
        "action": {"type": "string", "enum": list(KEYS)}, "times": {"type": "integer"}},
        "required": ["action"]},
    handler=handler, acting=True, exempt="it presses a media key and reads nothing"))
