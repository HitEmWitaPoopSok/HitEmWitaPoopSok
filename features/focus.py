"""Focus mode: hold back non-urgent speech, tuck distractions away, say when time is up."""
import time

import toolkit

DEFAULT_MINUTES, MAX_MINUTES = 50, 480


def _state() -> dict:
    return toolkit.load_json("focus", {})


async def handler(args: dict) -> str:
    action = str(args.get("action") or "status").lower()
    st = _state()
    now = time.time()
    if action == "status":
        if toolkit.focus_active():
            return f"Focus is on, sir — about {int((st['until'] - now) / 60) + 1} minutes left."
        return "Focus mode is off, sir."
    if action == "stop":
        toolkit.save_json("focus", {})
        return "Focus ended, sir. Welcome back."
    if action == "distractions":
        names = [toolkit.clean(n, 30).lower().replace(".exe", "") for n in (args.get("apps") or [])]
        st["apps"] = [n for n in names if n][:15]
        toolkit.save_json("focus", st)
        return "I'll tuck " + (", ".join(st["apps"]) or "nothing") + " away when you focus, sir."
    if action != "start":
        return "I can start or stop focus, set its distractions, or say how long is left, sir."
    try:
        minutes = float(args.get("minutes") or DEFAULT_MINUTES)
    except (TypeError, ValueError):
        return "How many minutes, sir?"
    if not 1 <= minutes <= MAX_MINUTES:
        return "Focus can run from one minute to eight hours, sir."
    st.update(until=now + minutes * 60, announced=False)
    toolkit.save_json("focus", st)
    hidden = 0
    wm = toolkit.Hooks.handlers.get("manage_window")
    for app in st.get("apps", []):
        if wm:
            r = wm({"action": "minimize", "target": app})
            r = await r if hasattr(r, "__await__") else r
            hidden += "Minimised" in str(r)
    extra = f" I've tucked {hidden} away." if hidden else ""
    return f"Focus on for {int(minutes)} minutes, sir. I'll stay quiet unless it's urgent.{extra}"


async def tick() -> None:
    st = _state()
    if st.get("until") and not st.get("announced") and st["until"] <= time.time():
        st["announced"] = True
        toolkit.save_json("focus", st)
        await toolkit.say("Your focus session is over, sir. Well done.", urgent=True)


toolkit.register(toolkit.Tool(
    name="focus_mode",
    description=("Focus mode: `start` with `minutes` (default 50) — non-urgent speech "
                 "is held back and the user's chosen distraction apps are minimised; "
                 "`stop`; `status`; `distractions` with `apps` (process names like "
                 "'discord', 'steam') to set what gets tucked away."),
    schema={"type": "object", "properties": {
        "action": {"type": "string", "enum": ["start", "stop", "status", "distractions"]},
        "minutes": {"type": "number"}, "apps": {"type": "array", "items": {"type": "string"}}},
        "required": ["action"]},
    handler=handler, acting=True,
    exempt="it keeps the user's own settings and reads nothing foreign"))
toolkit.register_job(toolkit.Job("focus", 15.0, tick))
