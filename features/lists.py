"""Shopping and to-do lists, and 'where I put it' notes: plain named lists."""
import toolkit

MAX_LISTS, MAX_ITEMS = 20, 100


def handler(args: dict) -> str:
    action = str(args.get("action") or "show").lower()
    name = toolkit.clean(args.get("list") or "shopping", 30).lower() or "shopping"
    data = toolkit.load_json("lists", {})
    items = [toolkit.clean(i, 100) for i in (args.get("items") or []) if toolkit.clean(i, 100)]
    if isinstance(args.get("items"), str):
        items = [toolkit.clean(args["items"], 100)]
    if action == "all":
        if not data:
            return "You have no lists, sir."
        return "Your lists: " + ", ".join(f"{k} ({len(v)})" for k, v in sorted(data.items())) + "."
    if action == "show":
        got = data.get(name, [])
        return f"Your {name} list: " + "; ".join(got) + "." if got else f"Your {name} list is empty, sir."
    if action == "add":
        if not items:
            return "Add what, sir?"
        if name not in data and len(data) >= MAX_LISTS:
            return "That's too many lists, sir."
        cur = data.setdefault(name, [])
        added = [i for i in items if i.lower() not in (c.lower() for c in cur)]
        if len(cur) + len(added) > MAX_ITEMS:
            return "That list is full, sir."
        cur.extend(added)
        toolkit.save_json("lists", data)
        return f"Added {len(added)} to your {name} list, sir." if added else "Already on it, sir."
    if action in ("remove", "done"):
        cur = data.get(name, [])
        keep = [c for c in cur if not any(i.lower() in c.lower() for i in items)]
        if len(keep) == len(cur):
            return "I couldn't find that on the list, sir."
        data[name] = keep
        if not keep:
            data.pop(name)
        toolkit.save_json("lists", data)
        return f"Removed {len(cur) - len(keep)}, sir."
    if action == "clear":
        data.pop(name, None)
        toolkit.save_json("lists", data)
        return f"Your {name} list is cleared, sir."
    return "I can add, remove, show, clear or list them all, sir."


toolkit.register(toolkit.Tool(
    name="lists",
    description=("Named lists: shopping (the default), todo, and anything else. "
                 "add / remove (also 'done') / show / clear one, or `all` for the "
                 "names. Also for 'where I put it' notes: use list 'places' with "
                 "an item like 'passport: blue drawer' and show it later."),
    schema={"type": "object", "properties": {
        "action": {"type": "string", "enum": ["add", "remove", "done", "show", "clear", "all"]},
        "list": {"type": "string"},
        "items": {"type": "array", "items": {"type": "string"}}},
        "required": ["action"]},
    handler=handler, acting=True,
    exempt="it stores the user's own words and reads nothing foreign"))
