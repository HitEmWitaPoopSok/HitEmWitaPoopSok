"""Push to the user's phone through ntfy.sh (free; install the ntfy app and subscribe
to your private topic). Urgent things, and anything when no page is open, also go to the phone.

NTFY_TOPIC is effectively a password: anyone who knows it can read what is sent,
so pick something long and random. Nothing sensitive is ever sent: only the
sentence he would have spoken.
"""
import os
import re

import httpx

import toolkit

TOPIC_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")


def topic() -> str:
    t = os.environ.get("NTFY_TOPIC", "").strip()
    return t if TOPIC_RE.fullmatch(t) else ""


def enabled() -> bool:
    return bool(topic()) and bool(toolkit.load_json("phone", {}).get("on", True))


async def push(text: str, title: str = "JARVIS") -> bool:
    if not topic():
        return False
    try:
        async with httpx.AsyncClient(timeout=6.0) as http:
            r = await http.post(f"https://ntfy.sh/{topic()}", content=text.encode("utf-8"),
                                headers={"Title": title})
        return r.status_code < 300
    except Exception:
        return False


async def handler(args: dict) -> str:
    action = str(args.get("action") or "status").lower()
    cfg = toolkit.load_json("phone", {})
    if action in ("on", "off"):
        cfg["on"] = action == "on"
        toolkit.save_json("phone", cfg)
    elif action == "test":
        if not topic():
            return "Your phone isn't set up, sir. Add an ntfy topic in my settings."
        return "Sent, sir." if await push("This is JARVIS. Your phone is connected.") else "That didn't go through, sir."
    elif action != "status":
        return "I can switch phone alerts on or off, test them, or say the status, sir."
    if not topic():
        return "Your phone isn't set up, sir. Add an ntfy topic in my settings."
    return f"Phone alerts are {'on' if cfg.get('on', True) else 'off'}, sir."


toolkit.Hooks.phone = push
toolkit.register(toolkit.Tool(
    name="phone_alerts",
    description=("Phone push notifications via ntfy: `on`, `off`, `test`, `status`. When on, "
                 "urgent alerts and reminders also reach the user's phone, and so does "
                 "anything he says while no page is open."),
    schema={"type": "object", "properties": {
        "action": {"type": "string", "enum": ["on", "off", "test", "status"]}}},
    handler=handler, acting=True, exempt="it only sends the user's own alert sentences out"))
