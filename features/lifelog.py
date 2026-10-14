"""A private, local life log of the window in front, searchable by voice.

OFF until the user turns it on, kept only on this machine, pruned after 30
days, and wiped on request.
"""
import json
import time
from datetime import datetime, timedelta

import toolkit

RETENTION_DAYS = 30
MAX_RESULTS = 25


def _file():
    return toolkit.store_path("lifelog").with_suffix(".jsonl")


def enabled() -> bool:
    return bool(toolkit.load_json("lifelog_config", {}).get("on"))


async def tick() -> None:
    if not enabled():
        return
    import window_manager
    try:
        wins = await window_manager.list_windows()
    except Exception:
        return
    front = next((w for w in wins if w.front), None)
    if not front:
        return
    entry = {"t": int(time.time()), "app": front.process, "title": front.title[:120]}
    last = None
    try:
        with open(_file(), "rb") as f:
            f.seek(max(0, _file().stat().st_size - 600))
            tail = f.read().decode("utf-8", "replace").splitlines()
        last = json.loads(tail[-1]) if tail else None
    except (OSError, ValueError, IndexError):
        pass
    if last and last.get("app") == entry["app"] and last.get("title") == entry["title"]:
        return
    _file().parent.mkdir(parents=True, exist_ok=True)
    with open(_file(), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _read(since: float) -> list[dict]:
    rows = []
    try:
        for line in _file().read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("t", 0) >= since:
                rows.append(r)
    except OSError:
        pass
    return rows


def prune() -> None:
    rows = _read(time.time() - RETENTION_DAYS * 86400)
    try:
        _file().write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    except OSError:
        pass


def handler(args: dict) -> str:
    action = str(args.get("action") or "status").lower()
    cfg = toolkit.load_json("lifelog_config", {})
    if action == "on":
        cfg["on"] = True
        toolkit.save_json("lifelog_config", cfg)
        return "Life log on, sir. I note which window is in front, on this machine only."
    if action == "off":
        cfg["on"] = False
        toolkit.save_json("lifelog_config", cfg)
        return "Life log off, sir. What I've kept stays until you tell me to wipe it."
    if action == "wipe":
        try:
            _file().unlink()
        except OSError:
            pass
        return "Wiped, sir."
    if action == "status":
        n = len(_read(0))
        return f"The life log is {'on' if cfg.get('on') else 'off'} with {n} entries, sir."
    if action in ("search", "summary"):
        day = str(args.get("day") or "").lower()
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        if day in ("", "today"):
            start, end = today, today + timedelta(days=1)
        elif day == "yesterday":
            start, end = today - timedelta(days=1), today
        else:
            try:
                start = datetime.fromisoformat(day)
            except ValueError:
                try:
                    start = today - timedelta(days=int(args.get("days_ago")))
                except (TypeError, ValueError):
                    return "Which day, sir?"
            end = start + timedelta(days=1)
        rows = [r for r in _read(start.timestamp()) if r["t"] < end.timestamp()]
        query = toolkit.clean(args.get("query"), 60).lower()
        if query:
            rows = [r for r in rows if query in (r["app"] + " " + r["title"]).lower()]
        if not rows:
            return "I have nothing logged for that, sir."
        if action == "summary":
            spent: dict = {}
            for a, b in zip(rows, rows[1:] + [{"t": min(rows[-1]["t"] + 60, end.timestamp())}]):
                spent[a["app"]] = spent.get(a["app"], 0) + min(b["t"] - a["t"], 900)
            top = sorted(spent.items(), key=lambda kv: -kv[1])[:8]
            return "Time in front (approx): " + ", ".join(f"{a} {int(s / 60)} min" for a, s in top)
        return "\n".join(f"{datetime.fromtimestamp(r['t']):%a %H:%M} {r['app']}: {r['title']}"
                         for r in rows[-MAX_RESULTS:])
    return "I can turn the log on or off, search it, summarise a day, or wipe it, sir."


toolkit.register(toolkit.Tool(
    name="life_log",
    description=("A private searchable timeline of which window was in front. Off until "
                 "the user says so: `on`, `off`, `wipe`, `status`. `search` (with `query` "
                 "and `day` today/yesterday/an ISO date, or `days_ago`) answers 'what was "
                 "I working on Tuesday?'; `summary` gives time per app for a day."),
    schema={"type": "object", "properties": {
        "action": {"type": "string", "enum": ["on", "off", "wipe", "status", "search", "summary"]},
        "query": {"type": "string"}, "day": {"type": "string"}, "days_ago": {"type": "integer"}},
        "required": ["action"]},
    handler=handler, acting=True, reading=True, taint="your window titles", wrap=True))
toolkit.register_job(toolkit.Job("lifelog", 60.0, tick))
