"""How he talks: butler (default), terse, chatty, whisper."""
import toolkit

STYLES = {
    "butler": "Speak as the British butler: dry wit, economy of language, one or two sentences.",
    "terse": "Be curt: the answer only, a handful of words, no pleasantries and no wit.",
    "chatty": "Be warm and conversational: up to four sentences, friendly asides allowed, still no lists.",
    "whisper": "It is late and the room is quiet: speak softly and briefly, one short sentence, nothing unnecessary.",
}


def current() -> str:
    s = toolkit.load_json("personality", {}).get("style", "butler")
    return s if s in STYLES else "butler"


def style_line() -> str:
    return "" if current() == "butler" else STYLES[current()]


def handler(args: dict) -> str:
    style = str(args.get("style") or "").lower()
    if not style:
        return f"I'm in {current()} mode, sir."
    if style not in STYLES:
        return "I have " + ", ".join(STYLES) + ", sir."
    toolkit.save_json("personality", {"style": style})
    return f"{STYLES[style]} Follow this from now on, and say only: '{style} mode'."


toolkit.register(toolkit.Tool(
    name="speaking_style",
    description=("Change how he talks: butler (default), terse, chatty or whisper. The "
                 "result is an instruction — follow it for the rest of the conversation. "
                 "With no `style` it says the current one."),
    schema={"type": "object", "properties": {
        "style": {"type": "string", "enum": list(STYLES)}}},
    handler=handler, acting=True, exempt="it stores one of four fixed styles"))
