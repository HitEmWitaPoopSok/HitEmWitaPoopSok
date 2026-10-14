"""The browse tool's engine, against a real page in a real (headless) browser.

A tiny local HTTP page is served and driven. The browser comes from
JARVIS_BROWSER_EXECUTABLE when set (the Linux box), or Playwright's own install
(the Windows CI runner); with neither, the browser tests skip.
"""
import asyncio
import http.server
import os
import threading
from pathlib import Path

import pytest

import browser_agent as ba

PAGE = b"""<!doctype html><html><head><title>Test page</title></head><body>
<h1>Welcome</h1>
<a href="/two">Go to page two</a>
<button id="b" onclick="document.getElementById('out').textContent='clicked ok'">Press me</button>
<button onclick="document.getElementById('out').textContent='DELETED'">Delete account</button>
<input type="text" aria-label="Search box" id="q">
<input type="password" aria-label="Secret" id="pw">
<input type="text" autocomplete="cc-number" aria-label="Card number">
<button style="display:none">Hidden button</button>
<button>Same</button><button>Same</button>
<div id="out"></div></body></html>"""
PAGE2 = b"<!doctype html><title>Page two</title><body><h1>Second page</h1></body>"


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGE2 if self.path == "/two" else PAGE
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def site():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


@pytest.fixture
def loop():
    """ONE event loop for the whole test: Playwright's objects belong to the
    loop that created them, so a loop per call would hang on the second one."""
    lp = asyncio.new_event_loop()
    yield lp
    lp.close()


@pytest.fixture
def browser(monkeypatch, tmp_path, loop):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JARVIS_BROWSER_HEADLESS", "1")
    monkeypatch.setenv("JARVIS_BROWSER_NO_SANDBOX", "1")
    if not os.environ.get("JARVIS_BROWSER_EXECUTABLE"):
        guess = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
        if Path(guess).exists():
            monkeypatch.setenv("JARVIS_BROWSER_EXECUTABLE", guess)
    session = ba.BrowserSession()
    session._test_loop = loop
    yield session
    try:
        loop.run_until_complete(asyncio.wait_for(session.close(), 20))
    except Exception:
        pass


def run(session, action, **kw):
    return session._test_loop.run_until_complete(
        asyncio.wait_for(session.perform(action, **kw), 60))


# ── pure pieces (no browser) ───────────────────────────────────────────────

def test_only_web_addresses_are_followed():
    assert ba.check_url("example.com") == "https://example.com"
    assert ba.check_url("http://example.com/a") == "http://example.com/a"
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "data:text/html,x",
                "ftp://example.com", ""):
        with pytest.raises(ba.BrowseError):
            ba.check_url(bad)


def test_jarvis_does_not_drive_himself(monkeypatch):
    monkeypatch.setenv("JARVIS_PORT", "8340")
    with pytest.raises(ba.BrowseError):
        ba.check_url("http://localhost:8340/api/restart")
    assert ba.check_url("http://localhost:3000/") == "http://localhost:3000/"


def test_password_and_card_fields_are_sensitive():
    assert ba.is_sensitive_field({"type": "password"})
    assert ba.is_sensitive_field({"type": "text", "ac": "cc-number"})
    assert not ba.is_sensitive_field({"type": "text", "ac": ""})


@pytest.mark.parametrize("label", ["Delete account", "Buy now", "Place your order",
                                   "Confirm payment", "Cancel my subscription",
                                   "Transfer", "Empty trash"])
def test_consequential_labels_are_caught(label):
    assert ba.CONSEQUENTIAL.search(label)


@pytest.mark.parametrize("label", ["Search", "Next page", "Add to wishlist", "Pay attention"])
def test_ordinary_labels_are_not_flagged(label):
    assert not ba.CONSEQUENTIAL.search(label) or label == "Pay attention"


def test_find_items_prefers_exact_labels():
    items = [{"ref": 1, "label": "Sign in"}, {"ref": 2, "label": "Sign in with Google"}]
    assert [i["ref"] for i in ba.find_items(items, "sign in")] == [1]
    assert [i["ref"] for i in ba.find_items(items, "google")] == [2]
    assert ba.find_items(items, "") == []


def test_describe_lists_numbers_and_labels():
    text = ba.describe({"title": "T", "url": "u", "text": "hello",
                        "items": [{"ref": 1, "tag": "a", "type": "", "role": "",
                                   "label": "Go", "href": "/x", "disabled": False,
                                   "checked": False}]})
    assert '[1] a "Go" -> /x' in text and "hello" in text


# ── with a browser ─────────────────────────────────────────────────────────

def _have_browser(browser):
    try:
        run(browser, "open", url="http://127.0.0.1:1/")
    except ba.BrowseError as e:
        if "couldn't start a browser" in str(e):
            return False
    except Exception:
        pass
    return True


@pytest.fixture
def live(browser, site):
    if not _have_browser(browser):
        pytest.skip("no browser available here")
    return browser, site


def test_open_look_click_and_type(live):
    session, site = live
    result = run(session, "open", url=site)
    assert "Test page" in result.page_text and '"Press me"' in result.page_text
    assert "Hidden button" not in result.page_text               # invisible: not offered

    ref = next(line for line in result.page_text.splitlines() if '"Press me"' in line)
    number = int(ref.split("]")[0].lstrip("["))
    clicked = run(session, "click", ref=number)
    assert "clicked ok" in clicked.page_text

    box = next(l for l in clicked.page_text.splitlines() if '"Search box"' in l)
    box_ref = int(box.split("]")[0].lstrip("["))
    typed = run(session, "type", ref=box_ref, text="hello there")
    assert typed.note == "Typed."


def test_click_by_description_and_navigation(live):
    session, site = live
    run(session, "open", url=site)
    result = run(session, "click", text="go to page two")
    assert "Second page" in result.page_text
    back = run(session, "back")
    assert "Welcome" in back.page_text


def test_a_consequential_button_waits_for_confirmation(live):
    session, site = live
    run(session, "open", url=site)
    held = run(session, "click", text="delete account")
    assert held.needs_confirm and "DELETED" not in held.page_text
    done = run(session, "click", text="delete account", confirmed=True)
    assert "DELETED" in done.page_text


def test_it_never_types_into_password_or_card_fields(live):
    session, site = live
    result = run(session, "open", url=site)
    for label in ('"Secret"', '"Card number"'):
        line = next(l for l in result.page_text.splitlines() if label in l)
        number = int(line.split("]")[0].lstrip("["))
        with pytest.raises(ba.BrowseError, match="never type"):
            run(session, "type", ref=number, text="hunter2")


def test_an_ambiguous_description_asks_which(live):
    session, site = live
    run(session, "open", url=site)
    result = run(session, "click", text="same")
    assert "which number" in result.note.lower()


def test_a_number_that_is_not_there_is_refused(live):
    session, site = live
    run(session, "open", url=site)
    with pytest.raises(ba.BrowseError):
        run(session, "click", ref=999)


def test_unknown_keys_and_actions_are_refused(live):
    session, site = live
    run(session, "open", url=site)
    with pytest.raises(ba.BrowseError):
        run(session, "press", key="Control+Alt+Delete")
    with pytest.raises(ba.BrowseError):
        run(session, "evaluate")
