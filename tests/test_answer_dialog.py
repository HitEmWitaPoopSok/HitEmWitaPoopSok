"""Tests for answer_dialog.

On Windows nothing can press a key in another terminal (see dialog.py), so
`dialog.answer` always reports `no_tty` or `bad_key`. What these tests pin is
the closed vocabulary, that nothing is ever pressed, and the tool's staged
read-back pattern (with the keypress itself faked).
"""

import asyncio

import pytest

import dialog


# --- the closed vocabulary --------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("return", "return"), ("Return", "return"), ("  enter ", "return"),
    ("yes", "return"), ("y", "return"), ("enter\n", "return"),
    ("escape", "escape"), ("ESC", "escape"), ("cancel", "escape"),
    ("no", "escape"), ("n", "escape"),
    ("1", "1"), ("9", "9"), ("5", "5"),
])
def test_the_accepted_vocabulary_normalizes(raw, expected):
    assert dialog.normalize_key(raw) == expected


@pytest.mark.parametrize("raw", [
    "rm -rf /",                       # free text
    "",                               # empty
    "   ",                            # whitespace only
    "yes please",                     # multi-character, starts with an alias
    "returnn",
    "0",                              # a digit outside 1-9
    "10",                             # two digits
    "-1",
    '"; do shell script "',           # injection-shaped
    "return; keystroke \"rm\"",
    "\n",
    "key code 36",
    None,
    36,
    ["return"],
])
def test_everything_outside_the_vocabulary_is_refused(raw):
    assert dialog.normalize_key(raw) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [
    "rm -rf /", "", "   ", "yes please", "0", "10", '"; do shell script "',
    "return; keystroke \"rm\"", None, 36,
])
async def test_a_refused_key_is_bad_key(raw):
    assert await dialog.answer(4242, raw) == dialog.BAD_KEY


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["return", "escape", "1", "9"])
async def test_nothing_is_ever_pressed_on_windows(key):
    assert await dialog.answer(4242, key) == dialog.NO_TTY


def test_there_are_no_ttys_to_look_up():
    assert dialog.tty_for_pid(1234) is None
    assert dialog.tty_for_pid(0) is None
    assert dialog.tty_for_pid("nonsense") is None


# --- the tool, and the staged pattern ---------------------------------------

@pytest.fixture
def wired(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path / "data"))
    import importlib
    import server as server_module
    importlib.reload(server_module)
    server_module.run_store.init_db()
    return server_module


class FakeUtterance:
    def __init__(self, cancelled=False):
        self.was_cancelled = cancelled


class FakeSpeech:
    """Models say -> wait_for -> open_cancel_window, and logs the order of
    everything so a test can prove nothing was pressed too early."""
    def __init__(self, log=None, cancelled=False, readback_cancelled=False,
                 readback_heard=True):
        self.said = []
        self.log = log if log is not None else []
        self.cancelled = cancelled
        self.readback_cancelled = readback_cancelled
        self.readback_heard = readback_heard

    async def say(self, text, *a, **k):
        self.said.append(text)
        self.log.append(("said", text))
        return FakeUtterance(cancelled=self.readback_cancelled)

    async def wait_for(self, utt, timeout=60.0):
        self.log.append(("waited", None))
        if not self.readback_heard:
            return False
        return not utt.was_cancelled

    async def open_cancel_window(self, *a, **k):
        self.log.append(("window", None))
        return self.cancelled


class FakeBrain:
    current_origin = "user"


def _state(pids=(4242,), voice_name="hammer", project="hammer"):
    import session_watch as sw
    return sw.SessionState(session_id="sid", cwd="/p/hammer", project=project,
                           state="needs_you", voice_name=voice_name,
                           pids=list(pids), primary_pid=pids[0])


@pytest.fixture
def tool(wired, monkeypatch):
    """server + a recorded fake keypress, with a session that resolves and
    has exactly one tty."""
    server = wired
    log = []
    speech = FakeSpeech(log=log)
    pressed = []

    async def fake_answer(pid, key):
        log.append(("pressed", (pid, key)))
        pressed.append((pid, key))
        return dialog.SENT

    monkeypatch.setattr(server, "speech", speech)
    monkeypatch.setattr(server, "brain_instance", FakeBrain())
    monkeypatch.setattr(server, "_resolve_or_explain",
                        lambda n: (_state(), None, None))
    monkeypatch.setattr(dialog, "tty_for_pid", lambda pid: "/dev/ttys006")
    monkeypatch.setattr(dialog, "answer", fake_answer)
    return server, speech, pressed, log


@pytest.mark.asyncio
async def test_the_tool_stages_and_presses_nothing_at_all(tool):
    """The tool runs mid-turn with the turn utterance still open. Anything it
    said would be queued behind the very turn waiting for it to return."""
    server, speech, pressed, _ = tool

    result = await server.tool_answer_dialog({"name": "hammer", "key": "yes"})

    assert speech.said == [], "the read-back may not happen inside the tool call"
    assert pressed == [], "nothing may be pressed from inside the tool call"
    assert "staged" in result.lower()
    assert len(server._staged_dialogs) == 1
    assert server._staged_dialogs[0].key == "return"
    import run_store
    assert run_store.list_steers(limit=50) == [], "staging is not an outcome"


@pytest.mark.asyncio
async def test_nothing_is_pressed_before_the_readback_has_been_heard(tool):
    server, speech, pressed, log = tool

    await server.tool_answer_dialog({"name": "hammer", "key": "yes"})
    await server._perform_staged_dialogs()

    kinds = [k for k, _ in log]
    assert kinds.index("pressed") > kinds.index("said")
    assert kinds.index("pressed") > kinds.index("waited")
    assert kinds.index("pressed") > kinds.index("window")
    assert pressed == [(4242, "return")]
    assert server._staged_dialogs == []


@pytest.mark.asyncio
async def test_the_readback_names_the_key_and_warns_about_the_focus(tool):
    server, speech, _, _ = tool

    await server.tool_answer_dialog({"name": "hammer", "key": "yes"})
    await server._perform_staged_dialogs()

    assert "Return" in speech.said[0] and "hammer" in speech.said[0]
    assert "forward" in speech.said[0].lower(), \
        "the user must be warned that this steals focus"


@pytest.mark.asyncio
async def test_a_cancel_word_in_the_window_blocks_the_keypress(wired, monkeypatch):
    server = wired
    speech = FakeSpeech(cancelled=True)
    pressed = []

    async def fake_answer(pid, key):
        pressed.append((pid, key))
        return dialog.SENT

    monkeypatch.setattr(server, "speech", speech)
    monkeypatch.setattr(server, "brain_instance", FakeBrain())
    monkeypatch.setattr(server, "_resolve_or_explain", lambda n: (_state(), None, None))
    monkeypatch.setattr(dialog, "tty_for_pid", lambda pid: "/dev/ttys006")
    monkeypatch.setattr(dialog, "answer", fake_answer)

    await server.tool_answer_dialog({"name": "hammer", "key": "yes"})
    await server._perform_staged_dialogs()

    assert pressed == [], "nothing may be pressed after a cancel"
    import run_store
    assert run_store.list_steers(limit=5)[0]["outcome"] == "dialog:cancelled_by_user"


@pytest.mark.asyncio
async def test_a_bargein_during_the_readback_blocks_it_and_records_a_cancel(
        wired, monkeypatch):
    """`wait_for` returns False for a cancel and a timeout alike, so
    `was_cancelled` must be checked explicitly and separately."""
    server = wired
    speech = FakeSpeech(readback_cancelled=True)
    pressed = []

    async def fake_answer(pid, key):
        pressed.append((pid, key))
        return dialog.SENT

    monkeypatch.setattr(server, "speech", speech)
    monkeypatch.setattr(server, "brain_instance", FakeBrain())
    monkeypatch.setattr(server, "_resolve_or_explain", lambda n: (_state(), None, None))
    monkeypatch.setattr(dialog, "tty_for_pid", lambda pid: "/dev/ttys006")
    monkeypatch.setattr(dialog, "answer", fake_answer)

    await server.tool_answer_dialog({"name": "hammer", "key": "escape"})
    await server._perform_staged_dialogs()

    assert pressed == []
    import run_store
    assert run_store.list_steers(limit=5)[0]["outcome"] == "dialog:cancelled_by_user"


@pytest.mark.asyncio
async def test_a_readback_that_was_never_heard_presses_nothing(wired, monkeypatch):
    server = wired
    speech = FakeSpeech(readback_heard=False)
    pressed = []

    async def fake_answer(pid, key):
        pressed.append((pid, key))
        return dialog.SENT

    monkeypatch.setattr(server, "speech", speech)
    monkeypatch.setattr(server, "brain_instance", FakeBrain())
    monkeypatch.setattr(server, "_resolve_or_explain", lambda n: (_state(), None, None))
    monkeypatch.setattr(dialog, "tty_for_pid", lambda pid: "/dev/ttys006")
    monkeypatch.setattr(dialog, "answer", fake_answer)

    await server.tool_answer_dialog({"name": "hammer", "key": "yes"})
    await server._perform_staged_dialogs()

    assert pressed == [], "never press something the user cannot be shown to have heard"
    import run_store
    assert run_store.list_steers(limit=5)[0]["outcome"] == "dialog:readback_failed"


@pytest.mark.asyncio
async def test_no_voice_refuses_rather_than_pressing_unannounced(wired, monkeypatch):
    server = wired
    pressed = []

    async def fake_answer(pid, key):
        pressed.append((pid, key))
        return dialog.SENT

    monkeypatch.setattr(server, "speech", None)
    monkeypatch.setattr(server, "brain_instance", FakeBrain())
    monkeypatch.setattr(server, "_resolve_or_explain", lambda n: (_state(), None, None))
    monkeypatch.setattr(dialog, "tty_for_pid", lambda pid: "/dev/ttys006")
    monkeypatch.setattr(dialog, "answer", fake_answer)

    result = await server.tool_answer_dialog({"name": "hammer", "key": "yes"})

    assert pressed == []
    assert server._staged_dialogs == []
    assert "won't press" in result.lower()
    import run_store
    assert run_store.list_steers(limit=5)[0]["outcome"] == "dialog:no_voice"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [
    "rm -rf /", "", "yes please", "0", "10", '"; do shell script "', "returnn",
])
async def test_the_tool_refuses_a_key_outside_the_vocabulary(bad, wired,
                                                             monkeypatch):
    server = wired
    speech = FakeSpeech()
    monkeypatch.setattr(server, "speech", speech)
    monkeypatch.setattr(server, "brain_instance", FakeBrain())
    monkeypatch.setattr(server, "_resolve_or_explain", lambda n: (_state(), None, None))
    monkeypatch.setattr(dialog, "answer",
                        lambda *a: pytest.fail("a refused key must not be pressed"))

    result = await server.tool_answer_dialog({"name": "hammer", "key": bad})

    assert server._staged_dialogs == [], "a refused key may not be staged"
    assert "return" in result.lower() and "escape" in result.lower()
    import run_store
    assert run_store.list_steers(limit=5)[0]["outcome"] == "dialog:bad_key"


@pytest.mark.asyncio
async def test_an_ambiguous_name_asks_rather_than_guessing(wired, monkeypatch):
    server = wired
    monkeypatch.setattr(server, "speech", FakeSpeech())
    monkeypatch.setattr(server, "brain_instance", FakeBrain())
    monkeypatch.setattr(server, "_resolve_or_explain",
                        lambda n: (None, "There are 2: a and b. Which one?", "ambiguous"))
    monkeypatch.setattr(dialog, "answer",
                        lambda *a: pytest.fail("an ambiguous target is never pressed"))

    result = await server.tool_answer_dialog({"name": "hammer", "key": "yes"})

    assert "which one" in result.lower()
    assert server._staged_dialogs == []
    import run_store
    assert run_store.list_steers(limit=5)[0]["outcome"] == "dialog:ambiguous"


@pytest.mark.asyncio
async def test_a_session_with_no_tty_is_refused_synchronously(wired, monkeypatch):
    """The `sdk-cli` entrypoint on this machine reports `??` for its tty."""
    server = wired
    monkeypatch.setattr(server, "speech", FakeSpeech())
    monkeypatch.setattr(server, "brain_instance", FakeBrain())
    monkeypatch.setattr(server, "_resolve_or_explain", lambda n: (_state(), None, None))
    monkeypatch.setattr(dialog, "tty_for_pid", lambda pid: None)
    monkeypatch.setattr(dialog, "answer",
                        lambda *a: pytest.fail("nothing to press"))

    result = await server.tool_answer_dialog({"name": "hammer", "key": "yes"})

    assert "terminal" in result.lower()
    assert server._staged_dialogs == []
    import run_store
    assert run_store.list_steers(limit=5)[0]["outcome"] == "dialog:no_tty"


@pytest.mark.asyncio
async def test_a_session_spanning_two_terminals_asks_rather_than_picking(
        wired, monkeypatch):
    server = wired
    monkeypatch.setattr(server, "speech", FakeSpeech())
    monkeypatch.setattr(server, "brain_instance", FakeBrain())
    monkeypatch.setattr(server, "_resolve_or_explain",
                        lambda n: (_state(pids=(1, 2)), None, None))
    monkeypatch.setattr(dialog, "tty_for_pid",
                        lambda pid: f"/dev/ttys00{pid}")
    monkeypatch.setattr(dialog, "answer",
                        lambda *a: pytest.fail("an ambiguous window is never typed into"))

    result = await server.tool_answer_dialog({"name": "hammer", "key": "yes"})

    assert "won't guess" in result.lower()
    assert server._staged_dialogs == []


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome,expected", [
    (dialog.SENT, "dialog:sent"),
    (dialog.NO_TTY, "dialog:no_tty"),
    (dialog.NOT_FOUND, "dialog:not_found"),
    (dialog.NOT_PERMITTED, "dialog:not_permitted"),
    (dialog.FAILED, "dialog:failed"),
])
async def test_every_terminal_path_writes_exactly_one_audit_row(
        outcome, expected, wired, monkeypatch):
    server = wired
    speech = FakeSpeech()

    async def fake_answer(pid, key):
        return outcome

    monkeypatch.setattr(server, "speech", speech)
    monkeypatch.setattr(server, "brain_instance", FakeBrain())
    monkeypatch.setattr(server, "_resolve_or_explain", lambda n: (_state(), None, None))
    monkeypatch.setattr(dialog, "tty_for_pid", lambda pid: "/dev/ttys006")
    monkeypatch.setattr(dialog, "answer", fake_answer)

    await server.tool_answer_dialog({"name": "hammer", "key": "yes"})
    await server._perform_staged_dialogs()

    import run_store
    rows = run_store.list_steers(limit=50)
    assert len(rows) == 1, "exactly one row per attempt, never zero and never two"
    assert rows[0]["outcome"] == expected
    assert rows[0]["prompt"] == "return", "the key is what was audited"
    assert speech.said[-1] != speech.said[0], "the outcome is spoken too"


@pytest.mark.asyncio
async def test_a_raised_exception_still_leaves_an_audit_row(wired, monkeypatch):
    server = wired

    async def boom(pid, key):
        raise RuntimeError("nope")

    monkeypatch.setattr(server, "speech", FakeSpeech())
    monkeypatch.setattr(server, "brain_instance", FakeBrain())
    monkeypatch.setattr(server, "_resolve_or_explain", lambda n: (_state(), None, None))
    monkeypatch.setattr(dialog, "tty_for_pid", lambda pid: "/dev/ttys006")
    monkeypatch.setattr(dialog, "answer", boom)

    await server.tool_answer_dialog({"name": "hammer", "key": "yes"})
    await server._perform_staged_dialogs()      # must not raise out

    import run_store
    rows = run_store.list_steers(limit=50)
    assert rows and rows[0]["outcome"] == "dialog:failed"
    assert server._staged_dialogs == []


@pytest.mark.asyncio
async def test_an_unreachable_host_is_reported_honestly(wired, monkeypatch):
    """The Orcha.app case: no Terminal tab owns that tty. JARVIS says so
    rather than claiming success or silently doing nothing."""
    server = wired
    speech = FakeSpeech()

    async def fake_answer(pid, key):
        return dialog.NOT_FOUND

    monkeypatch.setattr(server, "speech", speech)
    monkeypatch.setattr(server, "brain_instance", FakeBrain())
    monkeypatch.setattr(server, "_resolve_or_explain", lambda n: (_state(), None, None))
    monkeypatch.setattr(dialog, "tty_for_pid", lambda pid: "/dev/ttys006")
    monkeypatch.setattr(dialog, "answer", fake_answer)

    await server.tool_answer_dialog({"name": "hammer", "key": "yes"})
    await server._perform_staged_dialogs()

    last = speech.said[-1].lower()
    assert "terminal" in last and "hammer" in last
    assert "pressed" not in last, "it must not claim a keystroke it did not send"


# --- the registries ---------------------------------------------------------

def test_answer_dialog_is_gated_as_an_acting_tool(wired):
    server = wired
    assert "answer_dialog" in server.TOOL_HANDLERS
    assert "answer_dialog" in server.ACTING_TOOLS, (
        "a synthetic keystroke must never be reachable from another session's "
        "transcript — only from the user's own turn")
    assert server.ACTING_TOOLS <= set(server.TOOL_HANDLERS)


def test_the_three_registries_agree(wired):
    import brain
    import jarvis_mcp
    server = wired
    assert "mcp__jarvis__answer_dialog" in brain.ALLOWED_TOOLS
    assert {t["name"] for t in jarvis_mcp.TOOL_SPECS} == set(server.TOOL_HANDLERS)
    assert {t for t in brain.ALLOWED_TOOLS if t.startswith("mcp__")} <= {
        f"mcp__jarvis__{n}" for n in server.TOOL_HANDLERS}


def test_the_staged_dialogs_are_drained_after_the_turn(wired):
    """The whole point of the staged shape: `_handle_utterance` performs them
    after `end_turn`, never inside the tool call."""
    import inspect
    server = wired
    src = inspect.getsource(server._handle_utterance)
    assert "_perform_staged_dialogs()" in src
    assert "_staged_dialogs" in src
