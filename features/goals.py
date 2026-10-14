"""Multi-step goals: break a goal into tasks, keep them, check in on them."""
import time
import uuid
from datetime import datetime

import toolkit

MAX_GOALS, MAX_TASKS = 10, 30


def open_goals() -> list[dict]:
    return [g for g in toolkit.load_json("goals", []) if not g.get("done")]


def brief_lines() -> list[str]:
    out = []
    for g in open_goals()[:4]:
        todo = [t["text"] for t in g["tasks"] if not t["done"]]
        due = f", due {g['due']}" if g.get("due") else ""
        out.append(f"Goal '{g['title']}'{due}: {len(todo)} tasks left"
                   + (f"; next: {todo[0]}" if todo else ""))
    return out


def _find(goals, name):
    name = name.lower().strip()
    hits = [g for g in goals if name and name in g["title"].lower()]
    return hits[0] if len(hits) == 1 else None


def handler(args: dict) -> str:
    action = str(args.get("action") or "list").lower()
    goals = toolkit.load_json("goals", [])
    title = toolkit.clean(args.get("goal"), 80)
    tasks = [toolkit.clean(t, 120) for t in (args.get("tasks") or []) if toolkit.clean(t, 120)]
    if action == "list":
        lines = brief_lines()
        return "\n".join(lines) if lines else "You have no open goals, sir."
    if action == "add":
        if not title:
            return "What's the goal, sir?"
        if len(open_goals()) >= MAX_GOALS:
            return "That's plenty of goals, sir — finish or drop one first."
        due = toolkit.clean(args.get("due"), 20)
        goals.append({"id": uuid.uuid4().hex[:8], "title": title, "due": due, "done": False,
                      "created": time.time(), "tasks": [{"text": t, "done": False} for t in tasks[:MAX_TASKS]]})
        toolkit.save_json("goals", goals)
        return f"Goal '{title}' set with {len(tasks)} tasks, sir."
    g = _find(goals, title)
    if g is None:
        return "Which goal, sir? I couldn't match that to exactly one."
    if action == "show":
        return f"{g['title']}: " + "; ".join(("✓ " if t["done"] else "• ") + t["text"] for t in g["tasks"])
    if action == "add_tasks":
        g["tasks"].extend({"text": t, "done": False} for t in tasks)
        g["tasks"] = g["tasks"][:MAX_TASKS]
    elif action == "done_task":
        hit = 0
        for t in g["tasks"]:
            if any(w.lower() in t["text"].lower() for w in tasks) and not t["done"]:
                t["done"], hit = True, hit + 1
        if not hit:
            return "I couldn't match that task, sir."
        if all(t["done"] for t in g["tasks"]):
            g["done"] = True
    elif action == "complete":
        g["done"] = True
    elif action == "drop":
        goals = [x for x in goals if x is not g]
    else:
        return "I can add, show, list, add tasks, tick tasks off, complete or drop goals, sir."
    toolkit.save_json("goals", goals)
    return "Done, sir." + (" That completes the goal — well done." if g.get("done") else "")


toolkit.register(toolkit.Tool(
    name="goals",
    description=("Long goals broken into tasks. For 'plan my launch next week': work out "
                 "the tasks yourself, then `add` with `goal`, `tasks` and optional `due`. "
                 "Also show, list, add_tasks, done_task (`tasks` = words from the task), "
                 "complete, drop. Open goals appear in the daily brief."),
    schema={"type": "object", "properties": {
        "action": {"type": "string", "enum": ["add", "show", "list", "add_tasks", "done_task", "complete", "drop"]},
        "goal": {"type": "string"}, "due": {"type": "string"},
        "tasks": {"type": "array", "items": {"type": "string"}}}, "required": ["action"]},
    handler=handler, acting=True, exempt="it stores the user's own words and reads nothing foreign"))
