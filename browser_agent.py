"""Browser automation: JARVIS opens a page, looks at what can be clicked, clicks, types.

This is the `browse` tool's engine, driving a REAL, VISIBLE browser window with
Playwright so the user watches every move. It is deliberately not the user's
own browser profile: it has its own folder under JARVIS's data directory, so
cookies and logins made in it persist for next time (log in once, by hand, in
the window he opens) without JARVIS ever holding the user's everyday profile.

What it does not do, on purpose
-------------------------------
* It does not click anything on the user's DESKTOP. This is a page-level tool:
  Playwright can act on the page it controls and nothing else.
* It does not type into a password field or a payment-card field. Ever.
* It does not press a button whose label reads as spending money or deleting
  something until the caller says it was confirmed (the persona tells the model
  to get the user's plain say-so first).
* It does not follow `file:`/`javascript:`/`data:` addresses, or open JARVIS's
  own server, and it does not accept downloads.

Everything the page says (its text, its link and button labels) is the site's,
not JARVIS's; the server hands all of it to the brain inside an untrusted block.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import data_paths

log = logging.getLogger("jarvis.browse")

ACTIONS = ("open", "look", "click", "type", "press", "scroll", "back", "close")
KEYS = frozenset({"Enter", "Escape", "Tab", "ArrowDown", "ArrowUp", "ArrowLeft",
                  "ArrowRight", "PageDown", "PageUp", "Backspace", "Space",
                  "Home", "End"})
MAX_TYPED_CHARS = 500
MAX_ITEMS = 60
IDLE_CLOSE_SEC = 900
NAV_TIMEOUT_MS = 20_000
ACTION_TIMEOUT_MS = 6_000

# Labels that read as spending money, destroying something or leaving an account.
CONSEQUENTIAL = re.compile(
    r"\b(delete|remove account|close (my )?account|deactivate|pay( now)?|purchase|"
    r"buy( now)?|place (your |my )?order|complete order|checkout|check out|"
    r"transfer|send money|wire|confirm payment|erase|factory reset|empty (the )?trash|"
    r"cancel (my )?(subscription|membership)|unsubscribe)\b", re.I)

SCHEMES = ("http", "https")


class BrowseError(Exception):
    """Something that could not be done. The message is ours and may be spoken."""


@dataclass
class BrowseResult:
    note: str                    # trusted, a constant sentence
    page_text: str = ""          # the SITE's words: the caller wraps it as untrusted
    needs_confirm: bool = False


# Runs in the page. Tags every visible, interactive element with a number and
# returns what a person would call it. The numbers are the only thing the model
# ever uses to point at something.
_SNAPSHOT_JS = r"""() => {
  const sel = 'a[href], button, input, select, textarea, summary, [role=button], [role=link], [role=checkbox], [role=radio], [role=tab], [role=menuitem], [role=switch], [contenteditable=true], [onclick]';
  document.querySelectorAll('[data-jarvis-ref]').forEach(e => e.removeAttribute('data-jarvis-ref'));
  const seen = new Set();
  const out = [];
  const visible = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none'
      && r.bottom > 0 && r.right > 0 && r.top < innerHeight * 3;
  };
  let n = 0;
  for (const el of document.querySelectorAll(sel)) {
    if (seen.has(el) || !visible(el)) continue;
    seen.add(el);
    if (++n > %d) break;
    el.setAttribute('data-jarvis-ref', String(n));
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    const label = (el.getAttribute('aria-label')
      || (el.labels && el.labels[0] && el.labels[0].innerText)
      || el.innerText || el.getAttribute('alt') || el.getAttribute('title')
      || el.getAttribute('placeholder') || el.value || '')
      .replace(/\s+/g, ' ').trim().slice(0, 90);
    out.push({ref: n, tag: tag, type: type, role: el.getAttribute('role') || '', label: label,
              href: tag === 'a' ? (el.getAttribute('href') || '').slice(0, 100) : '',
              disabled: !!el.disabled, checked: !!el.checked,
              ac: (el.getAttribute('autocomplete') || '').toLowerCase()});
  }
  const text = (document.body ? document.body.innerText : '').replace(/\n{3,}/g, '\n\n').slice(0, 2500);
  return {title: document.title, url: location.href, text: text, items: out};
}""" % MAX_ITEMS


def check_url(url: str) -> str:
    """The URL if JARVIS may navigate to it, else BrowseError."""
    url = (url or "").strip()
    if re.match(r"(?i)(javascript|data|file|vbscript|about|blob|chrome|view-source|ftp|mailto):", url):
        raise BrowseError("I can only open web addresses")
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme.lower() not in SCHEMES or not parsed.hostname:
        raise BrowseError("I can only open web addresses")
    own_port = int(os.environ.get("JARVIS_PORT", "8340") or 8340)
    if parsed.hostname in ("localhost", "127.0.0.1", "::1", "[::1]") \
            and (parsed.port or (443 if parsed.scheme == "https" else 80)) == own_port:
        raise BrowseError("That's my own address, and I'd rather not drive myself")
    return url


def is_sensitive_field(item: dict) -> bool:
    """A field JARVIS never types into."""
    return item.get("type") == "password" or str(item.get("ac", "")).startswith("cc-")


def describe(snapshot: dict) -> str:
    """The page as the model reads it. All of it the site's words."""
    lines = [f"Title: {snapshot.get('title', '')}", f"Address: {snapshot.get('url', '')}", ""]
    items = snapshot.get("items", [])
    if items:
        lines.append("Things you can click or fill (use the number):")
        for item in items:
            kind = item.get("role") or item.get("type") or item.get("tag")
            bits = [f"[{item['ref']}] {kind}"]
            if item.get("label"):
                bits.append(f'"{item["label"]}"')
            if item.get("href"):
                bits.append(f"-> {item['href']}")
            if item.get("disabled"):
                bits.append("(disabled)")
            if item.get("checked"):
                bits.append("(checked)")
            lines.append(" ".join(bits))
        lines.append("")
    text = (snapshot.get("text") or "").strip()
    if text:
        lines.append("Page text:")
        lines.append(text)
    return "\n".join(lines)


def find_items(items: list[dict], text: str) -> list[dict]:
    """Items whose label matches a spoken description. Exact beats partial."""
    want = " ".join(text.lower().split())
    if not want:
        return []
    exact = [i for i in items if " ".join(str(i.get("label", "")).lower().split()) == want]
    if exact:
        return exact
    return [i for i in items if want in str(i.get("label", "")).lower()]


class BrowserSession:
    """One visible browser, started on first use and closed after a quiet spell."""

    def __init__(self) -> None:
        self._pw = None
        self._ctx = None
        self._page = None
        self._items: list[dict] = []
        self._last_used = 0.0
        self._lock = asyncio.Lock()

    # ── lifecycle ────────────────────────────────────────────────────────
    async def _launch(self) -> None:
        from playwright.async_api import async_playwright

        headless = os.environ.get("JARVIS_BROWSER_HEADLESS", "") == "1"
        self._pw = await async_playwright().start()
        profile = data_paths.data_dir() / "browser-profile"
        profile.mkdir(parents=True, exist_ok=True)
        options: dict = {
            "user_data_dir": str(profile),
            "headless": headless,
            "accept_downloads": False,
            "slow_mo": 0 if headless else 120,
            "ignore_https_errors": False,
        }
        if headless:
            options["viewport"] = {"width": 1280, "height": 800}
        else:
            options["no_viewport"] = True
        if os.environ.get("JARVIS_BROWSER_NO_SANDBOX") == "1":
            options["args"] = ["--no-sandbox"]

        explicit = os.environ.get("JARVIS_BROWSER_EXECUTABLE", "").strip()
        attempts = ([{"executable_path": explicit}] if explicit
                    else [{"channel": "chrome"}, {"channel": "msedge"}, {}])
        last: Optional[Exception] = None
        for extra in attempts:
            try:
                self._ctx = await self._pw.chromium.launch_persistent_context(**options, **extra)
                break
            except Exception as e:                 # try the next browser
                last = e
        if self._ctx is None:
            await self._pw.stop()
            self._pw = None
            raise BrowseError(
                "I couldn't start a browser to drive. Install Google Chrome or Edge, or "
                "re-run my installer with the browser download ticked"
            ) from last
        self._ctx.on("page", lambda p: setattr(self, "_page", p))
        self._page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()

    async def _ensure(self) -> None:
        if self._ctx is not None and time.monotonic() - self._last_used > IDLE_CLOSE_SEC:
            await self.close()
        if self._ctx is None:
            await self._launch()
        elif self._page is None or self._page.is_closed():
            pages = [p for p in self._ctx.pages if not p.is_closed()]
            self._page = pages[-1] if pages else await self._ctx.new_page()
        self._last_used = time.monotonic()

    async def close(self) -> None:
        ctx, pw = self._ctx, self._pw
        self._ctx = self._pw = self._page = None
        self._items = []
        try:
            if ctx:
                await ctx.close()
        except Exception:
            pass
        try:
            if pw:
                await pw.stop()
        except Exception:
            pass

    # ── helpers ──────────────────────────────────────────────────────────
    async def _settle(self) -> None:
        try:
            await self._page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass
        await asyncio.sleep(0.4)

    async def _look(self) -> dict:
        snapshot = await self._page.evaluate(_SNAPSHOT_JS)
        self._items = list(snapshot.get("items", []))
        return snapshot

    def _pick(self, ref, text) -> tuple[Optional[dict], Optional[list[dict]]]:
        """(the item, None), or (None, candidates) when the description is ambiguous."""
        if ref not in (None, ""):
            try:
                number = int(ref)
            except (TypeError, ValueError):
                raise BrowseError("That isn't a number I gave you")
            for item in self._items:
                if item["ref"] == number:
                    return item, None
            raise BrowseError("That number isn't on the page any more — ask me to look again")
        hits = find_items(self._items, str(text or ""))
        if not hits:
            raise BrowseError("I can't see anything like that on the page — ask me to look again")
        if len(hits) > 1:
            return None, hits[:8]
        return hits[0], None

    # ── the actions ──────────────────────────────────────────────────────
    async def perform(self, action: str, *, url: str = "", ref=None, text: str = "",
                      key: str = "", submit: bool = False, direction: str = "down",
                      confirmed: bool = False) -> BrowseResult:
        if action not in ACTIONS:
            raise BrowseError("I can open, look, click, type, press, scroll, go back or close")
        async with self._lock:
            if action == "close":
                await self.close()
                return BrowseResult("Browser closed.")
            if action == "open":
                url = check_url(url)
            await self._ensure()
            page = self._page

            if action == "open":
                for attempt in (1, 2):
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                        break
                    except Exception as e:
                        # A previous failed load leaves its error page navigating;
                        # the next goto is then "interrupted". One more try is right.
                        if attempt == 1 and "interrupted by another navigation" in str(e):
                            await asyncio.sleep(0.4)
                            continue
                        raise BrowseError("That page wouldn't load") from e
                await self._settle()
                return BrowseResult("Opened.", describe(await self._look()))

            if action == "look":
                return BrowseResult("Here is the page.", describe(await self._look()))

            if action == "back":
                try:
                    await page.go_back(timeout=NAV_TIMEOUT_MS)
                except Exception:
                    raise BrowseError("There's nothing to go back to")
                await self._settle()
                return BrowseResult("Went back.", describe(await self._look()))

            if action == "scroll":
                await page.mouse.wheel(0, -700 if str(direction).lower() == "up" else 700)
                await asyncio.sleep(0.3)
                return BrowseResult("Scrolled.", describe(await self._look()))

            if action == "press":
                if key not in KEYS:
                    raise BrowseError("I only press Enter, Escape, Tab, the arrows, Page keys, Backspace, Space, Home or End")
                await page.keyboard.press(key)
                await self._settle()
                return BrowseResult("Pressed.", describe(await self._look()))

            # click / type need something to point at
            if not self._items:
                await self._look()
            if action == "click":
                item, candidates = self._pick(ref, text)
            else:
                if ref in (None, ""):
                    raise BrowseError("Tell me which box, by its number")
                item, candidates = self._pick(ref, None)
            if candidates:
                lines = "\n".join(f"[{c['ref']}] {c.get('label', '')}" for c in candidates)
                return BrowseResult("More than one thing matches — which number?", lines)
            assert item is not None
            locator = page.locator(f'[data-jarvis-ref="{item["ref"]}"]').first

            if action == "click":
                if item.get("disabled"):
                    raise BrowseError("That one is greyed out")
                if CONSEQUENTIAL.search(item.get("label", "")) and not confirmed:
                    return BrowseResult("consequential", f'[{item["ref"]}] {item.get("label", "")}',
                                        needs_confirm=True)
                try:
                    await locator.click(timeout=ACTION_TIMEOUT_MS)
                except Exception:
                    raise BrowseError("I couldn't click that — something is in the way, or it moved")
                await self._settle()
                return BrowseResult("Clicked.", describe(await self._look()))

            # type
            if is_sensitive_field(item):
                raise BrowseError("I never type into a password or card field — you'll have to do that one yourself")
            if item.get("tag") not in ("input", "textarea") and not item.get("role") == "textbox" \
                    and item.get("type") not in ("", "text", "search", "email", "url", "tel", "number"):
                raise BrowseError("That isn't something you can type into")
            typed = str(text or "")[:MAX_TYPED_CHARS]
            try:
                await locator.fill(typed, timeout=ACTION_TIMEOUT_MS)
                if submit:
                    await locator.press("Enter", timeout=ACTION_TIMEOUT_MS)
            except Exception:
                raise BrowseError("I couldn't type into that")
            await self._settle()
            return BrowseResult("Typed.", describe(await self._look()))


_session = BrowserSession()


async def perform(action: str, **kwargs) -> BrowseResult:
    return await _session.perform(action, **kwargs)


async def shutdown() -> None:
    await _session.close()
