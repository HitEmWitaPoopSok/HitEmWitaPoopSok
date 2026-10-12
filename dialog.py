"""Answering a permission prompt in another terminal: not possible on Windows.

JARVIS's `answer_dialog` tool used to press one key in the terminal window a
Claude Code session lives in. That needs a way to name the window a session
is in, and Windows has no equivalent of a tty to name it by; the module's
first rule was that it never types into a window it cannot name. So here
every request is answered `no_tty` and nothing is pressed.

What stays is the part that is not about windows at all: the CLOSED
VOCABULARY. Return, Escape and a single digit 1-9 are the only keys the tool
will ever take; anything else (free text, an empty string, a shell fragment)
is refused before it goes anywhere. `server.py` validates with
`normalize_key`, so the boundary is kept in case a Windows mechanism is added.

Nothing here raises: every path returns an outcome string.
"""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("jarvis.dialog")

# --- outcomes ---------------------------------------------------------------
SENT = "sent"
NO_TTY = "no_tty"           # nothing here can name the window to press in
NOT_FOUND = "not_found"     # the window is hosted by something we cannot reach
NOT_PERMITTED = "not_permitted"   # the system refused the keystroke
FAILED = "failed"           # something went wrong sending it
BAD_KEY = "bad_key"         # defensive: a key outside the closed vocabulary

_ALIASES = {
    "enter": "return",
    "return": "return",
    "yes": "return",       # "yes" answers a permission prompt with Return
    "y": "return",
    "escape": "escape",
    "esc": "escape",
    "cancel": "escape",
    "no": "escape",
    "n": "escape",
}


def normalize_key(key) -> str | None:
    """The closed vocabulary, or None. None means REFUSE — never interpret.

    Returns "return", "escape", or a single digit "1".."9". Anything else,
    including free text that merely starts with an accepted word, is None.
    """
    if not isinstance(key, str):
        return None
    k = key.strip().lower()
    if k in _ALIASES:
        return _ALIASES[k]
    if len(k) == 1 and k in "123456789":
        return k
    return None


def spoken_key(normalized: str) -> str:
    """How the read-back names the key. Must match what actually gets sent."""
    return {"return": "Return", "escape": "Escape"}.get(normalized, normalized)


def tty_for_pid(pid) -> str | None:
    """There are no ttys to look up on Windows."""
    return None


async def tty_for_pid_async(pid) -> str | None:
    """`tty_for_pid`, awaitable (kept so callers need not know)."""
    return await asyncio.to_thread(tty_for_pid, pid)


async def answer(pid: int, key: str) -> str:
    """Press one key in the terminal that owns `pid`. Never raises.

    On Windows nothing can be pressed: a key outside the vocabulary is
    `bad_key`, anything else is `no_tty`.
    """
    if normalize_key(key) is None:
        log.warning(f"refusing a key outside the vocabulary: {key!r}")
        return BAD_KEY
    return NO_TTY
