"""Home Assistant: lights and smart devices, through its REST API.

One tool, `smart_home`, in `server.py`; everything that talks to Home Assistant
is here. It needs two settings (JARVIS's settings panel, or `.env`):

    HOMEASSISTANT_URL    e.g. http://homeassistant.local:8123
    HOMEASSISTANT_TOKEN  a long-lived access token (HA profile page, bottom)

What it will and will not do
----------------------------
* It CONTROLS lights, switches, fans, covers (blinds, shades; not garage doors or
  gates), climate, media players, scenes, input booleans and vacuums.
* It READS those and sensors, binary sensors, weather, persons, and the state of
  locks and alarm panels ("is the front door locked?").
* It never operates a LOCK, an ALARM PANEL, a CAMERA, a SIREN, a VALVE, a SCRIPT or
  an AUTOMATION, and never opens a garage door or gate: those are security or
  can run anything, and "a voice told it to" is not a good enough reason. The
  reply says so rather than quietly doing nothing.
* A name that matches several devices acts on all of them when they are the same
  kind and there are few ("the kitchen lights"); otherwise it asks which.
* Device names are set by whoever administers Home Assistant, so they reach the
  brain inside an untrusted block like any other outside text.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

import httpx

log = logging.getLogger("jarvis.homeassistant")

CONTROL_DOMAINS = ("light", "switch", "fan", "cover", "climate", "media_player",
                   "scene", "input_boolean", "vacuum")
READ_ONLY_DOMAINS = ("sensor", "binary_sensor", "weather", "person", "lock",
                     "alarm_control_panel", "device_tracker", "sun")
NEVER_CONTROL = ("lock", "alarm_control_panel", "camera", "siren", "valve",
                 "script", "automation", "button", "update", "shell_command")
RESTRICTED_COVER_CLASSES = ("garage", "gate", "door")

ACTIONS = ("list", "state", "turn_on", "turn_off", "toggle", "open", "close",
           "stop", "set", "activate")
MAX_TARGETS = 12
MAX_LISTED = 60
TIMEOUT_SEC = 8.0

STOPWORDS = frozenset({"the", "my", "a", "an", "all", "of", "in", "on", "to", "please",
                       "everything", "lights", "light", "lamp", "lamps"})
DOMAIN_WORDS = {
    "light": "light", "lights": "light", "lamp": "light", "lamps": "light",
    "fan": "fan", "fans": "fan",
    "tv": "media_player", "television": "media_player", "speaker": "media_player",
    "speakers": "media_player", "music": "media_player",
    "blinds": "cover", "blind": "cover", "shades": "cover", "shade": "cover",
    "curtains": "cover", "curtain": "cover", "shutters": "cover",
    "thermostat": "climate", "heating": "climate", "heat": "climate", "ac": "climate",
    "plug": "switch", "outlet": "switch", "switch": "switch",
    "vacuum": "vacuum", "robot": "vacuum", "scene": "scene",
}
NOUN = {"light": "light", "switch": "switch", "fan": "fan", "cover": "cover",
        "climate": "thermostat", "media_player": "player", "scene": "scene",
        "input_boolean": "switch", "vacuum": "vacuum"}
COLORS = {"red": [255, 0, 0], "green": [0, 200, 0], "blue": [0, 80, 255],
          "white": [255, 255, 255], "purple": [150, 60, 220], "pink": [255, 90, 170],
          "orange": [255, 130, 0], "yellow": [255, 220, 0], "cyan": [0, 220, 255]}
TEMPERATURE_WORDS = {"warm": 2700, "cool": 5000, "cold": 6500, "daylight": 6000}


class HAError(Exception):
    """Something that could not be done. The message is meant to be spoken."""


@dataclass
class Entity:
    entity_id: str
    name: str
    state: str
    domain: str
    area: str = ""
    device_class: str = ""
    attributes: Optional[dict] = None


# ── configuration and transport ────────────────────────────────────────────

def settings() -> tuple[str, str]:
    url = os.environ.get("HOMEASSISTANT_URL", "").strip().rstrip("/")
    token = os.environ.get("HOMEASSISTANT_TOKEN", "").strip()
    if url and "://" not in url:
        url = "http://" + url
    return url, token


def configured() -> bool:
    url, token = settings()
    return bool(url and token)


class Client:
    """A thin client. `transport` exists so tests can answer without a network."""

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None):
        self._transport = transport

    async def request(self, method: str, path: str, json=None) -> httpx.Response:
        url, token = settings()
        if not url or not token:
            raise HAError("Home Assistant isn't set up yet — add its address and a "
                          "long-lived token in my settings")
        if not url.lower().startswith(("http://", "https://")):
            raise HAError("The Home Assistant address has to start with http or https")
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SEC, transport=self._transport) as http:
                resp = await http.request(method, url + path, json=json, headers={
                    "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        except httpx.ConnectError:
            raise HAError("I can't reach Home Assistant at the address in my settings")
        except httpx.TimeoutException:
            raise HAError("Home Assistant took too long to answer")
        except httpx.HTTPError as e:
            log.warning("home assistant request failed: %s", type(e).__name__)
            raise HAError("I couldn't talk to Home Assistant")
        if resp.status_code == 401:
            raise HAError("Home Assistant rejected my token — make a new long-lived token and paste it into my settings")
        if resp.status_code == 404:
            raise HAError("Home Assistant says it doesn't know that — is the address right?")
        if resp.status_code >= 400:
            raise HAError(f"Home Assistant refused that ({resp.status_code})")
        return resp


async def check(client: Optional[Client] = None) -> dict:
    """{"valid": bool, "error": str|None, "entities": int} for the settings panel."""
    client = client or Client()
    try:
        resp = await client.request("GET", "/api/states")
        return {"valid": True, "entities": len(resp.json())}
    except HAError as e:
        return {"valid": False, "error": str(e)}


# ── reading the house ──────────────────────────────────────────────────────

def _domain(entity_id: str) -> str:
    return entity_id.split(".", 1)[0]


async def load_entities(client: Client) -> list[Entity]:
    resp = await client.request("GET", "/api/states")
    try:
        raw = resp.json()
    except ValueError:
        raise HAError("Home Assistant sent something I couldn't read")
    areas = await _load_areas(client)
    out: list[Entity] = []
    for item in raw if isinstance(raw, list) else []:
        eid = str(item.get("entity_id", ""))
        if "." not in eid:
            continue
        attrs = item.get("attributes") or {}
        out.append(Entity(
            entity_id=eid,
            name=str(attrs.get("friendly_name") or eid.split(".", 1)[1].replace("_", " ")),
            state=str(item.get("state", "")),
            domain=_domain(eid),
            area=areas.get(eid, ""),
            device_class=str(attrs.get("device_class") or ""),
            attributes=attrs))
    return out


async def _load_areas(client: Client) -> dict[str, str]:
    """entity_id -> area name, via a template. Best effort: no areas is fine."""
    template = ("{% for s in states %}{{ s.entity_id }}|{{ area_name(s.entity_id) or '' }}\n"
                "{% endfor %}")
    try:
        resp = await client.request("POST", "/api/template", json={"template": template})
    except HAError:
        return {}
    areas: dict[str, str] = {}
    for line in resp.text.splitlines():
        eid, _, area = line.partition("|")
        if eid and area.strip():
            areas[eid.strip()] = area.strip()
    return areas


def _norm(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(text).lower())


def resolve(entities: list[Entity], target: str, readable: bool = False) -> tuple[list[Entity], Optional[str]]:
    """The devices a spoken target means, as (matches, domain hint)."""
    words = _norm(target)
    hint = next((DOMAIN_WORDS[w] for w in words if w in DOMAIN_WORDS), None)
    needed = [w for w in words if w not in STOPWORDS and w not in DOMAIN_WORDS]
    allowed = set(CONTROL_DOMAINS) | (set(READ_ONLY_DOMAINS) if readable else set()) | set(NEVER_CONTROL)
    pool = [e for e in entities if e.domain in allowed]
    if hint:
        pool = [e for e in pool if e.domain == hint]
    if not needed and not hint:
        return [], hint
    hits = []
    for e in pool:
        hay = set(_norm(e.name) + _norm(e.area) + _norm(e.entity_id.split(".", 1)[1]))
        if all(w in hay or any(h.startswith(w) for h in hay) for w in needed):
            hits.append(e)
    exact = [e for e in hits if _norm(e.name) == words or _norm(e.name) == needed]
    return (exact or hits), hint


# ── the calls ──────────────────────────────────────────────────────────────

def _service_for(domain: str, action: str, args: dict) -> tuple[str, str, dict]:
    """(domain, service, data) for one entity of `domain`, or raise HAError."""
    value = args.get("value")
    color = str(args.get("color") or "").strip().lower()
    if domain == "scene":
        if action in ("activate", "turn_on"):
            return "scene", "turn_on", {}
        raise HAError("A scene can only be activated")
    if domain == "cover":
        if action in ("open", "turn_on"):
            return "cover", "open_cover", {}
        if action in ("close", "turn_off"):
            return "cover", "close_cover", {}
        if action == "stop":
            return "cover", "stop_cover", {}
        if action == "set":
            return "cover", "set_cover_position", {"position": _percent(value)}
    if domain == "climate" and action == "set":
        try:
            temp = float(value)
        except (TypeError, ValueError):
            raise HAError("What temperature, sir?")
        if not 5 <= temp <= 35 and not 40 <= temp <= 95:
            raise HAError("That temperature doesn't look right")
        return "climate", "set_temperature", {"temperature": temp}
    if domain == "light" and action == "set":
        data: dict = {}
        if value is not None:
            data["brightness_pct"] = _percent(value)
        if color in COLORS:
            data["rgb_color"] = COLORS[color]
        elif color in TEMPERATURE_WORDS:
            data["color_temp_kelvin"] = TEMPERATURE_WORDS[color]
        elif color:
            raise HAError("I don't know that colour")
        if not data:
            raise HAError("Set it to what — a brightness, or a colour?")
        return "light", "turn_on", data
    if domain == "fan" and action == "set":
        return "fan", "set_percentage", {"percentage": _percent(value)}
    if domain == "media_player" and action == "set":
        return "media_player", "volume_set", {"volume_level": _percent(value) / 100}
    if domain == "vacuum":
        if action in ("turn_on", "open"):
            return "vacuum", "start", {}
        if action in ("turn_off", "close", "stop"):
            return "vacuum", "return_to_base", {}
    if action in ("turn_on", "turn_off", "toggle"):
        return domain, action, {}
    raise HAError("I can't do that to that kind of device")


def _percent(value) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise HAError("What level, sir?")
    return int(max(0, min(100, round(number))))


def _past(action: str, args: dict) -> str:
    return {"turn_on": "on", "turn_off": "off", "toggle": "toggled", "open": "opened",
            "close": "closed", "stop": "stopped", "activate": "activated",
            "set": "adjusted"}.get(action, "done")


def _restricted(e: Entity) -> bool:
    return e.domain in NEVER_CONTROL or (
        e.domain == "cover" and e.device_class in RESTRICTED_COVER_CLASSES)


def _summary(entities: list[Entity]) -> str:
    lines = [f"{e.name}{' (' + e.area + ')' if e.area else ''}: {e.state}" for e in entities]
    return "\n".join(lines)


@dataclass
class Reply:
    text: str
    untrusted: str = ""          # device names and states: wrapped by the caller


async def execute(args: dict, client: Optional[Client] = None) -> Reply:
    """Run one `smart_home` request. Raises HAError with a sentence."""
    client = client or Client()
    action = str(args.get("action") or "list").strip().lower()
    target = str(args.get("target") or "").strip()[:80]
    if action not in ACTIONS:
        raise HAError("I can list, read, turn on or off, toggle, open, close, set or activate")
    entities = await load_entities(client)

    if action == "list":
        shown = [e for e in entities if e.domain in CONTROL_DOMAINS]
        if target:
            shown, _ = resolve(entities, target, readable=False)
            shown = [e for e in shown if e.domain in CONTROL_DOMAINS]
        if not shown:
            return Reply("I found nothing controllable like that.")
        return Reply(f"{min(len(shown), MAX_LISTED)} of {len(shown)} devices.",
                     _summary(sorted(shown, key=lambda e: (e.domain, e.name))[:MAX_LISTED]))

    if not target:
        raise HAError("Which device, sir?")

    if action == "state":
        hits, _ = resolve(entities, target, readable=True)
        hits = [e for e in hits if e.domain in CONTROL_DOMAINS + READ_ONLY_DOMAINS
                or e.domain in ("lock", "alarm_control_panel")]
        if not hits:
            raise HAError("I can't find anything like that in the house")
        extras = []
        for e in hits[:10]:
            a = e.attributes or {}
            unit = a.get("unit_of_measurement") or ""
            extras.append(f"{e.name}: {e.state}{(' ' + unit) if unit else ''}")
        return Reply(f"{len(hits[:10])} found.", "\n".join(extras))

    hits, _hint = resolve(entities, target)
    if not hits:
        raise HAError("I can't find a device like that")
    blocked = [e for e in hits if _restricted(e)]
    hits = [e for e in hits if not _restricted(e) and e.domain in CONTROL_DOMAINS]
    if not hits:
        if blocked:
            raise HAError("That's one for your own hand, sir — I don't operate locks, "
                          "alarms, cameras or garage doors")
        raise HAError("I can't control that")
    domains = {e.domain for e in hits}
    if len(domains) > 1:
        raise HAError("That could mean several kinds of device — say which, "
                      "like the kitchen lights or the kitchen fan")
    if len(hits) > MAX_TARGETS:
        raise HAError(f"That matches {len(hits)} devices — be more specific")
    domain = hits[0].domain
    svc_domain, service, data = _service_for(domain, action, args)
    body = {**data, "entity_id": [e.entity_id for e in hits]}
    await client.request("POST", f"/api/services/{svc_domain}/{service}", json=body)
    noun = NOUN.get(domain, "device") + ("s" if len(hits) != 1 else "")
    note = f" ({len(blocked)} left alone)" if blocked else ""
    return Reply(f"Done: {len(hits)} {noun} {_past(action, args)}{note}.",
                 _summary(hits[:6]) if len(hits) > 1 else "")
