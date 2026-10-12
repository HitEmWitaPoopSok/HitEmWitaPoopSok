# JARVIS for Windows

Windows port of [ethanplusai/jarvis](https://github.com/ethanplusai/jarvis).
Same brain, same dashboard, same voice; the macOS plumbing (AppleScript,
`screencapture`, Notification Center, Terminal.app) is replaced with native
Windows equivalents.

## Install

1. Get **`JARVIS-Setup-x.y.z.exe`** from this repository's
   [Releases](../../releases) page, or from the latest successful run of the
   **windows-installer** workflow (Actions → run → *Artifacts* → `JARVIS-Setup`).
2. Run it. It installs per-user (no administrator prompt) to
   `%LOCALAPPDATA%\Programs\JARVIS`, and bundles its own Python — nothing else
   to install for JARVIS itself.
3. Install the things JARVIS *uses* (the installer tells you if they're missing):
   - **Claude Code**, logged in once with `claude` in a terminal
     (<https://docs.claude.com/en/docs/claude-code/setup>; it needs
     [Git for Windows](https://git-scm.com/download/win)). JARVIS thinks on your
     Claude *subscription*; no API key is used.
   - **Google Chrome** — the microphone only works there.
   - A **Fish Audio API key** (<https://fish.audio>) for his voice. Put it in
     `%APPDATA%\JARVIS\.env` as `FISH_API_KEY=...` (or in his settings page).
4. Start **JARVIS** from the Start menu. He opens `http://localhost:8340` in
   Chrome. **Stop JARVIS** (also in the Start menu) shuts the server down.

Your data (database, memory notes, `.env`, `jarvis.log`) lives in
`%APPDATA%\JARVIS` and survives upgrades and uninstalls.

## What differs from macOS

| Feature | Windows |
|---|---|
| Open a terminal / run a start command | New `cmd.exe` console window |
| Open URLs in Chrome / Firefox | Launches the browser executable directly |
| Notifications when no tab is open | Windows balloon/toast via PowerShell |
| "What's on my screen" / window list | PowerShell + `System.Drawing` (per-monitor, DPI aware) |
| Open a file in an editor | VS Code (`code`), else the file's default app |
| Answer a permission prompt in another terminal by keystroke | **Not available** (needs Terminal.app); JARVIS says so |
| Steer a message into another running session | **Not available** (needs unix-domain sockets); JARVIS says so |
| Read the Chrome tab title/URL | **Not available** |

Everything else — runs, dashboard, specs, memory, usage, session watching — is
the original code.

## Building the installer yourself

On Windows with Python 3.12, Node 22 and [Inno Setup 6](https://jrsoftware.org/isinfo.php):

```powershell
powershell -ExecutionPolicy Bypass -File windows\build.ps1 -Version 1.0.0
# -> build\out\JARVIS-Setup-1.0.0.exe
```

or let GitHub build it: **Actions → windows-installer → Run workflow**, or push a
tag such as `v1.0.0` to also publish a Release.

## Running from source (no installer)

```powershell
pip install -r requirements.txt
python -m playwright install chromium
cd frontend; npm install; npm run build; cd ..
copy .env.example .env      # add FISH_API_KEY
$env:PYTHONUTF8 = "1"
python server.py
```
