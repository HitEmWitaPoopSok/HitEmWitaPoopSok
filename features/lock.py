"""The voice lock: risky tools need a click on his display first.

Anyone who can talk to the microphone — a person across the room, a video
playing aloud — can ask him to do things. With the lock on, tools that DO
things in the real world (lights, windows, other apps, runs) refuse until the
user presses **Unlock** on the HUD, which holds for ten minutes.

This guards against a voice, not against someone sitting at your keyboard
(they can press the button too). It is a deliberate, honest speed bump, and it
logs nothing secret: there is no spoken passphrase to leak.
"""
import time

import toolkit

SENSITIVE = {"smart_home", "browse", "manage_window", "desktop_ui", "run_command", "spawn_run",
             "start_build", "steer_session", "fix_yourself", "routine", "voice_mode"}
DEFAULT_MINUTES, MAX_MINUTES = 10, 60
_state = {"until": 0.0}


def enabled() -> bool:
    return bool(toolkit.load_json("lock", {}).get("enabled"))


def unlocked() -> bool:
    return _state["until"] > time.time()


def unlock(minutes: float = DEFAULT_MINUTES) -> float:
    minutes = max(1.0, min(float(minutes), MAX_MINUTES))
    _state["until"] = time.time() + minutes * 60
    return _state["until"]


def lock_now() -> None:
    _state["until"] = 0.0


def status() -> dict:
    left = max(0, int(_state["until"] - time.time()))
    return {"enabled": enabled(), "unlocked": unlocked(), "seconds_left": left}


def gate(tool: str):
    if tool not in SENSITIVE or not enabled() or unlocked():
        return None
    return ("locked — that needs your say-so on my display, sir. Press Unlock, "
            "then ask me again.")


def handler(args: dict) -> str:
    action = str(args.get("action") or "status").lower()
    if action == "enable":
        toolkit.save_json("lock", {"enabled": True})
        lock_now()
        return "Voice lock on, sir. Risky actions now wait for you to press Unlock on my display."
    if action == "disable":
        if enabled() and not unlocked():
            return "That needs your say-so on my display first, sir. Press Unlock, then ask again."
        toolkit.save_json("lock", {"enabled": False})
        return "Voice lock off, sir."
    if action == "lock":
        lock_now()
        return "Locked, sir."
    if action == "status":
        s = status()
        if not s["enabled"]:
            return "The voice lock is off, sir."
        return ("The voice lock is on and open for another "
                f"{s['seconds_left'] // 60 + 1} minutes, sir." if s["unlocked"]
                else "The voice lock is on, and locked, sir.")
    return "I can enable, disable, lock now, or say the status, sir."


toolkit.add_gate(gate)
toolkit.register(toolkit.Tool(
    name="voice_lock",
    description=("The voice lock: `enable`, `disable`, `lock` (relock now) or `status`. With it "
                 "on, tools that act in the world refuse until the user presses Unlock on "
                 "his display; tell them to press it when a tool says it is locked."),
    schema={"type": "object", "properties": {
        "action": {"type": "string", "enum": ["enable", "disable", "lock", "status"]}},
        "required": ["action"]},
    handler=handler, acting=True, exempt="it flips one switch and reads nothing"))
