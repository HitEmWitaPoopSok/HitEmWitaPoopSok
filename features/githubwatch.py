"""Watch GitHub repos for CI results and pull requests, and tell the user."""
import re

import httpx

import toolkit

REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,38}/[A-Za-z0-9._-]{1,100}")
MAX_REPOS = 8


def _headers() -> dict:
    import os
    h = {"Accept": "application/vnd.github+json", "User-Agent": "jarvis-for-windows"}
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


async def _get(http, path: str, **params):
    r = await http.get(f"https://api.github.com{path}", params=params, headers=_headers())
    r.raise_for_status()
    return r.json()


async def snapshot(repo: str) -> dict:
    async with httpx.AsyncClient(timeout=8.0) as http:
        runs = (await _get(http, f"/repos/{repo}/actions/runs", per_page=5)).get("workflow_runs", [])
        prs = await _get(http, f"/repos/{repo}/pulls", state="all", sort="updated",
                         direction="desc", per_page=5)
    return {"runs": runs, "prs": prs}


def describe_run(r: dict) -> str:
    return f"{r.get('name', 'workflow')} on {r.get('head_branch', '?')}: {r.get('conclusion') or r.get('status')}"


def describe_pr(p: dict) -> str:
    state = "merged" if p.get("merged_at") else p.get("state", "?")
    return f"#{p.get('number')} {str(p.get('title', ''))[:80]} ({state})"


async def tick() -> None:
    from features import alerts
    repos = toolkit.load_json("github_repos", [])
    if not repos:
        return
    seen = toolkit.load_json("github_seen", {})
    first = not seen
    for repo in repos[:MAX_REPOS]:
        try:
            snap = await snapshot(repo)
        except Exception:
            continue
        for r in snap["runs"]:
            if r.get("status") != "completed":
                continue
            key = f"{repo}:run:{r['id']}"
            if first or key in seen:
                seen[key] = 1
                continue
            seen[key] = 1
            ok = r.get("conclusion") == "success"
            await alerts.raise_alert("github", key,
                                     f"Sir, {'a build passed' if ok else 'a build FAILED'} on {repo.split('/')[1]}.",
                                     urgent=not ok)
        for p in snap["prs"]:
            state = "merged" if p.get("merged_at") else p.get("state")
            key = f"{repo}:pr:{p['number']}:{state}"
            if first or key in seen:
                seen[key] = 1
                continue
            seen[key] = 1
            await alerts.raise_alert("github", key,
                                     f"Sir, pull request {p['number']} on {repo.split('/')[1]} was {state}.")
    toolkit.save_json("github_seen", dict(list(seen.items())[-400:]))


async def handler(args: dict) -> str:
    action = str(args.get("action") or "list").lower()
    repos = toolkit.load_json("github_repos", [])
    repo = str(args.get("repo") or "").strip()
    if action == "list":
        return ("Watching: " + ", ".join(repos) + ".") if repos else "I'm not watching any repositories, sir."
    if action in ("add", "remove", "check") and not REPO_RE.fullmatch(repo):
        return "Give me the repository as owner/name, sir."
    if action == "add":
        if len(repos) >= MAX_REPOS:
            return "That's as many as I can watch, sir."
        if repo not in repos:
            repos.append(repo)
            toolkit.save_json("github_repos", repos)
            toolkit.save_json("github_seen", {})        # next tick records a baseline silently
        return f"Watching {repo}, sir."
    if action == "remove":
        if repo not in repos:
            return "I wasn't watching that, sir."
        toolkit.save_json("github_repos", [r for r in repos if r != repo])
        return "Stopped, sir."
    if action == "check":
        try:
            snap = await snapshot(repo)
        except Exception:
            return "I couldn't reach GitHub for that, sir — check the name, or set GITHUB_TOKEN for private repos."
        lines = ["Builds:"] + [f"- {describe_run(r)}" for r in snap["runs"][:5]] \
                + ["Pull requests:"] + [f"- {describe_pr(p)}" for p in snap["prs"][:5]]
        return "\n".join(lines)
    return "I can add, remove, list or check repositories, sir."


toolkit.register(toolkit.Tool(
    name="github_watch",
    description=("Watch GitHub repos (`owner/name`) so he tells the user when a build "
                 "fails or passes or a pull request opens, merges or closes: add, "
                 "remove, list. `check` reads a repo's latest builds and PRs now. "
                 "Private repos need GITHUB_TOKEN in .env."),
    schema={"type": "object", "properties": {
        "action": {"type": "string", "enum": ["add", "remove", "list", "check"]},
        "repo": {"type": "string"}}, "required": ["action"]},
    handler=handler, acting=True, reading=True, taint="GitHub build and PR titles", wrap=True))
toolkit.register_job(toolkit.Job("github", 300.0, tick))
