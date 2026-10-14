"""Voice modes that decide what happens to the words he hears: meeting notes,
dictation into the focused window, and a wake word.

All three are off until asked, announced when they start, and ended by a
spoken phrase or by the tool.
"""
import re
import time
from datetime import datetime

import toolkit
from features import _ps

NOTES_STOP = re.compile(r"\b(stop|end|finish)\b.*\b(notes|note taking|meeting)\b|\bthat'?s the meeting\b", re.I)
DICTATION_STOP = re.compile(r"\b(stop|end|finish)\b.*\b(dictat\w*|typing)\b", re.I)
WAKE_RE = re.compile(r"^\W*(?:(?:hey|ok|okay|hi|yo)\s+)?jarvis\b[\s,.:;!?-]*", re.I)
CONVERSATION_WINDOW = 25.0
MAX_NOTES_CHARS = 200_000

_state = {"mode": "", "file": "", "last_heard": 0.0}

PASTE = r"""
Set-Clipboard -Value $env:JARVIS_TEXT
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait('^v')
Write-Output ok
"""


def notes_dir():
    d = toolkit.store_path("x").parent / "notes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def wake_on() -> bool:
    return bool(toolkit.load_json("modes", {}).get("wake"))


async def intercept(text: str):
    now = time.time()
    mode = _state["mode"]
    if mode == "notes":
        if NOTES_STOP.search(text):
            _state["mode"] = ""
            await toolkit.say("Notes saved, sir. Ask me to read or summarise them.", urgent=True)
            return None
        path = notes_dir() / _state["file"]
        if path.exists() and path.stat().st_size > MAX_NOTES_CHARS:
            _state["mode"] = ""
            await toolkit.say("The notes file is full, sir — I've stopped.", urgent=True)
            return None
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {text}\n")
        return None
    if mode == "dictation":
        if DICTATION_STOP.search(text):
            _state["mode"] = ""
            await toolkit.say("Dictation off, sir.", urgent=True)
            return None
        code, out, _ = await _ps.run(PASTE, {"JARVIS_TEXT": text.strip() + " "}, timeout=6.0)
        if code != 0 or out.strip() != "ok":
            _state["mode"] = ""
            await toolkit.say("I couldn't type that, sir, so I've stopped dictating.", urgent=True)
        return None
    if wake_on():
        m = WAKE_RE.match(text)
        if m:
            _state["last_heard"] = now
            rest = text[m.end():].strip()
            return rest or "Yes?"
        if now - _state["last_heard"] <= CONVERSATION_WINDOW:
            _state["last_heard"] = now
            return text
        return None
    return text


def handler(args: dict) -> str:
    action = str(args.get("action") or "status").lower()
    if action == "start_notes":
        name = datetime.now().strftime("%Y-%m-%d-%H%M") + ".txt"
        _state.update(mode="notes", file=name)
        return ("Taking notes, sir. I'll write down everything I hear and stay quiet "
                "until you say 'stop notes'.")
    if action == "start_dictation":
        _state["mode"] = "dictation"
        return ("Dictating, sir. Click where you want the text; I'll type what you say "
                "until you say 'stop dictating'.")
    if action == "stop":
        was, _state["mode"] = _state["mode"], ""
        return f"Stopped {was}, sir." if was else "Nothing was running, sir."
    if action in ("wake_on", "wake_off"):
        cfg = toolkit.load_json("modes", {})
        cfg["wake"] = action == "wake_on"
        toolkit.save_json("modes", cfg)
        return ("Wake word on, sir. Say 'Jarvis' first; after I reply I'll keep listening "
                "for a few seconds." if cfg["wake"] else "Wake word off, sir. I'll answer everything.")
    if action == "show_notes":
        files = sorted(notes_dir().glob("*.txt"), reverse=True)
        if not files:
            return "You have no notes, sir."
        if str(args.get("which") or "") == "list":
            return "Notes: " + ", ".join(f.stem for f in files[:10]) + "."
        return files[0].read_text(encoding="utf-8")[-12000:] or "That note is empty, sir."
    if action == "status":
        wake = "on" if wake_on() else "off"
        return f"Mode: {_state['mode'] or 'none'}; wake word {wake}."
    return "I can take notes, dictate, stop, show notes, or switch the wake word, sir."


toolkit.add_interceptor(intercept)
toolkit.register(toolkit.Tool(
    name="voice_mode",
    description=("Change what he does with what he hears. `start_notes` writes down "
                 "everything said (meetings) until the user says 'stop notes'; "
                 "`show_notes` returns the latest notes to summarise (untrusted — "
                 "other people spoke); `start_dictation` types what the user says into "
                 "the window they have focused until 'stop dictating'; `stop`; "
                 "`wake_on` / `wake_off` require saying 'Jarvis' before he answers."),
    schema={"type": "object", "properties": {
        "action": {"type": "string", "enum": ["start_notes", "show_notes", "start_dictation",
                                              "stop", "wake_on", "wake_off", "status"]},
        "which": {"type": "string"}}, "required": ["action"]},
    handler=handler, acting=True, reading=True, taint="your meeting notes", wrap=True))
