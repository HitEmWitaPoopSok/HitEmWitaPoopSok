/**
 * The JARVIS HUD.
 *
 * Collapsed: a small arc-reactor in the lower-left corner. Its outer ring is
 * three status arcs (microphone, voice, brain), its coil spins faster while he
 * thinks, its core pulses while he speaks, and every run in progress is a small
 * moon orbiting it. A session that needs the user is a red moon; a repair
 * waiting for approval turns the whole ring gold.
 *
 * Click it (or press H, or tell him "open the display") and it expands into a
 * panel: status, what is running, what needs the user, usage, what he is doing
 * right now, and "Fix yourself".
 *
 * Everything the panel shows arrives as data (run prompts, session names, a
 * repair's summary and diff are other people's words), so every string goes in
 * with `textContent`; nothing here uses innerHTML.
 */

import "./hud.css";

export interface HudHooks {
  getState(): string;
  isMuted(): boolean;
  getProblems(): Map<string, string>;
  openSettings(): void;
}

export interface Hud {
  open(focus?: string): void;
  close(): void;
  toggle(): void;
  noteActivity(tool: string, state: string): void;
  refresh(): void;
  setStyle(s: { theme?: string; sounds?: boolean; dim?: boolean }): void;
  cue(kind: string): void;
}

type Light = "ok" | "warn" | "bad" | "off";

interface RunRow { id: string; project_name: string; prompt: string; status: string; started_at: number | null; created_at: number }
interface SessionRow { session_id: string; project: string; state: string; since: number | null; voice_name: string }
interface UsageWindow { label: string; utilization: number | null; resets_at: number | null; expired: boolean; stale: boolean }
interface FixState {
  phase: string;
  problem?: string;
  summary?: string;
  error?: string;
  started_at?: number;
  changes?: { modified: string[]; added: string[] };
  ignored?: string[];
  diff?: string;
  applied_files?: string[];
}

const TOOL_LABEL: Record<string, string> = {
  list_sessions: "checking your sessions", session_detail: "reading a session",
  list_projects: "looking at your projects", spawn_run: "starting a run",
  start_build: "starting a build", build_status: "checking on a build",
  run_status: "checking on a run", cancel_run: "stopping a run",
  create_project: "creating a project", repo_overview: "reading the code",
  search_repo: "searching the code", read_file: "reading a file",
  read_page: "reading a web page", look_at_page: "looking at a web page",
  look_at_screen: "looking at your screen", what_is_on_screen: "checking your windows",
  open_in_browser: "opening that", open_in_terminal: "opening a terminal",
  open_in_editor: "opening your editor", run_command: "running a command",
  remember: "using memory", recall: "using memory", project_note: "using memory",
  write_journal: "using memory", usage_status: "checking your usage",
  github_repo: "looking up a repository", review_document: "reading a document",
  approve_document: "recording an approval", connections: "checking my connections",
  fix_yourself: "starting a repair", show_hud: "opening the display",
  manage_window: "working with your windows", browse: "using the browser",
};

const REDUCED = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function ago(seconds: number): string {
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}

function clock(epoch: number | null): string {
  if (!epoch) return "";
  return new Date(epoch * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

async function getJson<T>(url: string): Promise<T | null> {
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

async function post(url: string, body?: unknown): Promise<{ ok: boolean; data: any }> {
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    });
    let data: any = null;
    try { data = await res.json(); } catch { /* empty body */ }
    return { ok: res.ok, data };
  } catch (e) {
    return { ok: false, data: { error: String(e) } };
  }
}

export function createHud(hooks: HudHooks): Hud {
  // ── state ────────────────────────────────────────────────────────────
  let isOpen = false;
  let runs: RunRow[] = [];
  let needs: SessionRow[] = [];
  let windows: UsageWindow[] = [];
  let measured = false;
  let serverOk = true;
  let uptime = 0;
  let claudeInstalled = true;
  let fix: FixState = { phase: "idle" };
  let activity = { tool: "", state: "done", at: 0 };
  let fixDraft = "";
  let pollTimer: number | undefined;

  // ── DOM ──────────────────────────────────────────────────────────────
  const root = el("div");
  root.id = "hud";
  const orb = el("button");
  orb.id = "hud-orb";
  orb.type = "button";
  orb.title = "Systems (H)";
  orb.setAttribute("aria-label", "JARVIS systems display");
  orb.setAttribute("aria-expanded", "false");
  const canvas = el("canvas");
  const SIZE = 112;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = SIZE * dpr;
  canvas.height = SIZE * dpr;
  canvas.style.width = `${SIZE}px`;
  canvas.style.height = `${SIZE}px`;
  orb.appendChild(canvas);
  const panel = el("div");
  panel.id = "hud-panel";
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", "JARVIS systems");
  root.append(panel, orb);
  document.body.appendChild(root);
  const ctx = canvas.getContext("2d")!;
  ctx.scale(dpr, dpr);

  // ── lights ───────────────────────────────────────────────────────────
  function lights(): { mic: Light; voice: Light; brain: Light; server: Light } {
    const problems = hooks.getProblems();
    return {
      mic: problems.has("mic") ? "bad" : hooks.isMuted() ? "warn" : "ok",
      voice: problems.has("voice") ? "bad" : "ok",
      brain: problems.has("brain") ? "bad" : (!claudeInstalled ? "bad" : hooks.getState() === "compacting" ? "warn" : "ok"),
      server: serverOk ? "ok" : "bad",
    };
  }

  const COLOR: Record<Light, string> = { ok: "#34d399", warn: "#fbbf24", bad: "#f87171", off: "#475569" };

  // ── the reactor ──────────────────────────────────────────────────────
  const start = performance.now();
  let theme = "reactor";
  let sounds = false;
  let audio: AudioContext | null = null;
  try {
    theme = localStorage.getItem("jarvis-hud-theme") || "reactor";
    sounds = localStorage.getItem("jarvis-hud-sounds") === "1";
    if (localStorage.getItem("jarvis-hud-dim") === "1") root.classList.add("dim");
  } catch { /* storage may be blocked */ }

  /** A short tone for a state change: listening, working, done. */
  function cue(kind: string) {
    if (!sounds) return;
    try {
      audio = audio ?? new AudioContext();
      const seq: Record<string, number[]> = { listening: [660, 880], thinking: [440], done: [880, 660], error: [220, 180] };
      const notes = seq[kind];
      if (!notes) return;
      notes.forEach((f, i) => {
        const o = audio!.createOscillator();
        const gn = audio!.createGain();
        o.frequency.value = f;
        o.type = "sine";
        const t0 = audio!.currentTime + i * 0.09;
        gn.gain.setValueAtTime(0.0001, t0);
        gn.gain.exponentialRampToValueAtTime(0.05, t0 + 0.02);
        gn.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.16);
        o.connect(gn).connect(audio!.destination);
        o.start(t0);
        o.stop(t0 + 0.18);
      });
    } catch { /* no audio available */ }
  }

  function setStyle(s: { theme?: string; sounds?: boolean; dim?: boolean }) {
    try {
      if (s.theme) { theme = s.theme; localStorage.setItem("jarvis-hud-theme", theme); }
      if (s.sounds !== undefined) { sounds = s.sounds; localStorage.setItem("jarvis-hud-sounds", sounds ? "1" : "0"); if (sounds) cue("done"); }
      if (s.dim !== undefined) { root.classList.toggle("dim", s.dim); localStorage.setItem("jarvis-hud-dim", s.dim ? "1" : "0"); }
    } catch { /* storage may be blocked */ }
    if (s.theme) theme = s.theme;
    if (s.dim !== undefined) root.classList.toggle("dim", s.dim);
  }

  function draw(now: number) {
    requestAnimationFrame(draw);
    if (document.hidden) return;
    const t = (now - start) / 1000;
    const m = REDUCED ? 0.15 : 1;
    const c = SIZE / 2;
    ctx.clearRect(0, 0, SIZE, SIZE);

    const state = hooks.getState();
    const spin = ({ thinking: 1.8, speaking: 0.7, listening: 0.28, compacting: 1.2, idle: 0.14 } as Record<string, number>)[state] ?? 0.2;
    const pulse = state === "speaking" ? 0.22 : state === "thinking" ? 0.14 : 0.07;
    const pulseRate = state === "speaking" ? 7 : state === "thinking" ? 4 : 1.6;
    const L = lights();
    const fixReady = fix.phase === "ready";

    // moon orbit guides
    ctx.lineWidth = 1;
    ctx.strokeStyle = "rgba(56,189,248,0.10)";
    for (const [rx, ry, tilt] of [[50, 24, 0.5], [47, 31, -0.6]] as const) {
      ctx.beginPath();
      ctx.ellipse(c, c, rx, ry, tilt, 0, Math.PI * 2);
      ctx.stroke();
    }

    // status arcs: mic (top-right), voice (bottom), brain (top-left)
    const arcs: [number, Light][] = [[-90, L.mic], [30, L.voice], [150, L.brain]];
    for (const [startDeg, light] of arcs) {
      const a0 = ((startDeg + 5) * Math.PI) / 180;
      const a1 = ((startDeg + 115) * Math.PI) / 180;
      ctx.beginPath();
      ctx.arc(c, c, 34, a0, a1);
      ctx.lineWidth = 3.5;
      ctx.lineCap = "round";
      const flicker = light === "bad" ? 0.55 + 0.45 * Math.abs(Math.sin(t * 3)) : 1;
      ctx.strokeStyle = COLOR[light];
      ctx.globalAlpha = (light === "off" ? 0.4 : 0.9) * flicker;
      ctx.shadowColor = COLOR[light];
      ctx.shadowBlur = light === "ok" ? 4 : 8;
      ctx.stroke();
      ctx.shadowBlur = 0;
      ctx.globalAlpha = 1;
    }

    // thin outer ring (gold and pulsing when a repair waits for approval)
    ctx.beginPath();
    ctx.arc(c, c, 38.5, 0, Math.PI * 2);
    ctx.lineWidth = fixReady ? 2 : 1;
    ctx.strokeStyle = fixReady
      ? `rgba(251,191,36,${0.5 + 0.5 * Math.abs(Math.sin(t * 2.2))})`
      : "rgba(56,189,248,0.22)";
    ctx.stroke();

    if (theme === "blackhole") {
      // accretion disc around a dark core
      ctx.save();
      ctx.translate(c, c);
      for (let i = 0; i < 4; i++) {
        ctx.save();
        ctx.rotate(t * (0.35 + i * 0.12) * m + i);
        ctx.scale(1, 0.34);
        const r = 17 + i * 5;
        const gr = ctx.createRadialGradient(0, 0, r - 4, 0, 0, r + 3);
        gr.addColorStop(0, "rgba(251,146,60,0)");
        gr.addColorStop(0.5, `rgba(${251 - i * 40},${146 + i * 30},${60 + i * 50},${0.75 - i * 0.12})`);
        gr.addColorStop(1, "rgba(251,146,60,0)");
        ctx.beginPath();
        ctx.arc(0, 0, r, 0, Math.PI * 2);
        ctx.strokeStyle = gr;
        ctx.lineWidth = 5;
        ctx.stroke();
        ctx.restore();
      }
      const bk = 1 + pulse * 0.5 * Math.sin(t * pulseRate * m);
      ctx.beginPath();
      ctx.arc(0, 0, 11 * bk, 0, Math.PI * 2);
      ctx.fillStyle = "#000";
      ctx.shadowColor = "rgba(125,211,252,0.9)";
      ctx.shadowBlur = 10;
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.restore();
    } else if (theme === "moon") {
      // a pale cratered moon with a slow terminator
      const mk = 1 + pulse * 0.4 * Math.sin(t * pulseRate * m);
      ctx.save();
      ctx.translate(c, c);
      const mg = ctx.createRadialGradient(-6, -6, 2, 0, 0, 20 * mk);
      mg.addColorStop(0, "#f1f5f9");
      mg.addColorStop(0.7, "#94a3b8");
      mg.addColorStop(1, "#334155");
      ctx.beginPath();
      ctx.arc(0, 0, 18 * mk, 0, Math.PI * 2);
      ctx.fillStyle = mg;
      ctx.shadowColor = "rgba(125,211,252,0.7)";
      ctx.shadowBlur = 12;
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.fillStyle = "rgba(51,65,85,0.45)";
      for (const [x, y, r] of [[-6, -3, 3.2], [5, 4, 2.4], [2, -8, 2], [-3, 8, 1.8]] as const) {
        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    } else {
    // coil: ten segments
    ctx.save();
    ctx.translate(c, c);
    ctx.rotate(t * spin * m);
    for (let i = 0; i < 10; i++) {
      ctx.save();
      ctx.rotate((i * Math.PI * 2) / 10);
      ctx.beginPath();
      ctx.moveTo(-3.6, -27);
      ctx.lineTo(3.6, -27);
      ctx.lineTo(2.6, -19.5);
      ctx.lineTo(-2.6, -19.5);
      ctx.closePath();
      ctx.fillStyle = `rgba(56,189,248,${i % 2 ? 0.42 : 0.7})`;
      ctx.fill();
      ctx.restore();
    }
    ctx.restore();

    // core
    const k = 1 + pulse * Math.sin(t * pulseRate * m);
    const g = ctx.createRadialGradient(c, c, 0, c, c, 16 * k);
    g.addColorStop(0, "rgba(240,252,255,1)");
    g.addColorStop(0.35, "rgba(125,211,252,0.95)");
    g.addColorStop(0.75, "rgba(14,165,233,0.35)");
    g.addColorStop(1, "rgba(14,165,233,0)");
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(c, c, 16 * k, 0, Math.PI * 2);
    ctx.fill();
    // the reactor's triangle
    ctx.save();
    ctx.translate(c, c);
    ctx.rotate(-t * 0.25 * m);
    ctx.beginPath();
    for (let i = 0; i < 3; i++) {
      const a = (i * Math.PI * 2) / 3 - Math.PI / 2;
      ctx.lineTo(Math.cos(a) * 8, Math.sin(a) * 8);
    }
    ctx.closePath();
    ctx.strokeStyle = "rgba(2,40,70,0.55)";
    ctx.lineWidth = 1.2;
    ctx.stroke();
    ctx.restore();
    }

    // moons: one per active run (cyan running, amber queued), red for needs-you
    function moon(index: number, count: number, rx: number, ry: number, tilt: number, speed: number, size: number, color: string, glow: number) {
      const a = t * speed * m + (index * Math.PI * 2) / Math.max(count, 1);
      const x0 = Math.cos(a) * rx;
      const y0 = Math.sin(a) * ry;
      const x = c + x0 * Math.cos(tilt) - y0 * Math.sin(tilt);
      const y = c + x0 * Math.sin(tilt) + y0 * Math.cos(tilt);
      ctx.beginPath();
      ctx.arc(x, y, size, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.shadowColor = color;
      ctx.shadowBlur = glow;
      ctx.fill();
      ctx.shadowBlur = 0;
    }
    const shownRuns = runs.slice(0, 8);
    shownRuns.forEach((r, i) =>
      moon(i, shownRuns.length, 50, 24, 0.5, 0.55 + (i % 3) * 0.12, 3.1,
        r.status === "queued" ? "#fbbf24" : r.project_name === "jarvis-fix" ? "#fde68a" : "#67e8f9", 7));
    const shownNeeds = needs.slice(0, 6);
    shownNeeds.forEach((s, i) =>
      moon(i, shownNeeds.length, 47, 31, -0.6, -0.45, 3.8 + 0.8 * Math.abs(Math.sin(t * 3 + i)), "#f87171", 11));

    // badge
    const count = needs.length || runs.length;
    if (count) {
      ctx.font = "bold 10px Segoe UI, sans-serif";
      const label = String(count > 9 ? "9+" : count);
      const bx = SIZE - 16;
      const by = SIZE - 14;
      ctx.beginPath();
      ctx.arc(bx, by, 8.5, 0, Math.PI * 2);
      ctx.fillStyle = needs.length ? "#b91c1c" : "#075985";
      ctx.fill();
      ctx.fillStyle = "#fff";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(label, bx, by + 0.5);
    }
  }
  requestAnimationFrame(draw);

  // ── the panel ────────────────────────────────────────────────────────
  function light(kind: Light): HTMLElement {
    return el("span", `hud-dot ${kind}`);
  }

  function row(kind: Light | null, label: string, value: string, valueClass = ""): HTMLElement {
    const r = el("div", "hud-row");
    if (kind) r.append(light(kind));
    r.append(el("span", "hud-lbl", label));
    r.append(el("span", `grow ${valueClass}`, value));
    return r;
  }

  function section(title: string, extra = ""): [HTMLElement, HTMLElement] {
    const s = el("div", "hud-sec");
    const l = el("div", "hud-label");
    l.append(el("span", "", title), el("span", "", extra));
    s.append(l);
    return [s, s];
  }

  function toolText(): string {
    const label = TOOL_LABEL[activity.tool] ?? (activity.tool ? "working" : "");
    if (!activity.tool) return "idle";
    const age = (Date.now() - activity.at) / 1000;
    if (activity.state === "start") return `${label}…`;
    return age < 25 ? `finished ${label} · ${ago(age)} ago` : "idle";
  }

  function render() {
    const keepScroll = panel.scrollTop;
    const L = lights();
    const problems = hooks.getProblems();
    const state = hooks.getState();
    panel.replaceChildren();

    const head = el("div", "hud-head");
    head.append(el("span", "", "JARVIS · systems"));
    const x = el("button", "hud-x", "×");
    x.type = "button";
    x.setAttribute("aria-label", "Close");
    x.addEventListener("click", () => close());
    head.append(x);
    panel.append(head);

    // status
    const [status] = section("Status");
    status.append(
      row(L.mic, "Microphone", problems.get("mic") ?? (hooks.isMuted() ? "muted" : state === "listening" ? "listening" : "ready"), problems.has("mic") ? "hud-need" : "hud-dim"),
      row(L.voice, "Voice", problems.get("voice") ?? (state === "speaking" ? "speaking" : "ready"), problems.has("voice") ? "hud-need" : "hud-dim"),
      row(L.brain, "Brain", problems.get("brain") ?? (!claudeInstalled ? "Claude Code is not installed" : state === "thinking" ? "thinking" : state === "compacting" ? "gathering his thoughts" : "ready"), problems.has("brain") || !claudeInstalled ? "hud-need" : "hud-dim"),
      row(L.server, "Server", serverOk ? `online · up ${ago(uptime)}` : "not answering", serverOk ? "hud-dim" : "hud-need"),
    );
    if (problems.has("voice") || problems.has("mic") || problems.has("brain")) {
      const btn = el("button", "hud-btn", "Open settings");
      btn.type = "button";
      btn.style.marginTop = "6px";
      btn.addEventListener("click", () => hooks.openSettings());
      status.append(btn);
    }
    panel.append(status);

    // runs
    const [runSec] = section("Running now", String(runs.length));
    if (!runs.length) runSec.append(el("div", "hud-dim", "nothing is running"));
    for (const r of runs.slice(0, 6)) {
      const started = r.started_at ?? r.created_at;
      const line = el("div", "hud-row");
      line.append(light(r.status === "queued" ? "warn" : "ok"));
      line.append(el("span", "grow", `${r.project_name} — ${r.prompt.replace(/\s+/g, " ").slice(0, 52)}`));
      line.append(el("span", "hud-dim hud-mono", r.status === "queued" ? "queued" : ago(Date.now() / 1000 - started)));
      runSec.append(line);
    }
    panel.append(runSec);

    // needs you
    const [needSec] = section("Needs you", String(needs.length));
    if (!needs.length) needSec.append(el("div", "hud-dim", "nobody is waiting on you"));
    for (const s of needs.slice(0, 6)) {
      const line = el("div", "hud-row hud-need");
      line.append(light("bad"));
      line.append(el("span", "grow", s.project || s.voice_name));
      if (s.since) line.append(el("span", "hud-mono", `${ago(Date.now() / 1000 - s.since)}`));
      needSec.append(line);
    }
    panel.append(needSec);

    // usage
    const [useSec] = section("Usage");
    const reported = windows.filter((w) => w.utilization !== null && !w.expired);
    if (!measured || !reported.length) {
      useSec.append(el("div", "hud-dim", "no reading yet — it appears after his first reply"));
    }
    for (const w of reported) {
      const pct = Math.max(0, Math.min(100, Math.round(w.utilization!)));
      const line = el("div", "hud-row");
      line.append(el("span", "grow", w.label), el("span", "hud-mono", `${pct}%`),
        el("span", "hud-dim hud-mono", w.resets_at ? `resets ${clock(w.resets_at)}` : ""));
      const gauge = el("div", "hud-gauge");
      const fill = el("i", pct >= 85 ? "hot" : "");
      fill.style.width = `${pct}%`;
      gauge.append(fill);
      useSec.append(line, gauge);
    }
    panel.append(useSec);

    // activity
    const [actSec] = section("Doing");
    actSec.append(el("div", "hud-dim", toolText()));
    panel.append(actSec);

    // fix yourself
    panel.append(renderFix());
    panel.scrollTop = keepScroll;
  }

  function renderFix(): HTMLElement {
    const [sec] = section("Fix yourself");
    const box = el("div", "hud-fix");
    box.id = "hud-fix";
    const busy = (btn: HTMLButtonElement, label: string) => { btn.disabled = true; btn.textContent = label; };

    const startForm = (note?: string) => {
      if (note) box.append(el("div", "hud-dim", note), el("div", "", " "));
      const ta = el("textarea");
      ta.placeholder = "What's wrong? (optional — he reads his own log either way)";
      ta.value = fixDraft;
      ta.addEventListener("input", () => { fixDraft = ta.value; });
      ta.addEventListener("keydown", (e) => e.stopPropagation());
      const go = el("button", "hud-btn primary", "Fix yourself");
      go.type = "button";
      go.addEventListener("click", async () => {
        busy(go, "starting…");
        const res = await post("/api/fix-yourself", { problem: fixDraft });
        if (!res.ok) { go.disabled = false; go.textContent = "Fix yourself"; box.prepend(el("div", "hud-need", String(res.data?.error ?? "could not start"))); return; }
        fixDraft = "";
        await pollNow();
      });
      box.append(ta, go);
    };

    switch (fix.phase) {
      case "running": {
        const secs = fix.started_at ? Date.now() / 1000 - fix.started_at : 0;
        box.append(el("div", "", `Repair in progress · ${ago(secs)}`),
          el("div", "hud-dim", "A Claude Code run is working on a copy of me. Nothing changes until you approve it."));
        break;
      }
      case "ready": {
        box.classList.add("flash");
        box.append(el("div", "", "A fix is ready for your review"));
        if (fix.summary) box.append(el("div", "hud-dim", fix.summary));
        const files = [...(fix.changes?.modified ?? []), ...(fix.changes?.added ?? [])];
        const list = el("div", "hud-mono");
        list.textContent = files.map((f) => `• ${f}`).join("\n");
        list.style.whiteSpace = "pre-wrap";
        list.style.margin = "6px 0";
        box.append(list);
        if (fix.ignored?.length) {
          box.append(el("div", "hud-dim", `Not applied: ${fix.ignored.join("; ")}`));
        }
        if (fix.diff) {
          const d = el("details");
          d.append(el("summary", "", "See the change"));
          const pre = el("pre");
          for (const line of fix.diff.split("\n")) {
            const span = el("span", line.startsWith("+") && !line.startsWith("+++") ? "added" : "", line + "\n");
            pre.append(span);
          }
          d.append(pre);
          box.append(d);
        }
        const apply = el("button", "hud-btn primary", "Apply and restart");
        apply.type = "button";
        apply.style.marginTop = "8px";
        apply.addEventListener("click", async () => {
          if (!window.confirm("Apply this change to JARVIS and restart him?")) return;
          busy(apply, "applying…");
          const res = await post("/api/fix-yourself/apply");
          if (!res.ok) { apply.disabled = false; apply.textContent = "Apply and restart"; box.append(el("div", "hud-need", String(res.data?.error ?? "could not apply"))); return; }
          box.replaceChildren(el("div", "", "Applied. Restarting…"));
          setTimeout(() => window.location.reload(), 6000);
        });
        const discard = el("button", "hud-btn", "Discard");
        discard.type = "button";
        discard.addEventListener("click", async () => { await post("/api/fix-yourself/discard"); await pollNow(); });
        box.append(apply, discard);
        break;
      }
      case "nothing":
        box.append(el("div", "", "No change was needed"));
        if (fix.summary) box.append(el("div", "hud-dim", fix.summary));
        box.append(el("div", "", " "));
        startForm();
        break;
      case "failed":
        startForm(`The last repair did not finish${fix.error ? `: ${fix.error}` : ""}.`);
        break;
      case "applied": {
        box.append(el("div", "", `Applied: ${(fix.applied_files ?? []).join(", ")}`));
        const undo = el("button", "hud-btn", "Undo");
        undo.type = "button";
        undo.style.marginTop = "6px";
        undo.addEventListener("click", async () => {
          if (!window.confirm("Put the original files back and restart JARVIS?")) return;
          busy(undo, "undoing…");
          const res = await post("/api/fix-yourself/revert");
          if (!res.ok) { undo.disabled = false; undo.textContent = "Undo"; box.append(el("div", "hud-need", String(res.data?.error ?? "could not undo"))); return; }
          box.replaceChildren(el("div", "", "Undone. Restarting…"));
          setTimeout(() => window.location.reload(), 6000);
        });
        box.append(undo);
        break;
      }
      default:
        startForm("If something is broken, he can look at his own log and try to repair himself on a copy. You approve before anything changes.");
    }
    sec.append(box);
    return sec;
  }

  // ── data ─────────────────────────────────────────────────────────────
  let busyPolling = false;
  async function pollNow() {
    if (busyPolling) return;
    busyPolling = true;
    try {
      const [r, s, u, f, st] = await Promise.all([
        getJson<{ runs: RunRow[] }>("/api/runs?status=queued,running&limit=20"),
        getJson<{ sessions: SessionRow[] }>("/api/sessions?state=needs_you"),
        getJson<{ measured: boolean; windows: UsageWindow[] }>("/api/usage/limits"),
        getJson<FixState>("/api/fix-yourself"),
        getJson<{ claude_code_installed: boolean; uptime_seconds: number }>("/api/settings/status"),
      ]);
      serverOk = r !== null || st !== null;
      if (r) runs = r.runs;
      if (s) needs = s.sessions;
      if (u) { windows = u.windows ?? []; measured = !!u.measured; }
      if (f) {
        const was = fix.phase;
        fix = f;
        if (f.phase === "ready" && was !== "ready") open("fix");
      }
      if (st) { claudeInstalled = st.claude_code_installed; uptime = st.uptime_seconds; }
      if (isOpen) render();
    } finally {
      busyPolling = false;
    }
  }

  function schedule() {
    window.clearTimeout(pollTimer);
    pollTimer = window.setTimeout(async () => { await pollNow(); schedule(); }, isOpen ? 2500 : 6000);
  }

  // ── open / close ─────────────────────────────────────────────────────
  function open(focus?: string) {
    if (!isOpen) {
      isOpen = true;
      root.classList.add("open");
      orb.setAttribute("aria-expanded", "true");
    }
    render();
    void pollNow();
    schedule();
    if (focus === "fix") {
      document.getElementById("hud-fix")?.scrollIntoView({ block: "nearest", behavior: REDUCED ? "auto" : "smooth" });
    }
  }
  function close() {
    isOpen = false;
    root.classList.remove("open");
    orb.setAttribute("aria-expanded", "false");
    schedule();
  }
  function toggle() { isOpen ? close() : open(); }

  orb.addEventListener("click", (e) => { e.stopPropagation(); toggle(); });
  panel.addEventListener("click", (e) => e.stopPropagation());
  document.addEventListener("click", () => { /* the panel stays open until closed on purpose */ });
  document.addEventListener("keydown", (e) => {
    const target = e.target as HTMLElement | null;
    const typing = !!target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
    if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "h" || e.key === "H") toggle();
    else if (e.key === "Escape" && isOpen) close();
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) void pollNow(); });

  void pollNow();
  schedule();

  return {
    open, close, toggle,
    noteActivity(tool: string, state: string) {
      activity = { tool, state, at: Date.now() };
      if (isOpen) render();
    },
    refresh() { void pollNow(); },
    setStyle,
    cue,
  };
}
