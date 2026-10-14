"""Routines: named chains of steps the user defines by voice ("good night")."""
import toolkit

# Only these may appear in a routine. None of them can run a program or send
# anything off the machine.
STEP_TOOLS = {"smart_home", "manage_window", "reminder", "show_hud", "media_control",
              "focus_mode", "brief_settings", "lists", "hud_style"}
MAX_STEPS, MAX_ROUTINES = 12, 20


def _valid(steps) -> list[dict]:
    if not isinstance(steps, list) or not steps:
        raise ValueError("A routine needs steps")
    if len(steps) > MAX_STEPS:
        raise ValueError(f"A routine holds {MAX_STEPS} steps at most")
    out = []
    for s in steps:
        if not isinstance(s, dict) or s.get("tool") not in STEP_TOOLS \
                or not isinstance(s.get("args", {}), dict):
            raise ValueError("A step can only use " + ", ".join(sorted(STEP_TOOLS)))
        out.append({"tool": s["tool"], "args": s.get("args", {})})
    return out


async def handler(args: dict) -> str:
    action = str(args.get("action") or "list").lower()
    name = toolkit.clean(args.get("name"), 40).lower()
    data = toolkit.load_json("routines", {})
    if action == "list":
        return ("Your routines: " + ", ".join(sorted(data)) + ".") if data else "You have no routines yet, sir."
    if action == "show":
        r = data.get(name)
        if not r:
            return "I don't have that routine, sir."
        return f"{name}: " + "; ".join(f"{s['tool']} {s['args']}" for s in r) + "."
    if action == "delete":
        if data.pop(name, None) is None:
            return "I don't have that routine, sir."
        toolkit.save_json("routines", data)
        return "Deleted, sir."
    if action == "save":
        if not name:
            return "What shall I call it, sir?"
        try:
            steps = _valid(args.get("steps"))
        except ValueError as e:
            return f"{e}, sir."
        if name not in data and len(data) >= MAX_ROUTINES:
            return "That's too many routines, sir."
        data[name] = steps
        toolkit.save_json("routines", data)
        return f"Saved '{name}' with {len(steps)} steps, sir."
    if action == "run":
        steps = data.get(name)
        if not steps:
            return "I don't have that routine, sir."
        done, failed = 0, []
        for s in steps:
            fn = toolkit.Hooks.handlers.get(s["tool"])
            if fn is None or s["tool"] not in STEP_TOOLS:
                failed.append(s["tool"])
                continue
            try:
                r = fn(dict(s["args"]))
                if hasattr(r, "__await__"):
                    await r
                done += 1
            except Exception:
                failed.append(s["tool"])
        return (f"{name} done, sir." if not failed
                else f"{name}: {done} steps done, {len(failed)} failed ({', '.join(failed)}), sir.")
    return "I can save, run, show, delete or list routines, sir."


toolkit.register(toolkit.Tool(
    name="routine",
    description=("Routines — named chains of steps. `save` with `name` and `steps` "
                 "[{tool, args}] using only: smart_home, manage_window, reminder, "
                 "show_hud, media_control, focus_mode, brief_settings, lists, hud_style. "
                 "`run` by name when they say it ('good night', 'I'm home'). Also "
                 "list, show, delete. Build a routine only from what the user said."),
    schema={"type": "object", "properties": {
        "action": {"type": "string", "enum": ["save", "run", "show", "delete", "list"]},
        "name": {"type": "string"},
        "steps": {"type": "array", "items": {"type": "object", "properties": {
            "tool": {"type": "string"}, "args": {"type": "object"}}, "required": ["tool"]}}},
        "required": ["action"]},
    handler=handler, acting=True,
    exempt="steps are the user's own, validated against a short list of tools"))
