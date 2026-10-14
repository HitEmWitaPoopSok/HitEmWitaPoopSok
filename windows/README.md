# JARVIS for Windows

Windows port of [ethanplusai/jarvis](https://github.com/ethanplusai/jarvis).
Same brain, same dashboard, same voice. It is Windows-only: the original's
macOS-specific code has been removed, and terminal, browser, notification and
screenshot handling use `cmd.exe` and PowerShell.

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
   - A **Fish Audio API key** (<https://fish.audio>) for his voice. The
     installer has a page that asks for it (and your name) and saves it to
     `%APPDATA%\JARVIS\.env`; leave it blank and JARVIS's settings panel opens
     and asks for it the first time you start him. For unattended installs:
     `JARVIS-Setup-1.0.0.exe /VERYSILENT /fishkey=YOUR_KEY /username=Name`.
4. Start **JARVIS** from the Start menu. He opens `http://localhost:8340` in
   Chrome. **Stop JARVIS** (also in the Start menu) shuts the server down.

Your data (database, memory notes, `.env`, `jarvis.log`) lives in
`%APPDATA%\JARVIS` and survives upgrades and uninstalls.

## Things JARVIS can do at your desk and in your home

| Say | What happens |
|---|---|
| "Add football scores to my brief", "drop the weather", "what's in my brief?", "turn the brief off" | The daily brief: the first time you open JARVIS each day he reads out the topics you chose (weather, what your runs did, usage, and anything else he can look up). Change it any time by asking. Stored in `%APPDATA%\\JARVIS\\brief.json` |
| "Open the HUD" / "show systems" | The small reactor orb in the lower-left corner expands (or click it) |
| "Fix yourself" (or the button in settings / HUD) | A repair runs on a *copy* of JARVIS's code. You read the change on the HUD and press **Apply**; it keeps a backup and has **Undo**. Python code only |
| "Open Notepad", "minimise Chrome", "close the terminal", "show the desktop" | Window control. Add your own apps in `%APPDATA%\JARVIS\apps.json`, e.g. `{"spotify": "C:\\Users\\you\\AppData\\Roaming\\Spotify\\Spotify.exe"}` |
| "Go to example.com and click Sign up" | A browser JARVIS opens himself (fresh profile, no saved logins). It can click and type on web pages. It cannot control your own Chrome or other desktop apps. It never types into password or card fields and asks you before anything that buys, sends or deletes |
| "Turn off the kitchen lights", "set the bedroom to 30%", "is it warm in the hall?" | Home Assistant. In JARVIS's settings enter your Home Assistant address and a long-lived token (HA profile page, bottom). He will not operate locks, alarms, cameras or garage doors |

## What is not available on Windows

| Feature | Windows |
|---|---|
| Open a terminal / run a start command | New `cmd.exe` console window |
| Open URLs in Chrome / Firefox | Launches the browser executable directly |
| Notifications when no tab is open | Windows balloon/toast via PowerShell |
| "What's on my screen" / window list | PowerShell + `System.Drawing` (per-monitor, DPI aware) |
| Open a file in an editor | VS Code (`code`), else the file's default app |
| Answer a permission prompt in another terminal by keystroke | **Not available** (no way to name another terminal window); JARVIS says so |
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

## Everyday tools

| Say | What happens |
|---|---|
| "Remind me at 3 to call Sam", "timer for 12 minutes", "remind me to drink water every hour" | `reminder`: spoken when due (a Windows toast if no page is open); repeating nudges are gentle and held back during focus |
| "Add milk to the shopping list", "remember my passport is in the blue drawer" | `lists`: plain named lists |
| "What's 18% of 2,340?", "convert 40 euros to dollars" | `calculate`: exact arithmetic, units, currencies |
| "Summarise what I just copied", "put that on my clipboard" | `clipboard` |
| "Find the PDF about taxes I downloaded last week" | `find_files`: names only, in Documents, Downloads, Desktop |
| "I'm focusing for an hour" | `focus_mode`: holds back non-urgent speech and minimises your chosen distraction apps |
| "Save a routine called good night: lights off, minimise everything" | `routine`: named chains using a short safe list of tools |
| "Pause", "next track", "volume up" | `media_control`: media keys, works with any player |
| "Tell me when my Claude usage is high" | `alerts` |
| "What did I get done today?", "when will I hit my limit?" | `daily_summary` |
| "Start keeping my life log", "what was I working on Tuesday?" | `life_log`: off until you say so; local only; kept 30 days |
| "Switch to the black hole theme", "sounds on", "night mode" | `hud_style` |

## Adding your own tools (plugins)

Drop a `.py` file into `%APPDATA%\JARVIS\plugins\` and restart JARVIS. It
registers a tool with `toolkit`:

```python
import toolkit

toolkit.register(toolkit.Tool(
    name="coffee", description="Start the coffee machine.",
    schema={"type": "object", "properties": {}},
    handler=lambda args: "Brewing, sir.",
    acting=True, exempt="it brews, it reads nothing"))
```

A plugin runs with JARVIS's own rights, so only put there code you trust. A
plugin cannot replace a built-in tool, and one that fails to load is skipped
and logged.
