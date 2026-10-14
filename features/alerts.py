"""Proactive alerts: he speaks up unprompted about things you chose to hear about.

Other features raise alerts with `raise_alert(kind, key, text, urgent)`; each
(kind, key) is spoken once. The user turns kinds on and off by voice.
"""
import time

import toolkit

KINDS = {"usage": "Claude usage getting high", "github": "CI and pull request changes",
         "calendar": "meetings about to start"}
DEFAULT_ON = {"usage": True, "github": True, "calendar": True}


def config() -> dict:
    cfg = toolkit.load_json("alerts", {})
    return {k: bool(cfg.get(k, DEFAULT_ON[k])) for k in KINDS}


async def raise_alert(kind: str, key: str, text: str, urgent: bool = False) -> bool:
    if not config().get(kind, False):
        return False
    seen = toolkit.load_json("alerts_seen", {})
    token = f"{kind}:{key}"
    if token in seen:
        return False
    if not await toolkit.say(text, urgent=urgent):
        return False                    # focus or no listener: try again on a later tick
    cutoff = time.time() - 14 * 86400
    seen = {k: v for k, v in seen.items() if v > cutoff}
    seen[token] = time.time()
    toolkit.save_json("alerts_seen", seen)
    return True


def handler(args: dict) -> str:
    action = str(args.get("action") or "show").lower()
    cfg = config()
    kinds = [str(k).lower() for k in (args.get("kinds") or [])]
    bad = [k for k in kinds if k not in KINDS]
    if bad:
        return "I watch for " + ", ".join(KINDS) + ", sir."
    if action in ("enable", "disable"):
        for k in kinds or list(KINDS):
            cfg[k] = action == "enable"
        toolkit.save_json("alerts", cfg)
    elif action != "show":
        return "I can show, enable or disable alerts, sir."
    return "Alerts: " + "; ".join(f"{KINDS[k]} {'on' if v else 'off'}" for k, v in cfg.items()) + "."


async def usage_tick() -> None:
    import usage_store
    snap = usage_store.snapshot()
    for w in snap.get("windows") or []:
        pct, resets = w.get("utilization"), w.get("resets_at")
        if pct is None or w.get("expired") or w.get("stale") or resets is None:
            continue
        if pct >= 90:
            await raise_alert("usage", f"{w['key']}:{int(resets)}:90",
                              f"Sir, your {w['label']} usage has reached {int(pct)} percent.", urgent=False)


toolkit.register(toolkit.Tool(
    name="alerts",
    description=("Which unprompted alerts he gives: usage (Claude limits getting high), "
                 "github (CI and pull request changes), calendar (meetings about to "
                 "start). show / enable / disable, with `kinds` (all if omitted)."),
    schema={"type": "object", "properties": {
        "action": {"type": "string", "enum": ["show", "enable", "disable"]},
        "kinds": {"type": "array", "items": {"type": "string"}}}, "required": ["action"]},
    handler=handler, acting=True, exempt="it edits the user's own switches and reads nothing foreign"))
toolkit.register_job(toolkit.Job("alerts-usage", 120.0, usage_tick))
