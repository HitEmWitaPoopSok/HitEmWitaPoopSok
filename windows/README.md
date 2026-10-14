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

## Work, writing and connections

| Say | What happens |
|---|---|
| "What's on my calendar tomorrow?", "when's my next meeting?" | `calendar`, read-only. Paste your calendar's secret **iCal link** in settings. He warns you ~10 minutes before a meeting |
| "Any unread email?", "find mail about the invoice" | `inbox`, read-only: senders and subjects only, never bodies; he can't send, reply or delete. Use an **app password** (Gmail/Outlook/iCloud), set in settings |
| "Watch jarvis-org/app on GitHub" | `github_watch`: tells you when a build fails or passes or a PR opens/merges. Private repos need `GITHUB_TOKEN` in settings |
| "Review my last commit" | `review_changes`: he talks you through the diff |
| "Plan my launch next week" | `goals`: tasks he works out and tracks; open goals appear in the daily brief |
| "Get a second opinion on this" | `second_opinion`: another model weighs in; the answer is spoken when ready |
| "Read me what I copied" / "read that page" | `read_aloud`; say "stop" to interrupt |
| "Draft an email to Sam about the delay" | `drafts`: he writes, you approve, he copies it to the clipboard. **He can never send anything** |
| "Take notes", "start dictating", "wake word on" | `voice_mode`: meeting notes saved in `%APPDATA%\JARVIS\notes`, typing into the focused window, or requiring "Jarvis" before he answers |
| "Be terse" / "chatty" / "whisper mode" | `speaking_style` |
| "Push alerts to my phone" | `phone_alerts` through [ntfy](https://ntfy.sh): install the ntfy app, subscribe to a long random topic, put it in settings. Urgent alerts and anything said while no page is open go to your phone |
| "Turn on the voice lock" | `voice_lock`: risky tools (lights, windows, other apps, runs) refuse until you press **Unlock** on his display (10 minutes). It stops a voice across the room or a video playing aloud; it does **not** stop someone at your keyboard |
| "Click Save in Notepad", "type this into that box" | `desktop_ui`: Windows UI Automation on the window in front. Never password boxes, system/security windows or terminals; asks before anything that sends, buys or deletes |
| open `http://localhost:8340/ambient` | The wall display: clock, weather, what's coming up, runs, usage, goals, shopping |

### What is deliberately not here
- **Speaker (voice-print) recognition.** It can't be made reliable enough to guard anything, so the voice lock uses a click instead.
- **Webcam presence or gestures.** It needs camera access and machine-learning models, and the privacy cost isn't worth it.
- **Approving things from your phone.** ntfy can't reach back into your PC without exposing it to the internet.
- **A fully offline brain.** JARVIS's brain is Claude Code; swapping in a local model is a separate project.

## The Android companion

The Android app lives in its own repository, **Jarvis-for-android**. From your phone, anywhere:

- ask JARVIS things by voice or text;
- **search your PC's folders and download a file** (an SVG or PNG you forgot, a LightBurn file), or tell JARVIS "find the logo SVG and send it to me" and it appears in the app's Files tab;
- **relay a message** to whoever is near the PC: the PC chimes, speaks it aloud, and (if you ask) carries the first thing someone says back to your phone;
- see his status and press Unlock.

It does **not** listen silently to the room, and a phone request can't run commands, open terminals or browsers, start builds or drive other apps.

### One-time setup
1. Install **Tailscale** (free) on the PC and on the phone and sign in to the same account. This is the private link between them; nothing is opened to the internet.
2. In JARVIS's HUD, press **Pair a phone**. It turns the phone link on and shows a code and an address (`100.x.x.x:8341`).
3. In the app, enter that address and code. The code works once, for five minutes.
4. Optional: put your ntfy topic in settings so alerts and "file ready" reach the phone while the app is closed.
5. To have JARVIS available when you're out, tick **Start JARVIS quietly when I sign in** in the installer (or run the installer again). The PC must be on and not asleep. Windows Firewall may ask once to allow `python.exe`; allow it on private networks.

Say "also look in D:\Laser" to add folders to what he searches (never whole drives, your user folder, or system/credential folders). Only common document, image, vector, laser and 3D file types under 100 MB are ever sent. Remove a phone from the HUD or say "revoke Pixel".
