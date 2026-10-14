"""Built-in features, one module each. `load_all` imports them so each
registers itself with `toolkit`."""
import importlib
import logging

log = logging.getLogger("jarvis.features")

MODULES = [
    "reminders", "lists", "calculator", "clipboard", "filefinder", "focus",
    "routines", "media", "alerts", "summary", "lifelog", "hudstyle",
    "modes", "githubwatch", "codereview", "goals", "thinking", "drafts", "personality",
    "calendar", "email", "phone", "lock", "desktopui",
]


def load_all() -> None:
    for name in MODULES:
        try:
            importlib.import_module(f"features.{name}")
        except Exception:
            log.warning("feature %s failed to load", name, exc_info=True)
