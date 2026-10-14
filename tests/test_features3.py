"""Wave 3: calendar, email, phone, voice lock, desktop UI."""
import asyncio
import sys
from datetime import datetime, timedelta

import httpx
import pytest

import toolkit
from features import calendar as cal
from features import desktopui, email as mail, lock, phone


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def spoken(monkeypatch):
    said = []

    async def speak(text, urgent, wait=False):
        said.append((text, urgent))

    monkeypatch.setattr(toolkit.Hooks, "speak", speak)
    monkeypatch.setattr(toolkit.Hooks, "notify", None)
    monkeypatch.setattr(toolkit.Hooks, "phone", None)
    return said


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    lock._state["until"] = 0.0
    desktopui._last.update(hwnd=0, proc="", title="", items=[])
    desktopui._pending.clear()
    cal._cache.update(at=0.0, events=[])


# ── calendar ───────────────────────────────────────────────────────────────

def _ics(*events):
    return "BEGIN:VCALENDAR\r\n" + "".join(f"BEGIN:VEVENT\r\n{e}\r\nEND:VEVENT\r\n" for e in events) + "END:VCALENDAR\r\n"


def _stamp(dt):
    return dt.strftime("%Y%m%dT%H%M%S")


def test_one_off_events_and_folding_and_escapes():
    when = datetime(2026, 10, 14, 15, 30)
    events = cal.parse(_ics(f"DTSTART:{_stamp(when)}\r\nSUMMARY:Lunch with Sam\\, again\r\n  and more\r\nLOCATION:Café"))
    assert len(events) == 1 and events[0]["title"] == "Lunch with Sam, again and more"
    rows = cal.between(events, datetime(2026, 10, 14), datetime(2026, 10, 15))
    assert rows[0][0] == when and "15:30" in cal.line(*rows[0]) and "Café" in cal.line(*rows[0])


def test_all_day_and_cancelled():
    events = cal.parse(_ics("DTSTART;VALUE=DATE:20261014\r\nSUMMARY:Holiday",
                            "DTSTART:20261014T090000\r\nSUMMARY:Gone\r\nSTATUS:CANCELLED"))
    assert [e["title"] for e in events] == ["Holiday"] and events[0]["all_day"]


def test_utc_times_are_converted_to_local():
    events = cal.parse(_ics("DTSTART:20261014T120000Z\r\nSUMMARY:Call"))
    expected = datetime(2026, 10, 14, 12).replace(tzinfo=__import__("datetime").timezone.utc).astimezone().replace(tzinfo=None)
    assert events[0]["start"] == expected


def test_weekly_recurrence_with_days_count_and_exdate():
    start = datetime(2026, 10, 12, 9, 0)            # a Monday
    ev = cal.parse(_ics(f"DTSTART:{_stamp(start)}\r\nSUMMARY:Standup\r\nRRULE:FREQ=WEEKLY;BYDAY=MO,WE;COUNT=5\r\n"
                        "EXDATE:20261014T090000"))[0]
    days = [d.strftime("%a %d") for d in cal.occurrences(ev, datetime(2026, 10, 1), datetime(2026, 12, 1))]
    # MO 12, (WE 14 excluded), MO 19, WE 21, MO 26  -> five counted, four shown
    assert days == ["Mon 12", "Mon 19", "Wed 21", "Mon 26"]


def test_daily_monthly_until():
    s = datetime(2026, 10, 1, 8, 0)
    daily = cal.parse(_ics(f"DTSTART:{_stamp(s)}\r\nSUMMARY:d\r\nRRULE:FREQ=DAILY;INTERVAL=2;UNTIL=20261007T000000"))[0]
    assert [d.day for d in cal.occurrences(daily, datetime(2026, 10, 1), datetime(2026, 11, 1))] == [1, 3, 5, 7]
    monthly = cal.parse(_ics(f"DTSTART:{_stamp(datetime(2026, 1, 31, 8))}\r\nSUMMARY:m\r\nRRULE:FREQ=MONTHLY"))[0]
    assert len(cal.occurrences(monthly, datetime(2026, 1, 1), datetime(2026, 6, 1))) >= 4


def test_handler_needs_a_link_and_reads_today(monkeypatch):
    monkeypatch.delenv("CALENDAR_ICS_URL", raising=False)
    assert "isn't connected" in run(cal.handler({"action": "today"}))
    monkeypatch.setenv("CALENDAR_ICS_URL", "http://insecure.example/x.ics")
    assert "isn't connected" in run(cal.handler({"action": "today"}))      # https only
    monkeypatch.setenv("CALENDAR_ICS_URL", "https://example.com/secret.ics")
    soon = datetime.now() + timedelta(hours=2)
    body = _ics(f"DTSTART:{_stamp(soon)}\r\nSUMMARY:Dentist")
    real = httpx.AsyncClient
    monkeypatch.setattr(cal.httpx, "AsyncClient", lambda *a, **kw: real(
        *a, **{**kw, "transport": httpx.MockTransport(lambda r: httpx.Response(200, text=body))}))
    if soon.date() == datetime.now().date():
        assert "Dentist" in run(cal.handler({"action": "today"}))
    assert "Dentist" in run(cal.handler({"action": "next"}))


def test_meeting_alert_fires_once(monkeypatch, spoken):
    monkeypatch.setenv("CALENDAR_ICS_URL", "https://example.com/secret.ics")
    soon = datetime.now() + timedelta(minutes=8)
    body = _ics(f"DTSTART:{_stamp(soon)}\r\nSUMMARY:Design review\r\nLOCATION:Room 4")
    real = httpx.AsyncClient
    monkeypatch.setattr(cal.httpx, "AsyncClient", lambda *a, **kw: real(
        *a, **{**kw, "transport": httpx.MockTransport(lambda r: httpx.Response(200, text=body))}))
    run(cal.tick())
    run(cal.tick())
    assert len(spoken) == 1 and "Design review" in spoken[0][0] and "Room 4" in spoken[0][0]


# ── email ──────────────────────────────────────────────────────────────────

def test_email_requires_setup_and_never_touches_bodies(monkeypatch):
    for k in ("EMAIL_IMAP_HOST", "EMAIL_USER", "EMAIL_APP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    assert "isn't connected" in run(mail.handler({"action": "unread"}))
    monkeypatch.setenv("EMAIL_IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("EMAIL_USER", "me@example.com")
    monkeypatch.setenv("EMAIL_APP_PASSWORD", "app-pass")
    calls = []

    class FakeImap:
        def __init__(self, host, timeout=0): calls.append(("connect", host))
        def login(self, u, p): calls.append(("login", u))
        def select(self, box, readonly=False): calls.append(("select", box, readonly))
        def search(self, *crit): calls.append(("search", crit)); return "OK", [b"1 2"]
        def fetch(self, i, spec):
            calls.append(("fetch", spec))
            hdr = b"From: =?utf-8?q?Zo=C3=AB?= <z@x.com>\r\nSubject: Invoice due\r\nDate: Tue, 14 Oct 2026 09:00:00 +0000\r\n\r\n"
            return "OK", [(b"1 (BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {99}", hdr), b")"]
        def logout(self): calls.append(("logout",))

    monkeypatch.setattr(mail.imaplib, "IMAP4_SSL", FakeImap)
    out = run(mail.handler({"action": "unread"}))
    assert "Zoë" in out and "Invoice due" in out
    assert ("select", "INBOX", True) in calls                                 # read-only
    assert all("PEEK" in c[1] for c in calls if c[0] == "fetch")              # never marks read
    assert calls[-1] == ("logout",)
    assert "Search for what" in run(mail.handler({"action": "search"}))


# ── phone ──────────────────────────────────────────────────────────────────

def test_topic_validation(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "short")
    assert phone.topic() == ""
    monkeypatch.setenv("NTFY_TOPIC", "jarvis-8f3k2n9x4q")
    assert phone.topic() == "jarvis-8f3k2n9x4q"
    monkeypatch.setenv("NTFY_TOPIC", "../../evil/thing")
    assert phone.topic() == ""


def test_urgent_things_and_unheard_things_reach_the_phone(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "jarvis-8f3k2n9x4q")
    pushed = []

    async def push(text, title="JARVIS"):
        pushed.append(text)
        return True

    async def speak(text, urgent, wait=False):
        if text.startswith("nobody"):
            raise toolkit.NoListener()

    monkeypatch.setattr(toolkit.Hooks, "speak", speak)
    monkeypatch.setattr(toolkit.Hooks, "phone", push)
    monkeypatch.setattr(toolkit.Hooks, "notify", None)
    assert run(toolkit.say("gentle chat")) is True and pushed == []
    assert run(toolkit.say("urgent!", urgent=True)) is True and pushed == ["urgent!"]
    assert run(toolkit.say("nobody home")) is True and pushed[-1] == "nobody home"
    run(phone.handler({"action": "off"}))
    assert run(toolkit.say("nobody again")) is False and pushed[-1] == "nobody home"


def test_phone_push_posts_to_the_topic(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "jarvis-8f3k2n9x4q")
    seen = []
    real = httpx.AsyncClient

    def handler(request):
        seen.append((str(request.url), request.content, request.headers["Title"]))
        return httpx.Response(200)

    monkeypatch.setattr(phone.httpx, "AsyncClient", lambda *a, **kw: real(*a, **{**kw, "transport": httpx.MockTransport(handler)}))
    assert run(phone.push("Hello")) is True
    assert seen == [("https://ntfy.sh/jarvis-8f3k2n9x4q", b"Hello", "JARVIS")]


# ── the voice lock ─────────────────────────────────────────────────────────

def test_lock_gates_sensitive_tools_until_unlocked():
    assert toolkit.check_gates("smart_home") is None                        # off by default
    lock.handler({"action": "enable"})
    assert "locked" in toolkit.check_gates("smart_home")
    assert toolkit.check_gates("calculate") is None                         # harmless tools stay open
    assert toolkit.check_gates("voice_lock") is None                        # so the lock can be queried
    assert "Unlock" in lock.handler({"action": "disable"})                  # but not removed by voice alone
    lock.unlock(5)
    assert toolkit.check_gates("smart_home") is None
    lock.lock_now()
    assert toolkit.check_gates("smart_home")
    lock.unlock(5)
    assert "off" in lock.handler({"action": "disable"})


def test_unlock_is_capped_and_endpoints_need_an_origin():
    from fastapi.testclient import TestClient
    import server
    lock.handler({"action": "enable"})
    c = TestClient(server.app, base_url="http://localhost:8340")
    assert c.get("/api/lock-status").json()["unlocked"] is False
    r = c.post("/api/unlock", json={"minutes": 9999}, headers={"Origin": "http://localhost:8340"})
    assert r.status_code == 200 and r.json()["unlocked"] and r.json()["seconds_left"] <= lock.MAX_MINUTES * 60
    assert c.post("/api/lock", headers={"Origin": "http://localhost:8340"}).json()["unlocked"] is False
    # no Origin: refused (by the web boundary, or by the route itself)
    assert c.post("/api/unlock", json={}).status_code in (400, 403)


def test_a_locked_tool_is_refused_over_the_tool_channel(monkeypatch):
    from fastapi.testclient import TestClient
    import data_paths
    import server

    class Stub:
        current_origin = "user"
        ready = True
        turn_untrusted_source = None

    monkeypatch.setattr(server, "brain_instance", Stub())
    lock.handler({"action": "enable"})
    c = TestClient(server.app, base_url="http://localhost:8340")
    token = data_paths.ensure_tool_token()
    r = c.post("/internal/tool", json={"tool": "smart_home", "arguments": {"action": "list"}},
               headers={"Authorization": f"Bearer {token}"})
    assert "locked" in r.text
    lock.unlock(1)
    r = c.post("/internal/tool", json={"tool": "smart_home", "arguments": {"action": "list"}},
               headers={"Authorization": f"Bearer {token}"})
    assert "locked" not in r.text


# ── desktop UI ─────────────────────────────────────────────────────────────

LISTING = "\n".join([
    "WIN|||4242|||notepad|||Untitled - Notepad",
    "ITEM|||0|||Edit|||Text editor|||False",
    "ITEM|||1|||Button|||Save|||False",
    "ITEM|||2|||Button|||Send|||False",
    "ITEM|||3|||Edit|||Password|||True",
    "garbage"])


@pytest.fixture
def ui(monkeypatch):
    calls = []

    async def fake(script, env=None, timeout=8.0):
        if env is None:
            return 0, LISTING, ""
        calls.append(env)
        return 0, "ok\n", ""

    monkeypatch.setattr(desktopui._ps, "run", fake)
    return calls


def test_parse_and_describe():
    win = desktopui.parse(LISTING)
    assert win["hwnd"] == 4242 and win["proc"] == "notepad" and len(win["items"]) == 4
    text = desktopui.describe(win)
    assert "[1] Button: Save" in text and "password — I will not type here" in text


def test_look_then_click_and_type(ui):
    assert "Untitled - Notepad" in run(desktopui.handler({"action": "look"}))
    assert run(desktopui.handler({"action": "click", "ref": 1})) == "Done, sir."
    assert run(desktopui.handler({"action": "type", "ref": 0, "text": "hello $(evil)"})) == "Done, sir."
    assert ui[0]["JARVIS_NAME"] == "Save" and ui[0]["JARVIS_ACTION"] == "click"
    assert ui[1]["JARVIS_TEXT"] == "hello $(evil)" and ui[1]["JARVIS_HWND"] == "4242"


def test_password_boxes_buttons_and_stale_numbers(ui):
    run(desktopui.handler({"action": "look"}))
    assert "password box" in run(desktopui.handler({"action": "type", "ref": 3, "text": "x"}))
    assert "isn't somewhere" in run(desktopui.handler({"action": "type", "ref": 1, "text": "x"}))
    assert "let me look again" in run(desktopui.handler({"action": "click", "ref": 99}))
    assert ui == []                                                         # none reached PowerShell


def test_consequential_click_needs_the_server_side_confirmation(ui):
    run(desktopui.handler({"action": "look"}))
    out = run(desktopui.handler({"action": "click", "ref": 2, "confirmed": True}))     # claimed up front
    assert "commit" in out and ui == []
    out = run(desktopui.handler({"action": "click", "ref": 2, "confirmed": True}))     # now it was asked
    assert out == "Done, sir." and ui[0]["JARVIS_NAME"] == "Send"


def test_protected_windows_are_left_alone(monkeypatch):
    async def fake(script, env=None, timeout=8.0):
        return 0, "WIN|||1|||powershell|||Windows PowerShell\nITEM|||0|||Edit|||x|||False", ""

    monkeypatch.setattr(desktopui._ps, "run", fake)
    assert "leave those alone" in run(desktopui.handler({"action": "look"}))
    assert desktopui.protected("keepassxc") and desktopui.protected("consent") and not desktopui.protected("spotify")


def test_act_without_looking_first(ui):
    assert "look at the window first" in run(desktopui.handler({"action": "click", "ref": 0}))


@pytest.mark.skipif(sys.platform != "win32", reason="needs real Windows PowerShell")
def test_real_ui_automation_scripts_parse():
    from features import _ps
    code, out, err = run(_ps.run(desktopui.LIST, timeout=30.0))
    assert "ParserError" not in err and "UnexpectedToken" not in err and "Add-Type" not in err.split("\n")[0], err
    code, out, err = run(_ps.run(desktopui.ACT, {"JARVIS_HWND": "0", "JARVIS_IDX": "0", "JARVIS_NAME": "x",
                                                  "JARVIS_ACTION": "click", "JARVIS_TEXT": ""}, timeout=30.0))
    assert "ParserError" not in err and "UnexpectedToken" not in err, err
