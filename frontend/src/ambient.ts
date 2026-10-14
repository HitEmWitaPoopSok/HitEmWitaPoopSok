// The always-on wall display: clock, weather, what is coming up, what is
// running. Read-only; everything is drawn with textContent.

interface Ambient {
  weather: string | null;
  reminders: { text: string; due: number }[];
  shopping: string[];
  goals: string[];
  runs: { active: number; failed: number; succeeded: number };
  usage: { label: string; pct: number }[];
  focus: boolean;
}

const $ = (id: string) => document.getElementById(id)!;

function tick() {
  const d = new Date();
  $("clock").textContent = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  $("date").textContent = d.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" });
}

function card(title: string, rows: (string | HTMLElement)[]): HTMLElement {
  const c = document.createElement("div");
  c.className = "card";
  const h = document.createElement("h2");
  h.textContent = title;
  c.appendChild(h);
  for (const r of rows) {
    if (typeof r === "string") {
      const row = document.createElement("div");
      row.textContent = r;
      c.appendChild(row);
    } else c.appendChild(r);
  }
  return c;
}

function bar(label: string, pct: number): HTMLElement {
  const w = document.createElement("div");
  const t = document.createElement("div");
  t.textContent = `${label} ${Math.round(pct)}%`;
  const b = document.createElement("div");
  b.className = "bar";
  const i = document.createElement("i");
  i.style.width = `${Math.min(100, Math.max(0, pct))}%`;
  if (pct >= 85) i.className = "hot";
  b.appendChild(i);
  w.append(t, b);
  return w;
}

async function refresh() {
  let a: Ambient;
  try {
    const res = await fetch("/api/ambient");
    if (!res.ok) throw new Error(String(res.status));
    a = await res.json();
  } catch {
    $("weather").textContent = "JARVIS is not reachable";
    return;
  }
  $("weather").textContent = a.weather ?? "";
  $("focus").textContent = a.focus ? "Focus mode is on" : "";
  const side = $("side");
  side.replaceChildren();
  const now = Date.now() / 1000;
  if (a.reminders.length) {
    side.appendChild(card("Coming up", a.reminders.map((r) => {
      const mins = Math.max(0, Math.round((r.due - now) / 60));
      const when = mins < 90 ? `in ${mins} min` : new Date(r.due * 1000).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" });
      return `${r.text} · ${when}`;
    })));
  }
  const rr = a.runs;
  side.appendChild(card("Runs today", [`${rr.active} active · ${rr.succeeded} done · ${rr.failed} failed`]));
  if (a.usage.length) side.appendChild(card("Claude usage", a.usage.map((u) => bar(u.label, u.pct))));
  if (a.goals.length) side.appendChild(card("Goals", a.goals));
  if (a.shopping.length) side.appendChild(card("Shopping", a.shopping));
}

tick();
setInterval(tick, 1000);
void refresh();
setInterval(refresh, 30000);
