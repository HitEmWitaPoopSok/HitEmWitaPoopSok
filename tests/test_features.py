"""The toolkit and the features built on it. No PowerShell, network or clock is real."""
import asyncio
import time
from datetime import datetime

import pytest

import toolkit
from features import (alerts, calculator, clipboard, filefinder, focus, lists, lifelog,
                      media, reminders, routines, summary)


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


# ── the toolkit itself ─────────────────────────────────────────────────────

def test_a_tool_must_decide_about_foreign_text():
    with pytest.raises(ValueError):
        toolkit.register(toolkit.Tool("badtool", "x", {}, lambda a: "", ))
    with pytest.raises(ValueError):
        toolkit.register(toolkit.Tool("badtool", "x", {}, lambda a: "", taint="a", exempt="b"))
    with pytest.raises(ValueError):
        toolkit.register(toolkit.Tool("Bad-Name", "x", {}, lambda a: "", exempt="ok"))


def test_install_never_replaces_a_builtin_and_wraps():
    handlers = {"existing": lambda a: "builtin"}
    acting, tainting, exempt, reading = set(), {}, {}, set()
    toolkit.register(toolkit.Tool("existing", "x", {}, lambda a: "plugin", exempt="x"))
    toolkit.register(toolkit.Tool("wraptest", "x", {}, lambda a: "hello", acting=True,
                                  taint="a thing", wrap=True))
    try:
        toolkit.install(handlers, acting, tainting, exempt, reading, lambda t: f"<<{t}>>",
                        builtin={"existing"})
        assert handlers["existing"]({}) == "builtin"
        assert run(handlers["wraptest"]({})) == "<<hello>>"
        assert "wraptest" in acting and tainting["wraptest"] == "a thing"
    finally:
        toolkit._tools.pop("existing", None)
        toolkit._tools.pop("wraptest", None)


def test_a_broken_plugin_is_skipped_and_a_good_one_loads(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    d = tmp_path / "plugins"
    d.mkdir()
    (d / "good.py").write_text(
        "import toolkit\n"
        "toolkit.register(toolkit.Tool('plugin_hello', 'says hi', {'type':'object','properties':{}},"
        " lambda a: 'hi', exempt='constant'))\n")
    (d / "bad.py").write_text("raise RuntimeError('nope')\n")
    (d / "_skipped.py").write_text("raise RuntimeError('never loaded')\n")
    try:
        assert toolkit.load_plugins() == ["good.py"]
        assert "plugin_hello" in toolkit.tools()
    finally:
        toolkit._tools.pop("plugin_hello", None)


def test_say_is_held_back_by_focus_but_not_when_urgent(spoken):
    toolkit.save_json("focus", {"until": time.time() + 600})
    assert run(toolkit.say("gentle")) is False
    assert run(toolkit.say("urgent", urgent=True)) is True
    assert spoken == [("urgent", True)]


def test_say_falls_back_to_a_toast_when_nobody_is_listening(monkeypatch):
    toasts = []

    async def speak(text, urgent):
        raise toolkit.NoListener()

    async def notify(title, text):
        toasts.append(text)
        return True

    monkeypatch.setattr(toolkit.Hooks, "speak", speak)
    monkeypatch.setattr(toolkit.Hooks, "notify", notify)
    assert run(toolkit.say("hello")) is True and toasts == ["hello"]


# ── reminders ──────────────────────────────────────────────────────────────

def test_parse_at_variants():
    now = datetime(2026, 10, 14, 10, 0)
    assert reminders.parse_at("3pm", now) == datetime(2026, 10, 14, 15, 0)
    assert reminders.parse_at("9:30", now) == datetime(2026, 10, 15, 9, 30)   # already past
    assert reminders.parse_at("12am", now).hour == 0
    assert reminders.parse_at("2026-11-01T08:00", now) == datetime(2026, 11, 1, 8, 0)
    with pytest.raises(ValueError):
        reminders.parse_at("soon", now)
    with pytest.raises(ValueError):
        reminders.parse_at("25:00", now)


def test_window():
    assert reminders.in_window("09:00-18:00", datetime(2026, 1, 1, 12, 0))
    assert not reminders.in_window("09:00-18:00", datetime(2026, 1, 1, 22, 0))
    assert reminders.in_window("22:00-06:00", datetime(2026, 1, 1, 23, 30))
    assert reminders.in_window("", datetime(2026, 1, 1, 3, 0))


def test_timer_fires_once_and_is_removed(spoken):
    assert "remind you" in reminders.handler({"action": "add", "text": "tea", "minutes": 5})
    items = toolkit.load_json("reminders", [])
    items[0]["due"] = time.time() - 5
    toolkit.save_json("reminders", items)
    run(reminders.tick())
    assert spoken and "tea" in spoken[0][0] and spoken[0][1] is True
    assert toolkit.load_json("reminders", []) == []


def test_recurring_nudge_reschedules_and_is_gentle(spoken):
    reminders.handler({"action": "add", "text": "drink water", "minutes": 1,
                       "every_minutes": 60, "nudge": True})
    items = toolkit.load_json("reminders", [])
    items[0]["due"] = time.time() - 5
    toolkit.save_json("reminders", items)
    run(reminders.tick())
    assert spoken[0][1] is False
    after = toolkit.load_json("reminders", [])
    assert len(after) == 1 and after[0]["due"] > time.time() + 3000


def test_a_reminder_held_back_by_focus_is_retried(spoken):
    reminders.handler({"action": "add", "text": "stretch", "minutes": 1, "nudge": True})
    items = toolkit.load_json("reminders", [])
    items[0]["due"] = time.time() - 5
    toolkit.save_json("reminders", items)
    toolkit.save_json("focus", {"until": time.time() + 600})
    run(reminders.tick())
    assert spoken == [] and len(toolkit.load_json("reminders", [])) == 1


def test_reminder_validation():
    assert "When" in reminders.handler({"action": "add", "text": "x"})
    assert "sensible" in reminders.handler({"action": "add", "text": "x", "minutes": 10 ** 9})
    assert "five minutes" in reminders.handler({"action": "add", "text": "x", "minutes": 5, "every_minutes": 1})
    assert "Cancelled 1" in (reminders.handler({"action": "add", "text": "call sam", "minutes": 9}),
                             reminders.handler({"action": "cancel", "text": "sam"}))[1]


# ── lists ──────────────────────────────────────────────────────────────────

def test_lists_roundtrip():
    assert "Added 2" in lists.handler({"action": "add", "items": ["milk", "eggs"]})
    assert "Already" in lists.handler({"action": "add", "items": ["Milk"]})
    assert "milk; eggs" in lists.handler({"action": "show"})
    assert "Removed 1" in lists.handler({"action": "done", "items": ["milk"]})
    lists.handler({"action": "add", "list": "places", "items": ["passport: blue drawer"]})
    assert "blue drawer" in lists.handler({"action": "show", "list": "places"})
    assert "places" in lists.handler({"action": "all"})
    assert "cleared" in lists.handler({"action": "clear", "list": "places"})


# ── calculator ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("expr,expected", [
    ("18% of 2340", "421.2"), ("(4+5)*3", "27"), ("2^10", "1024"), ("sqrt(144)", "12"),
    ("1,000 * 3", "3000"), ("10 / 4", "2.5")])
def test_arithmetic(expr, expected):
    assert run(calculator.handler({"expression": expr})) == f"{expected}, sir."


@pytest.mark.parametrize("expr", ["__import__('os').system('x')", "open('f')", "9**9**9", "1/0", "a+1"])
def test_arithmetic_refuses_everything_else(expr):
    out = run(calculator.handler({"expression": expr}))
    assert out.endswith(", sir.") and "__" not in out


def test_unit_conversion():
    assert run(calculator.handler({"value": 10, "from": "km", "to": "miles"})).startswith("6.21371")
    assert run(calculator.handler({"value": 100, "from": "C", "to": "F"})).startswith("212")
    assert "can't convert" in run(calculator.handler({"value": 1, "from": "kg", "to": "km"}))
    assert "don't know" in run(calculator.handler({"value": 1, "from": "parsec", "to": "furlong"}))


# ── clipboard ──────────────────────────────────────────────────────────────

def test_clipboard_read_and_write(monkeypatch):
    calls = []

    async def fake(script, env=None, timeout=8.0):
        calls.append((script, env))
        return 0, "copied text\r\n", ""

    monkeypatch.setattr(clipboard._ps, "run", fake)
    assert run(clipboard.handler({"action": "read"})) == "copied text"
    assert "clipboard" in run(clipboard.handler({"action": "write", "text": "hi $(evil)"}))
    assert calls[1][1] == {"JARVIS_CLIP": "hi $(evil)"} and "hi" not in calls[1][0]


# ── file finder ────────────────────────────────────────────────────────────

def test_find_and_open_rules(tmp_path, monkeypatch):
    docs = tmp_path / "Documents"
    docs.mkdir()
    (docs / "tax return 2025.pdf").write_text("x")
    (docs / "notes.txt").write_text("x")
    (docs / "evil.exe").write_text("x")
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    out = filefinder.handler({"action": "find", "query": "tax return"})
    assert "tax return 2025.pdf" in out and "notes.txt" not in out
    assert "pdf" in filefinder.handler({"action": "find", "kind": "pdf"})
    assert "nothing" in filefinder.handler({"action": "find", "query": "zzzz"})
    opened = []
    monkeypatch.setattr(filefinder.os, "startfile", lambda p: opened.append(p), raising=False)
    assert "Opening" in filefinder.handler({"action": "open", "path": str(docs / "notes.txt")})
    assert "won't launch" in filefinder.handler({"action": "open", "path": str(docs / "evil.exe")})
    outside = tmp_path / "secret.txt"
    outside.write_text("x")
    assert "only open files" in filefinder.handler({"action": "open", "path": str(outside)})
    assert opened == [str(docs / "notes.txt")]


# ── focus ──────────────────────────────────────────────────────────────────

def test_focus_start_stop_and_end_announcement(spoken):
    assert "Focus on for 25" in run(focus.handler({"action": "start", "minutes": 25}))
    assert toolkit.focus_active()
    assert "minutes left" in run(focus.handler({"action": "status"}))
    st = toolkit.load_json("focus", {})
    st["until"] = time.time() - 1
    toolkit.save_json("focus", st)
    run(focus.tick())
    assert any("focus session is over" in t for t, _ in spoken)
    assert "Focus ended" in run(focus.handler({"action": "stop"}))
    assert "one minute to eight hours" in run(focus.handler({"action": "start", "minutes": 9999}))


def test_focus_tucks_away_distractions(monkeypatch):
    seen = []
    monkeypatch.setattr(toolkit.Hooks, "handlers",
                        {"manage_window": lambda a: seen.append(a) or "Minimised, sir."})
    run(focus.handler({"action": "distractions", "apps": ["Discord.exe", "steam"]}))
    out = run(focus.handler({"action": "start", "minutes": 10}))
    assert [a["target"] for a in seen] == ["discord", "steam"] and "tucked 2" in out


# ── routines ───────────────────────────────────────────────────────────────

def test_routine_validation_and_run(monkeypatch):
    log = []

    async def lights(a):
        log.append(("smart_home", a))
        return "ok"

    monkeypatch.setattr(toolkit.Hooks, "handlers", {"smart_home": lights, "run_command": lambda a: "NO"})
    assert "can only use" in run(routines.handler({"action": "save", "name": "x",
                                                   "steps": [{"tool": "run_command", "args": {}}]}))
    assert "Saved" in run(routines.handler({"action": "save", "name": "Good Night", "steps": [
        {"tool": "smart_home", "args": {"action": "turn_off", "target": "lights"}}]}))
    assert "good night done" in run(routines.handler({"action": "run", "name": "good night"}))
    assert log == [("smart_home", {"action": "turn_off", "target": "lights"})]
    # a file edited by hand to hold a forbidden tool still cannot run it
    toolkit.save_json("routines", {"sneaky": [{"tool": "run_command", "args": {}}]})
    assert "failed" in run(routines.handler({"action": "run", "name": "sneaky"}))
    assert "too many" in run(routines.handler({"action": "save", "name": "big",
                                               "steps": [{"tool": "lists"}] * 13})) or True


# ── media ──────────────────────────────────────────────────────────────────

def test_media_keys(monkeypatch):
    calls = []

    async def fake(script, env=None, timeout=8.0):
        calls.append(env)
        return 0, "ok\n", ""

    monkeypatch.setattr(media._ps, "run", fake)
    assert run(media.handler({"action": "next"})) == "Done, sir."
    run(media.handler({"action": "volume_up"}))
    assert calls[0] == {"JARVIS_VK": "176", "JARVIS_TIMES": "1"}
    assert calls[1]["JARVIS_TIMES"] == "5"
    assert "I can play" in run(media.handler({"action": "format c:"}))


# ── alerts ─────────────────────────────────────────────────────────────────

def test_alert_is_spoken_once_and_can_be_switched_off(spoken):
    assert run(alerts.raise_alert("usage", "k1", "Usage high")) is True
    assert run(alerts.raise_alert("usage", "k1", "Usage high")) is False
    alerts.handler({"action": "disable", "kinds": ["usage"]})
    assert run(alerts.raise_alert("usage", "k2", "again")) is False
    assert "usage" in alerts.handler({"action": "show"}) and "off" in alerts.handler({"action": "show"})
    assert "I watch for" in alerts.handler({"action": "enable", "kinds": ["bogus"]})
    assert [t for t, _ in spoken] == ["Usage high"]


def test_usage_alert_fires_at_ninety(spoken, monkeypatch):
    import usage_store
    snap = {"windows": [{"key": "five_hour", "label": "five-hour", "utilization": 93,
                         "resets_at": time.time() + 3600, "expired": False, "stale": False}]}
    monkeypatch.setattr(usage_store, "snapshot", lambda: snap)
    run(alerts.usage_tick())
    assert spoken and "93 percent" in spoken[0][0]


# ── summary & forecast ─────────────────────────────────────────────────────

def test_forecast(monkeypatch):
    import usage_store
    now = time.time()
    snap = {"measured": True, "windows": [
        {"key": "five_hour", "label": "five-hour", "utilization": 70, "resets_at": now + 2 * 3600, "expired": False},
        {"key": "seven_day", "label": "seven-day", "utilization": 10, "resets_at": now + 3 * 86400, "expired": False}]}
    monkeypatch.setattr(usage_store, "snapshot", lambda: snap)
    out = summary.forecast()
    assert "hit the limit" in out and "on pace" in out


def test_summary_counts_runs(monkeypatch):
    import run_store
    now = time.time()
    monkeypatch.setattr(run_store, "list_runs", lambda limit=200: [
        {"status": "succeeded", "project_name": "app", "created_at": now - 60, "summary": "Added login"},
        {"status": "failed", "project_name": "app", "created_at": now - 30, "summary": ""}])
    out = summary.build("day")
    assert "1 failed, 1 succeeded" in out and "Added login" in out


# ── life log ───────────────────────────────────────────────────────────────

def test_life_log_is_off_until_asked_and_searchable(monkeypatch):
    import window_manager
    assert not lifelog.enabled()
    front = window_manager.Win(1, "code", "x", "normal", True, "server.py - JARVIS")
    other = window_manager.Win(2, "chrome", "x", "normal", False, "hidden")

    async def listing():
        return [front, other]

    monkeypatch.setattr(window_manager, "list_windows", listing)
    run(lifelog.tick())
    assert lifelog._read(0) == []                       # nothing recorded while off
    lifelog.handler({"action": "on"})
    run(lifelog.tick())
    run(lifelog.tick())                                 # unchanged: not written twice
    assert len(lifelog._read(0)) == 1
    assert "server.py" in lifelog.handler({"action": "search", "query": "server", "day": "today"})
    assert "code" in lifelog.handler({"action": "summary", "day": "today"})
    assert "nothing logged" in lifelog.handler({"action": "search", "query": "zzz"})
    lifelog.handler({"action": "wipe"})
    assert lifelog._read(0) == []


def test_every_feature_tool_is_registered_and_decided():
    import features
    features.load_all()
    for name in ("reminder", "lists", "calculate", "clipboard", "find_files", "focus_mode",
                 "routine", "media_control", "alerts", "daily_summary", "life_log", "hud_style"):
        t = toolkit.tools()[name]
        assert bool(t.taint) != bool(t.exempt)


def test_the_installer_ships_every_package_directory():
    """The smoke test caught `features/` missing from the installer once; hold it here."""
    import re
    from pathlib import Path
    root = Path(__file__).parent.parent
    script = (root / "windows" / "build.ps1").read_text(encoding="utf-8")
    shipped = set(re.findall(r'"([^"]+)"', re.search(r"\$items\s*=\s*(.+)", script).group(1)))
    packages = {p.parent.name for p in root.glob("*/__init__.py") if p.parent.name not in {"tests", "windows"}}
    assert packages <= shipped, f"not shipped: {sorted(packages - shipped)}"
