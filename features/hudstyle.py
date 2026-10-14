"""HUD themes and sound cues, switched by voice (the page remembers them)."""
import toolkit

THEMES = ("reactor", "blackhole", "moon")


async def handler(args: dict) -> str:
    msg = {"type": "hud", "action": "style"}
    said = []
    theme = str(args.get("theme") or "").lower()
    if theme:
        if theme not in THEMES:
            return "I have " + ", ".join(THEMES) + ", sir."
        msg["theme"] = theme
        said.append(f"{theme} theme")
    if args.get("sounds") is not None:
        msg["sounds"] = bool(args["sounds"])
        said.append("sounds " + ("on" if msg["sounds"] else "off"))
    if args.get("dim") is not None:
        msg["dim"] = bool(args["dim"])
        said.append("night mode " + ("on" if msg["dim"] else "off"))
    if not said:
        return "Tell me a theme, sounds, or night mode, sir."
    await toolkit.emit(msg)
    return "Set: " + ", ".join(said) + ", sir."


toolkit.register(toolkit.Tool(
    name="hud_style",
    description=("Change how his display looks and sounds: `theme` reactor, blackhole "
                 "or moon; `sounds` true/false for the little listening/working/done "
                 "cues; `dim` true/false for night mode."),
    schema={"type": "object", "properties": {
        "theme": {"type": "string", "enum": list(THEMES)},
        "sounds": {"type": "boolean"}, "dim": {"type": "boolean"}}},
    handler=handler, exempt="it only changes the page's look"))
