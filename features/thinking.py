"""A second opinion from another model, and reading things aloud.

Both take longer than a tool call may (the brain's MCP child gives up after 20
seconds), so each starts background work and the result is SPOKEN when ready,
straight to the user, never routed back through the brain.
"""
import asyncio
import os
import re
import shutil
import tempfile

import claude_env
import toolkit

SECOND_MODEL_DEFAULT = "opus"
MAX_READ_CHARS = 12000
_tasks: set = set()
_reading: dict = {"task": None}


def _spawn(coro) -> None:
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


def sentences(text: str, limit: int) -> str:
    parts = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    return " ".join(parts[:limit])


async def _ask(question: str) -> None:
    model = os.environ.get("JARVIS_SECOND_MODEL", SECOND_MODEL_DEFAULT).strip() or SECOND_MODEL_DEFAULT
    claude = os.environ.get("JARVIS_CLAUDE_PATH") or shutil.which("claude") or "claude"
    prompt = ("Give an independent, candid second opinion on the question below, as a "
              "sharp advisor would: your recommendation first, then the two strongest "
              "reasons, then the biggest risk. Plain prose, under 120 words, no lists.\n\n"
              f"Question: {question}")
    try:
        with tempfile.TemporaryDirectory() as cwd:
            proc = await asyncio.create_subprocess_exec(
                *claude_env.command_argv(claude), "-p", prompt, "--model", model,
                "--tools", "", "--output-format", "text",
                cwd=cwd, env=claude_env.child_env(), stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=150)
        text = out.decode("utf-8", "replace").strip()
    except Exception:
        text = ""
    if not text:
        await toolkit.say("Sir, I couldn't get a second opinion just now.", urgent=True)
        return
    await toolkit.say("A second opinion, sir. " + sentences(text, 6), urgent=True, wait=True)


def ask_handler(args: dict) -> str:
    q = toolkit.clean(args.get("question"), 1200)
    if not q:
        return "What would you like a second opinion on, sir?"
    _spawn(_ask(q))
    return ("I'm asking another model, sir. It will take a minute; I'll tell you "
            "what it says when it's ready — don't answer for it.")


async def _read(text: str) -> None:
    for chunk in re.split(r"(?<=[.!?])\s+", text):
        if chunk.strip():
            try:
                await toolkit.say(chunk.strip(), urgent=False, wait=True)
            except asyncio.CancelledError:
                raise


async def read_handler(args: dict) -> str:
    if str(args.get("action") or "read").lower() == "stop":
        t = _reading.get("task")
        if t and not t.done():
            t.cancel()
            return "Stopped reading, sir."
        return "I wasn't reading, sir."
    source = str(args.get("source") or "clipboard").lower()
    text = ""
    if source == "clipboard":
        from features import clipboard
        text = await clipboard.handler({"action": "read"})
    elif source == "text":
        text = str(args.get("text") or "")
    elif source == "url":
        h = toolkit.Hooks.handlers.get("read_page")
        if h is None:
            return "I can't fetch pages just now, sir."
        got = h({"url": args.get("url")})
        text = await got if hasattr(got, "__await__") else str(got)
        text = re.sub(r"</?session-output[^>]*>", "", text)
    elif source == "file":
        from features import filefinder
        from pathlib import Path
        p = Path(str(args.get("path") or ""))
        if not p.is_absolute() or not p.is_file() or not filefinder.inside_roots(p) \
                or p.suffix.lower() not in {".txt", ".md", ".csv", ".log", ".json"}:
            return "I can read text files in your Documents, Downloads or Desktop, sir."
        text = p.read_text(encoding="utf-8", errors="replace")
    else:
        return "I can read the clipboard, a page, a text file, or text you give me, sir."
    text = " ".join(text.split())[:MAX_READ_CHARS]
    if not text or text.endswith("is empty, sir."):
        return "There's nothing there to read, sir."
    old = _reading.get("task")
    if old and not old.done():
        old.cancel()
    _reading["task"] = asyncio.create_task(_read(text))
    return f"Reading it aloud now, sir — about {len(text) // 15 // 60 + 1} minutes. Say stop and I will."


toolkit.register(toolkit.Tool(
    name="second_opinion",
    description=("Ask a different, stronger model for an independent view on a decision "
                 "the user is weighing. Pass the question with the needed context in "
                 "`question`. It takes about a minute and the answer is spoken to the "
                 "user directly when ready — tell them it's coming and do not guess it."),
    schema={"type": "object", "properties": {"question": {"type": "string"}},
            "required": ["question"]},
    handler=ask_handler, acting=True, exempt="its answer is spoken to the user, never read by you"))
toolkit.register(toolkit.Tool(
    name="read_aloud",
    description=("Read something aloud to the user, like a podcast, without you summarising "
                 "it: `source` clipboard, url (with `url`), file (`path`, text files) or "
                 "text (`text`). `action` stop interrupts. The reading is spoken directly; "
                 "for 'read me a summary' use the other tools and speak it yourself."),
    schema={"type": "object", "properties": {
        "action": {"type": "string", "enum": ["read", "stop"]},
        "source": {"type": "string", "enum": ["clipboard", "url", "file", "text"]},
        "url": {"type": "string"}, "path": {"type": "string"}, "text": {"type": "string"}}},
    handler=read_handler, acting=True,
    exempt="the text goes to the speakers and is not returned to you"))
