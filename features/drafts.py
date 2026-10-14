"""Drafts the user dictates and approves: emails, messages, documents. Nothing is sent."""
import re

import toolkit
from features import _ps

MAX_CHARS = 20000


def _dir():
    d = toolkit.store_path("x").parent / "drafts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", toolkit.clean(name, 40).lower()).strip("-") or "draft"


async def handler(args: dict) -> str:
    action = str(args.get("action") or "list").lower()
    name = _slug(args.get("name") or "")
    path = _dir() / f"{name}.txt"
    if action == "list":
        names = sorted(p.stem for p in _dir().glob("*.txt"))
        return ("Drafts: " + ", ".join(names) + ".") if names else "You have no drafts, sir."
    if action == "save":
        text = str(args.get("text") or "")[:MAX_CHARS]
        if not text.strip():
            return "There's nothing to save, sir."
        path.write_text(text, encoding="utf-8")
        return f"Draft '{name}' saved, sir."
    if not path.is_file():
        return "I don't have that draft, sir."
    if action == "show":
        return path.read_text(encoding="utf-8")
    if action == "copy":
        code, _, _ = await _ps.run("Set-Clipboard -Value $env:JARVIS_CLIP",
                                   {"JARVIS_CLIP": path.read_text(encoding="utf-8")})
        return "It's on your clipboard, sir — paste it where you like." if code == 0 else "I couldn't reach the clipboard, sir."
    if action == "delete":
        path.unlink()
        return "Deleted, sir."
    return "I can save, show, copy, delete or list drafts, sir."


toolkit.register(toolkit.Tool(
    name="drafts",
    description=("Compose with the user: write the email, message or document they "
                 "asked for, read it back, revise it with them, then `save` it by `name` "
                 "(with `text`). `copy` puts a saved draft on the clipboard to paste "
                 "into their mail app. You can never send anything. Also show, delete, list."),
    schema={"type": "object", "properties": {
        "action": {"type": "string", "enum": ["save", "show", "copy", "delete", "list"]},
        "name": {"type": "string"}, "text": {"type": "string"}}, "required": ["action"]},
    handler=handler, acting=True, exempt="it keeps the user's own drafts and reads nothing foreign"))
