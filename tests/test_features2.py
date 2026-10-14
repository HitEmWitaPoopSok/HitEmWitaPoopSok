"""Wave 2 features: modes, GitHub watch, code review, goals, thinking, drafts, style, endpoints."""
import asyncio
import subprocess
import time

import httpx
import pytest

import toolkit
from features import codereview, drafts, githubwatch, goals, modes, personality, thinking


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def spoken(monkeypatch):
    said = []

    async def speak(text, urgent, wait=False):
        said.append((text, urgent))

    monkeypatch.setattr(toolkit.Hooks, "speak", speak)
    monkeypatch.setattr(toolkit.Hooks, "notify", None)
    return said


@pytest.fixture(autouse=True)
def reset_modes():
    modes._state.update(mode="", file="", last_heard=0.0)


# ── modes ──────────────────────────────────────────────────────────────────

def test_wake_word_gates_and_opens_a_conversation_window(monkeypatch):
    assert run(modes.intercept("what time is it")) == "what time is it"       # off by default
    modes.handler({"action": "wake_on"})
    assert run(modes.intercept("some chatter in the room")) is None
    assert run(modes.intercept("Hey Jarvis, what's the weather")) == "what's the weather"
    assert run(modes.intercept("and tomorrow")) == "and tomorrow"             # inside the window
    modes._state["last_heard"] = time.time() - 60
    assert run(modes.intercept("and the day after")) is None
    assert run(modes.intercept("jarvis")) == "Yes?"
    modes.handler({"action": "wake_off"})
    assert run(modes.intercept("anything")) == "anything"


def test_notes_are_written_not_answered(spoken):
    assert "Taking notes" in modes.handler({"action": "start_notes"})
    assert run(modes.intercept("we agreed to ship on friday")) is None
    assert run(modes.intercept("Sam owns the invoice")) is None
    assert run(modes.intercept("ok jarvis stop notes")) is None
    assert modes._state["mode"] == "" and "saved" in spoken[0][0]
    text = modes.handler({"action": "show_notes"})
    assert "ship on friday" in text and "Sam owns the invoice" in text
    assert run(modes.intercept("hello")) == "hello"                            # back to normal


def test_dictation_pastes_via_environment_only(monkeypatch, spoken):
    calls = []

    async def fake(script, env=None, timeout=8.0):
        calls.append((script, env))
        return 0, "ok\n", ""

    monkeypatch.setattr(modes._ps, "run", fake)
    modes.handler({"action": "start_dictation"})
    assert run(modes.intercept("hello $(calc) world")) is None
    assert calls[0][1] == {"JARVIS_TEXT": "hello $(calc) world "} and "calc" not in calls[0][0]
    assert run(modes.intercept("stop dictating")) is None
    assert modes._state["mode"] == "" and run(modes.intercept("hi")) == "hi"


def test_dictation_stops_itself_on_failure(monkeypatch, spoken):
    async def fake(script, env=None, timeout=8.0):
        return 1, "", "boom"

    monkeypatch.setattr(modes._ps, "run", fake)
    modes.handler({"action": "start_dictation"})
    run(modes.intercept("typing something"))
    assert modes._state["mode"] == "" and "couldn't type" in spoken[0][0]


def test_interceptors_chain_and_survive_a_crash():
    async def boom(t):
        raise RuntimeError("x")

    async def upper(t):
        return t.upper()

    toolkit.add_interceptor(boom)
    toolkit.add_interceptor(upper)
    try:
        assert run(toolkit.intercept("hi")) == "HI"
    finally:
        toolkit._interceptors.remove(boom)
        toolkit._interceptors.remove(upper)


# ── GitHub watch ───────────────────────────────────────────────────────────

def _gh_transport(runs, prs):
    def handler(request):
        if request.url.path.endswith("/actions/runs"):
            return httpx.Response(200, json={"workflow_runs": runs})
        if request.url.path.endswith("/pulls"):
            return httpx.Response(200, json=prs)
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_watch_validates_names():
    assert "owner/name" in run(githubwatch.handler({"action": "add", "repo": "not a repo; rm -rf"}))
    assert "Watching a/b" in run(githubwatch.handler({"action": "add", "repo": "a/b"}))
    assert "a/b" in run(githubwatch.handler({"action": "list"}))
    assert "Stopped" in run(githubwatch.handler({"action": "remove", "repo": "a/b"}))


def test_first_tick_is_a_silent_baseline_then_changes_are_spoken(monkeypatch, spoken):
    state = {"runs": [{"id": 1, "status": "completed", "conclusion": "success", "name": "ci", "head_branch": "main"}],
             "prs": [{"number": 7, "title": "x", "state": "open"}]}
    real = httpx.AsyncClient

    def client(*a, **kw):
        kw["transport"] = _gh_transport(state["runs"], state["prs"])
        return real(*a, **kw)

    monkeypatch.setattr(githubwatch.httpx, "AsyncClient", client)
    run(githubwatch.handler({"action": "add", "repo": "o/proj"}))
    run(githubwatch.tick())
    assert spoken == []                                             # baseline
    state["runs"].insert(0, {"id": 2, "status": "completed", "conclusion": "failure", "name": "ci", "head_branch": "main"})
    state["prs"][0] = {"number": 7, "title": "x", "state": "closed", "merged_at": "2026-01-01"}
    run(githubwatch.tick())
    texts = [t for t, _ in spoken]
    assert any("FAILED" in t for t in texts) and any("pull request 7" in t and "merged" in t for t in texts)
    spoken.clear()
    run(githubwatch.tick())
    assert spoken == []                                             # nothing new, nothing said


def test_check_wraps_nothing_itself_but_reports(monkeypatch):
    real = httpx.AsyncClient
    monkeypatch.setattr(githubwatch.httpx, "AsyncClient", lambda *a, **kw: real(
        *a, **{**kw, "transport": _gh_transport(
            [{"id": 1, "status": "completed", "conclusion": "success", "name": "ci", "head_branch": "main"}],
            [{"number": 3, "title": "Add login", "state": "open"}])}))
    out = run(githubwatch.handler({"action": "check", "repo": "o/p"}))
    assert "ci on main: success" in out and "#3 Add login (open)" in out


# ── code review ────────────────────────────────────────────────────────────

def test_review_changes_reads_a_real_repo(tmp_path, monkeypatch):
    repo = tmp_path / "myproj"
    repo.mkdir()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"]}
    for cmd in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True, env=env)
    (repo / "a.py").write_text("print(1)\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "first change"], check=True, env=env)
    monkeypatch.setattr(toolkit.Hooks, "project_paths", staticmethod(lambda: [repo]))
    out = codereview.handler({"project": "myproj"})
    assert "first change" in out and "print(1)" in out
    (repo / "a.py").write_text("print(2)\n")
    assert "print(2)" in codereview.handler({"project": "myproj", "what": "uncommitted"})
    assert "Which project" in codereview.handler({"project": "nope"})


# ── goals ──────────────────────────────────────────────────────────────────

def test_goal_lifecycle_and_brief_lines():
    assert "set with 3 tasks" in goals.handler({"action": "add", "goal": "Launch site", "due": "Friday",
                                                 "tasks": ["write copy", "buy domain", "deploy"]})
    assert "3 tasks left" in goals.brief_lines()[0] and "due Friday" in goals.brief_lines()[0]
    assert goals.handler({"action": "done_task", "goal": "launch", "tasks": ["domain"]}) == "Done, sir."
    assert "✓ buy domain" in goals.handler({"action": "show", "goal": "launch"})
    goals.handler({"action": "add_tasks", "goal": "launch", "tasks": ["announce"]})
    out = goals.handler({"action": "done_task", "goal": "launch", "tasks": ["copy", "deploy", "announce"]})
    assert "completes the goal" in out and goals.open_goals() == []
    assert "couldn't match" in goals.handler({"action": "show", "goal": "zzz"})


# ── thinking ───────────────────────────────────────────────────────────────

def test_sentence_trimming():
    assert thinking.sentences("One. Two! Three? Four. Five.", 3) == "One. Two! Three?"


def test_second_opinion_runs_in_the_background_and_speaks(monkeypatch, spoken):
    class FakeProc:
        async def communicate(self):
            return b"Do it. Because X. Risk is Y.", b""

    seen = {}

    async def fake_exec(*argv, **kw):
        seen["argv"], seen["kw"] = argv, kw
        return FakeProc()

    monkeypatch.setattr(thinking.asyncio, "create_subprocess_exec", fake_exec)

    async def go():
        reply = thinking.ask_handler({"question": "Should I rewrite it in Rust?"})
        await asyncio.gather(*list(thinking._tasks))
        return reply

    reply = run(go())
    assert "another model" in reply
    assert "--tools" in seen["argv"] and seen["argv"][seen["argv"].index("--tools") + 1] == ""
    assert "ANTHROPIC_API_KEY" not in seen["kw"]["env"]
    assert spoken and "Do it." in spoken[0][0]
    assert "second opinion on" in thinking.ask_handler({"question": ""})


def test_read_aloud_sources(tmp_path, monkeypatch, spoken):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    docs = tmp_path / "Documents"
    docs.mkdir()
    (docs / "story.txt").write_text("First sentence. Second sentence.")
    (docs / "tool.exe").write_text("x")

    async def go():
        out = await thinking.read_handler({"source": "file", "path": str(docs / "story.txt")})
        await thinking._reading["task"]
        bad = await thinking.read_handler({"source": "file", "path": str(docs / "tool.exe")})
        nothing = await thinking.read_handler({"source": "text", "text": "  "})
        return out, bad, nothing

    out, bad, nothing = run(go())
    assert "Reading it aloud" in out and [t for t, _ in spoken] == ["First sentence.", "Second sentence."]
    assert "text files" in bad and "nothing there" in nothing


# ── drafts & style ─────────────────────────────────────────────────────────

def test_drafts(monkeypatch):
    async def fake(script, env=None, timeout=8.0):
        fake.env = env
        return 0, "", ""

    monkeypatch.setattr(drafts._ps, "run", fake)
    assert "saved" in run(drafts.handler({"action": "save", "name": "Email to Sam!", "text": "Hi Sam"}))
    assert "email-to-sam" in run(drafts.handler({"action": "list"}))
    assert run(drafts.handler({"action": "show", "name": "email to sam"})) == "Hi Sam"
    assert "clipboard" in run(drafts.handler({"action": "copy", "name": "email to sam"}))
    assert fake.env == {"JARVIS_CLIP": "Hi Sam"}
    # a traversal attempt becomes an ordinary file name
    run(drafts.handler({"action": "save", "name": "../../evil", "text": "x"}))
    assert not (drafts._dir().parent.parent / "evil.txt").exists()


def test_speaking_style_persists_into_the_launch_prompt(tmp_path):
    assert personality.style_line() == ""
    assert "terse" in personality.handler({"style": "terse"})
    assert "Be curt" in personality.style_line()
    assert personality.handler({"style": "rude"}).startswith("I have")
    personality.handler({"style": "butler"})
    assert personality.style_line() == ""


# ── endpoints ──────────────────────────────────────────────────────────────

def test_ambient_and_health_endpoints():
    from fastapi.testclient import TestClient
    import server
    server._tool_stats.clear()
    server._note_tool("reminder", False)
    server._note_tool("reminder", True)
    server._note_latency(1.2, 3.4)
    toolkit.save_json("lists", {"shopping": ["milk"]})
    c = TestClient(server.app, base_url="http://localhost:8340")
    h = c.get("/api/health-stats").json()
    assert h["turns"] == 1 and h["tools"][0] == {"name": "reminder", "calls": 2, "failures": 1}
    a = c.get("/api/ambient").json()
    assert a["shopping"] == ["milk"] and set(a["runs"]) == {"active", "failed", "succeeded"}
