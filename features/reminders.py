"""Timers, alarms, reminders and habit nudges.

One store (`reminders.json`), one job. A reminder is `{id, text, due, every,
window, nudge}`: `every` (minutes) makes it recur, `window` ("09:00-18:00")
limits when a recurring one may fire, and `nudge` marks a gentle one (habit
nudges are spoken non-urgently, so a focus session holds them back).
"""
import re
import time
import uuid
from datetime import datetime, timedelta

import toolkit

MAX_REMINDERS = 40
TIME_RE = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*$", re.I)


def parse_at(text: str, now: datetime) -> datetime:
    """'15:30', '3pm', '3:15 pm' (today, or tomorrow if past) or an ISO date-time."""
    t = str(text or "").strip()
    m = TIME_RE.match(t)
    if m:
        hour, minute, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
        if ap == "pm" and hour < 12:
            hour += 12
        if ap == "am" and hour == 12:
            hour = 0
        if hour > 23 or minute > 59:
            raise ValueError("That isn't a time")
        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return due if due > now else due + timedelta(days=1)
    try:
        return datetime.fromisoformat(t)
    except ValueError:
        raise ValueError("Give me a time like 15:30, 3pm, or a date and time")


def say_when(due: float, now: float) -> str:
    d = datetime.fromtimestamp(due)
    secs = due - now
    if secs < 90:
        return "in a minute"
    if secs < 3600:
        return f"in {int(round(secs / 60))} minutes"
    if d.date() == datetime.fromtimestamp(now).date():
        return f"at {d.hour}:{d.minute:02d}"
    return f"on {d.strftime('%A')} at {d.hour}:{d.minute:02d}"


def in_window(window: str, now: datetime) -> bool:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})", window or "")
    if not m:
        return True
    a, b = int(m.group(1)) * 60 + int(m.group(2)), int(m.group(3)) * 60 + int(m.group(4))
    cur = now.hour * 60 + now.minute
    return a <= cur <= b if a <= b else (cur >= a or cur <= b)


def handler(args: dict) -> str:
    action = str(args.get("action") or "list").lower()
    items = toolkit.load_json("reminders", [])
    now = time.time()
    if action == "list":
        if not items:
            return "Nothing is set, sir."
        return "; ".join(f"{i['text']} ({say_when(i['due'], now)}"
                         f"{', every ' + str(i['every']) + ' min' if i.get('every') else ''})"
                         for i in sorted(items, key=lambda i: i["due"])) + "."
    if action == "clear":
        toolkit.save_json("reminders", [])
        return "All cleared, sir."
    text = toolkit.clean(args.get("text"), 120)
    if action == "cancel":
        if not text:
            return "Cancel which one, sir?"
        keep = [i for i in items if text.lower() not in i["text"].lower()]
        if len(keep) == len(items):
            return "I haven't one like that, sir."
        toolkit.save_json("reminders", keep)
        return f"Cancelled {len(items) - len(keep)}, sir."
    if action != "add":
        return "I can add, list, cancel or clear, sir."
    if len(items) >= MAX_REMINDERS:
        return "That's too many reminders, sir — cancel a few first."
    if not text:
        text = "Time is up"
    nowdt = datetime.now()
    try:
        if args.get("minutes") not in (None, ""):
            minutes = float(args["minutes"])
            if not 0.1 <= minutes <= 60 * 24 * 365:
                return "That's not a sensible length of time, sir."
            due = now + minutes * 60
        elif args.get("at"):
            due = parse_at(args["at"], nowdt).timestamp()
        else:
            return "When, sir?"
        every = float(args.get("every_minutes") or 0)
    except (ValueError, TypeError) as e:
        return f"{e}, sir." if str(e) else "I didn't follow that time, sir."
    if every and not 5 <= every <= 60 * 24 * 7:
        return "A repeat has to be between five minutes and a week, sir."
    items.append({"id": uuid.uuid4().hex[:8], "text": text, "due": due,
                  "every": every or 0, "window": toolkit.clean(args.get("window"), 12),
                  "nudge": bool(args.get("nudge"))})
    toolkit.save_json("reminders", items)
    return f"I'll remind you {say_when(due, now)}, sir."


async def tick() -> None:
    items = toolkit.load_json("reminders", [])
    if not items:
        return
    now = time.time()
    keep, changed = [], False
    for i in items:
        if i["due"] > now:
            keep.append(i)
            continue
        if i.get("every"):
            step = i["every"] * 60
            i["due"] += step * (int((now - i["due"]) // step) + 1)
            keep.append(i)
            changed = True
            if not in_window(i.get("window", ""), datetime.now()):
                continue
            await toolkit.say(i["text"] + ", sir.", urgent=False)
            continue
        changed = True
        late = now - i["due"] > 120
        sent = await toolkit.say(("Sir, you asked me to remind you: " if late else "Sir — ")
                                 + i["text"] + ".", urgent=not i.get("nudge"))
        if not sent:                     # held back (focus) or nobody to hear: try again soon
            i["due"] = now + 60
            keep.append(i)
    if changed:
        toolkit.save_json("reminders", keep)


toolkit.register(toolkit.Tool(
    name="reminder",
    description=("Timers, alarms, reminders and habit nudges. add with `text` and "
                 "either `minutes` (a timer: 'in 12 minutes') or `at` ('15:30', "
                 "'3pm' or a date-time). For a repeating nudge add `every_minutes` "
                 "(and `window` like '09:00-18:00', `nudge` true for gentle ones: "
                 "'remind me to drink water every hour'). Also list, cancel (by "
                 "words from its text) and clear."),
    schema={"type": "object", "properties": {
        "action": {"type": "string", "enum": ["add", "list", "cancel", "clear"]},
        "text": {"type": "string"}, "minutes": {"type": "number"},
        "at": {"type": "string"}, "every_minutes": {"type": "number"},
        "window": {"type": "string"}, "nudge": {"type": "boolean"}},
        "required": ["action"]},
    handler=handler, acting=True,
    exempt="it stores the user's own words and reads nothing foreign"))
toolkit.register_job(toolkit.Job("reminders", 5.0, tick))
