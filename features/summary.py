"""End-of-day / weekly summary, and a usage forecast."""
import subprocess
import time
from datetime import datetime, timedelta

import toolkit


def _commits(path: str, since: str) -> list[str]:
    try:
        out = subprocess.run(["git", "-C", path, "log", f"--since={since}", "--oneline", "-n", "15",
                              "--no-merges"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    return out.stdout.splitlines() if out.returncode == 0 else []


def build(period: str = "day") -> str:
    import run_store
    days = 7 if period == "week" else 1
    now = datetime.now()
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    lines = [f"Period: {'the last 7 days' if days == 7 else 'today'} (since {start:%A %H:%M})."]
    try:
        runs = [r for r in run_store.list_runs(limit=200) if r["created_at"] >= start.timestamp()]
    except Exception:
        runs = []
    if runs:
        counts: dict = {}
        for r in runs:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        lines.append("Runs: " + ", ".join(f"{n} {s}" for s, n in sorted(counts.items())) + ".")
        by_project: dict = {}
        for r in runs:
            by_project.setdefault(r["project_name"], []).append(r)
        for name, rs in list(by_project.items())[:8]:
            done = [r for r in rs if r["status"] == "succeeded" and r.get("summary")]
            lines.append(f"- {name}: {len(rs)} runs" + (f"; latest: {done[0]['summary'][:140]}" if done else ""))
    else:
        lines.append("Runs: none.")
    total = 0
    for p in toolkit.Hooks.project_paths()[:12]:
        c = _commits(str(p), start.isoformat())
        if c:
            total += len(c)
            lines.append(f"- commits in {getattr(p, 'name', p)}: {len(c)} (e.g. {c[0][:90]})")
    if not total:
        lines.append("Commits: none found.")
    rem = [r for r in toolkit.load_json("reminders", []) if r["due"] > time.time() and not r.get("every")]
    if rem:
        lines.append(f"Still pending: {len(rem)} reminders.")
    return "\n".join(lines)


def forecast() -> str:
    import usage_store
    snap = usage_store.snapshot()
    if not snap.get("measured"):
        return "I have no usage reading yet, sir."
    spans = {"five_hour": 5 * 3600, "seven_day": 7 * 86400}
    now, out = time.time(), []
    for w in snap["windows"]:
        pct, resets, span = w.get("utilization"), w.get("resets_at"), spans.get(w["key"])
        if pct is None or resets is None or span is None or w.get("expired"):
            continue
        elapsed = span - (resets - now)
        if elapsed < span * 0.08 or pct <= 0:
            out.append(f"{w['label']}: {int(pct)} percent used, too early to project.")
            continue
        projected = pct * span / elapsed
        if projected >= 100:
            hours = (100 - pct) / (pct / elapsed) / 3600
            out.append(f"{w['label']}: {int(pct)} percent used; at this rate you hit the limit in "
                       f"about {hours:.1f} hours, before it resets.")
        else:
            out.append(f"{w['label']}: {int(pct)} percent used; on pace to finish near {int(projected)} percent.")
    return " ".join(out) or "I can't project that yet, sir."


def handler(args: dict) -> str:
    if str(args.get("what") or "summary").lower() == "forecast":
        return forecast()
    return build("week" if str(args.get("period")).lower() == "week" else "day")


toolkit.register(toolkit.Tool(
    name="daily_summary",
    description=("What the user got done: runs, commits in their projects and pending "
                 "reminders, for `period` day (default) or week — 'what did I get done "
                 "today?', 'end of day report'. Or `what` = forecast: 'at this rate "
                 "when do I hit my Claude limit?'. Report it in a few spoken sentences."),
    schema={"type": "object", "properties": {
        "period": {"type": "string", "enum": ["day", "week"]},
        "what": {"type": "string", "enum": ["summary", "forecast"]}}},
    handler=handler, taint="your runs and commit messages", wrap=True))
