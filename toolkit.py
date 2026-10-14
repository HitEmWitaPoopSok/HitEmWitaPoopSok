"""The toolkit: how a new JARVIS ability is added without touching server.py.

A feature is one module that builds a `Tool` and calls `register(...)`. The
server installs every registered tool into its tables (handler, acting gate,
taint decision), `jarvis_mcp` offers it to the brain, and `brain` allows it.
The same call is how a user's own plugin works: drop a `.py` file into
`<data>/plugins/` and it is loaded at start.

    import toolkit

    def handler(args): return "Done, sir."

    toolkit.register(toolkit.Tool(
        name="coffee", description="...", schema={"type": "object", "properties": {}},
        handler=handler, acting=True, exempt="it brews, it does not read"))

Every tool must decide how it treats foreign text, exactly like the built-in
ones: either `taint="<what it read>"` (the turn can no longer use acting tools
until the user speaks again), or `exempt="<why it reads nothing foreign>"`.
`wrap=True` has the server put the whole result inside an untrusted block.

Background work is a `Job`: a coroutine called every `interval` seconds while
the server runs. Jobs speak through `say()` and never block each other.

A plugin is the user's own code running with the server's rights. Plugins are
loaded only from the user's data directory, never from a project or a web
page, and the plugin list is logged at start.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import data_paths

log = logging.getLogger("jarvis.toolkit")

NAME_RE = re.compile(r"[a-z][a-z0-9_]{2,40}")


class NoListener(Exception):
    """Raised by the speak hook when no page is connected to speak through."""


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    handler: Callable[[dict], Any]
    acting: bool = False              # only the user's own voice may use it
    taint: Optional[str] = None       # "what it read": marks the turn untrusted
    exempt: Optional[str] = None      # why it brings back no foreign text
    reading: bool = False             # survives a tainted turn (reads, does not change)
    wrap: bool = False                # put the whole result in an untrusted block

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description,
                "inputSchema": self.schema}


@dataclass
class Job:
    name: str
    interval: float
    run: Callable[[], Awaitable[None]]


_tools: dict[str, Tool] = {}
_jobs: dict[str, Job] = {}
_tasks: list[asyncio.Task] = []


def register(tool: Tool) -> Tool:
    if not NAME_RE.fullmatch(tool.name):
        raise ValueError(f"bad tool name {tool.name!r}")
    if bool(tool.taint) == bool(tool.exempt):
        raise ValueError(f"{tool.name}: give exactly one of taint= or exempt=")
    _tools[tool.name] = tool
    return tool


def register_job(job: Job) -> Job:
    _jobs[job.name] = job
    return job


def tools() -> dict[str, Tool]:
    return dict(_tools)


def specs() -> list[dict]:
    return [t.spec() for t in _tools.values()]


def allowed_names() -> list[str]:
    return [f"mcp__jarvis__{n}" for n in _tools]


# ── hooks the server fills in ──────────────────────────────────────────────

class Hooks:
    speak: Optional[Callable[[str, bool], Awaitable[None]]] = None    # (text, urgent)
    emit: Optional[Callable[[dict], Awaitable[None]]] = None          # to the page
    notify: Optional[Callable[[str, str], Awaitable[bool]]] = None    # (title, text)
    handlers: dict = {}                                               # TOOL_HANDLERS
    wrapper: Optional[Callable[[str], str]] = None
    project_paths: Callable[[], list] = staticmethod(lambda: [])


def focus_active() -> bool:
    """True while a focus session is running (features/focus.py keeps the file)."""
    try:
        until = float(json.loads(store_path("focus").read_text()).get("until", 0))
    except (OSError, ValueError, TypeError):
        return False
    return until > time.time()


async def say(text: str, urgent: bool = False) -> bool:
    """Speak (and notify) something unprompted. Non-urgent speech is held back
    during a focus session. Returns whether it was delivered."""
    if not urgent and focus_active():
        return False
    if Hooks.speak:
        try:
            await Hooks.speak(text, urgent)
            return True
        except NoListener:
            pass                                   # nobody has the page open: toast instead
        except Exception:
            log.warning("could not speak %r", text[:40], exc_info=True)
    if Hooks.notify:
        try:
            return bool(await Hooks.notify("JARVIS", text))
        except Exception:
            pass
    return False


async def emit(msg: dict) -> None:
    if Hooks.emit:
        try:
            await Hooks.emit(msg)
        except Exception:
            pass


# ── a tiny JSON store ──────────────────────────────────────────────────────

def store_path(name: str) -> Path:
    return data_paths.data_dir() / f"{name}.json"


def load_json(name: str, default: Any) -> Any:
    try:
        value = json.loads(store_path(name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


def save_json(name: str, value: Any) -> None:
    path = store_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    tmp.replace(path)


def clean(text: Any, limit: int = 160) -> str:
    """One safe line of user-supplied text."""
    t = re.sub(r"[\x00-\x1f\x7f-\x9f<>\"`{}\\]", " ", str(text or ""))
    return " ".join(t.split())[:limit]


# ── jobs ───────────────────────────────────────────────────────────────────

async def _loop(job: Job) -> None:
    await asyncio.sleep(min(job.interval, 3.0))
    while True:
        try:
            await job.run()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("job %s failed", job.name, exc_info=True)
        await asyncio.sleep(job.interval)


def start_jobs() -> None:
    for job in _jobs.values():
        _tasks.append(asyncio.create_task(_loop(job), name=f"job:{job.name}"))


async def stop_jobs() -> None:
    for t in _tasks:
        t.cancel()
    for t in _tasks:
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
    _tasks.clear()


def _wrapped(t: Tool, wrapper: Callable[[str], str]):
    async def run(args: dict):
        result = t.handler(args)
        if asyncio.iscoroutine(result):
            result = await result
        return wrapper(str(result))
    return run


# ── loading ────────────────────────────────────────────────────────────────

def plugins_dir() -> Path:
    return data_paths.data_dir() / "plugins"


def load_features() -> None:
    import features
    features.load_all()


def load_plugins() -> list[str]:
    """Import every `<data>/plugins/*.py`. A broken plugin is skipped, loudly."""
    loaded: list[str] = []
    d = plugins_dir()
    if not d.is_dir():
        return loaded
    for path in sorted(d.glob("*.py")):
        if path.name.startswith("_"):
            continue
        before = set(_tools)
        try:
            spec = importlib.util.spec_from_file_location(f"jarvis_plugin_{path.stem}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception:
            log.warning("plugin %s failed to load", path.name, exc_info=True)
            for n in set(_tools) - before:
                _tools.pop(n, None)
            continue
        loaded.append(path.name)
    if loaded:
        log.info("plugins loaded: %s", ", ".join(loaded))
    return loaded


def install(handlers: dict, acting: set, tainting: dict, exempt: dict, reading: set,
            wrapper: Callable[[str], str], builtin: Optional[set] = None) -> None:
    """Put every registered tool into the server's tables. A tool may not
    replace a built-in one."""
    Hooks.handlers = handlers
    Hooks.wrapper = wrapper
    protected = builtin if builtin is not None else set(handlers)
    for name, t in _tools.items():
        if name in protected:
            log.warning("tool %s would replace a built-in; ignored", name)
            continue
        handlers[name] = _wrapped(t, wrapper) if t.wrap else t.handler
        if t.acting:
            acting.add(name)
        if t.taint:
            tainting[name] = t.taint
        if t.exempt:
            exempt[name] = t.exempt
        if t.reading:
            reading.add(name)
