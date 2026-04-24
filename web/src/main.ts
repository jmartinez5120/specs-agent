// Main entry — tailadmin-style shell (sidebar + header + main content).
//
// Navigation is intentionally minimal: Home + Spec Browser. The old
// Plan / Results / History nav items were collapsed into the Spec Browser
// shell (see screens/spec.ts). Execution and Results still exist as
// routed screens — they're pushed transiently from the Test Cases tab
// but don't have sidebar entries.

import "./styles.css";

import { health } from "./api";
import { h } from "./dom";
import { openModal } from "./modal";
import { buildAISettingsPanel } from "./modals/ai-settings";
import { initRouter, mountRoute, navigate, parseHash, register } from "./router";
import { mountExecution } from "./screens/execution";
import { mountHome } from "./screens/home";
import { mountResults } from "./screens/results";
import { mountSpec } from "./screens/spec";
import { store } from "./state";
import { initToasts } from "./toast";
import type { Route } from "./router";

const app = document.getElementById("app")!;

// ------------------------------------------------------------------ //
// Sidebar nav
// ------------------------------------------------------------------ //

interface NavItem {
  route: Route["name"];
  label: string;
  icon: string; // SVG path `d` attr
}

const NAV: NavItem[] = [
  {
    route: "home",
    label: "Home",
    icon: "M3 12l9-9 9 9M5 10v10a1 1 0 001 1h3v-6h6v6h3a1 1 0 001-1V10",
  },
  {
    route: "spec",
    label: "Spec Browser",
    icon: "M4 6h16M4 12h16M4 18h10",
  },
];

function iconSvg(dPath: string): HTMLElement {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "icon");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.style.width = "18px";
  svg.style.height = "18px";
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", dPath);
  svg.appendChild(path);
  return svg as unknown as HTMLElement;
}

const brand = h(".brand", h(".mark", "S"), h("span", "specs-agent"));

const navList = h(".nav");
const sidebar = h(".sidebar", brand, navList, h(".footer", "v0.1 · anime.js"));

function renderNav() {
  navList.innerHTML = "";
  const current = parseHash();

  navList.appendChild(h(".group", "Workspace"));
  for (const item of NAV) {
    const itemEl = h(
      `.item${current === item.route ? ".active" : ""}`,
      {
        onclick: () => {
          // Clicking Spec Browser always returns to the list — not the last
          // opened spec's detail view.
          if (item.route === "spec") {
            store.set({ spec: null, specSource: "", plan: null });
          }
          navigate(item.route);
        },
      },
      iconSvg(item.icon),
      h("span", item.label),
    );
    navList.appendChild(itemEl);
  }
}

// ------------------------------------------------------------------ //
// Header
// ------------------------------------------------------------------ //

const headerTitle = h("h1", "Home");
const headerSubtitle = h("span.subtitle", "");
const statusEl = h(
  ".status.offline",
  h("span.dot"),
  h("span", { id: "status-label" }, "offline"),
);

// ---------- Theme toggle ---------- //
type Theme = "dark" | "light";
const THEME_KEY = "specs-agent-theme";

function readTheme(): Theme {
  const saved = localStorage.getItem(THEME_KEY);
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function applyTheme(t: Theme): void {
  document.documentElement.setAttribute("data-theme", t);
  localStorage.setItem(THEME_KEY, t);
  themeBtn.innerHTML = "";
  themeBtn.appendChild(themeIcon(t));
  themeBtn.title = t === "dark" ? "Switch to light mode" : "Switch to dark mode";
}

function themeIcon(t: Theme): SVGElement {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("width", "18");
  svg.setAttribute("height", "18");
  const d = t === "dark"
    // moon
    ? "M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"
    // sun
    : "M12 3v2M12 19v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M3 12h2M19 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42";
  if (t === "light") {
    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("cx", "12");
    circle.setAttribute("cy", "12");
    circle.setAttribute("r", "4");
    svg.appendChild(circle);
  }
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", d);
  svg.appendChild(path);
  return svg;
}

const themeBtn = h("button.theme-toggle", {
  "aria-label": "Toggle theme",
  onclick: () => {
    const current = (document.documentElement.getAttribute("data-theme") as Theme) || "dark";
    applyTheme(current === "dark" ? "light" : "dark");
  },
  style: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: "36px",
    height: "36px",
    borderRadius: "var(--r-2)",
    border: "1px solid var(--border)",
    color: "var(--text-muted)",
    background: "transparent",
    cursor: "pointer",
    transition: "color 120ms, border-color 120ms, background 120ms",
  },
}) as HTMLButtonElement;
themeBtn.addEventListener("mouseenter", () => {
  themeBtn.style.color = "var(--text)";
  themeBtn.style.borderColor = "var(--border-strong)";
});
themeBtn.addEventListener("mouseleave", () => {
  themeBtn.style.color = "var(--text-muted)";
  themeBtn.style.borderColor = "var(--border)";
});

applyTheme(readTheme());

const aiSettingsBtn = h("button.theme-toggle", {
  "aria-label": "AI Settings",
  title: "AI Settings",
  onclick: () => {
    openModal({
      title: "AI Settings",
      body: buildAISettingsPanel(),
      wide: true,
    });
  },
  style: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: "36px",
    height: "36px",
    borderRadius: "var(--r-2)",
    border: "1px solid var(--border)",
    color: "var(--text-muted)",
    background: "transparent",
    cursor: "pointer",
    marginRight: "var(--s-2)",
    transition: "color 120ms, border-color 120ms",
  },
}) as HTMLButtonElement;
{
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("width", "18");
  svg.setAttribute("height", "18");
  // 4-point spark icon — represents AI/intelligence
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", "M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1");
  svg.appendChild(path);
  aiSettingsBtn.appendChild(svg as unknown as Node);
}
aiSettingsBtn.addEventListener("mouseenter", () => {
  aiSettingsBtn.style.color = "var(--text)";
  aiSettingsBtn.style.borderColor = "var(--border-strong)";
});
aiSettingsBtn.addEventListener("mouseleave", () => {
  aiSettingsBtn.style.color = "var(--text-muted)";
  aiSettingsBtn.style.borderColor = "var(--border)";
});

const header = h(
  ".header",
  headerTitle,
  headerSubtitle,
  h(".spacer"),
  aiSettingsBtn,
  themeBtn,
  statusEl,
);

// Only the two canonical routes have titles. Execution / Results are transient;
// we still label them for the header so the chrome reads correctly.
const ROUTE_TITLES: Record<
  Route["name"],
  { title: string; sub: (s: typeof store.state) => string }
> = {
  home: { title: "Home", sub: () => "Load an OpenAPI spec to begin" },
  welcome: { title: "Home", sub: () => "Load an OpenAPI spec to begin" },
  spec: {
    title: "Spec Browser",
    sub: (s) =>
      s.spec
        ? `${s.spec.title} · v${s.spec.version} · ${s.spec.endpoints.length} endpoints`
        : "List, connect, or import a spec",
  },
  execution: { title: "Run Tests", sub: () => "Live execution" },
  results: {
    title: "Results",
    sub: (s) =>
      s.lastReport
        ? `${s.lastReport.passed_tests}/${s.lastReport.total_tests} passed · ${s.lastReport.pass_rate.toFixed(0)}%`
        : "",
  },
};

function renderHeader() {
  const current = parseHash();
  const meta = ROUTE_TITLES[current] || ROUTE_TITLES.home;
  headerTitle.textContent = meta.title;
  headerSubtitle.textContent = meta.sub(store.state);
}

// ------------------------------------------------------------------ //
// Layout
// ------------------------------------------------------------------ //

const main = h(".main");
const mainArea = h(".main-area", header, main);

app.appendChild(h(".app", sidebar, mainArea));

// ---------- TRON light-cycles ---------- //
// SVG polyline per bike. Each bike moves in 90°-axis-aligned direction;
// when the head enters the cursor shield we append a turn-point to its
// polyline and swap to a perpendicular direction so the trail actually
// bends rather than teleporting.

const SVG_NS = "http://www.w3.org/2000/svg";
const MAX_BIKES = 14;
const SHIELD_RADIUS_PX = 55;
const prefersReducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

// Muted TRON palette — same hues, desaturated and dimmed so the background
// animation reads as ambient texture rather than competing with the UI.
const TRAIL_HEX = ["#3d8ba0", "#a2624a", "#8a4f7a", "#4a8a6b", "#8a7547"];

const svgRoot = document.createElementNS(SVG_NS, "svg") as SVGSVGElement;
svgRoot.setAttribute("class", "tron-svg");
svgRoot.setAttribute("preserveAspectRatio", "none");
document.body.appendChild(svgRoot);

type Vec = { x: number; y: number };
type Bike = {
  color: string;
  points: Vec[];           // polyline vertices; last one = head
  dir: Vec;                // unit direction ±1 along one axis
  speed: number;           // px/ms
  turnsLeft: number;       // caps bends per bike
  turnCooldownUntil: number; // ms
  polyline: SVGPolylineElement;
  head: SVGCircleElement;
  headGlow: SVGCircleElement;
};
const bikes: Bike[] = [];
const cursor = { x: -1, y: -1, inside: false };

window.addEventListener("mousemove", (e: MouseEvent) => {
  cursor.x = e.clientX;
  cursor.y = e.clientY;
  cursor.inside = true;
}, { passive: true });
window.addEventListener("mouseleave", () => { cursor.inside = false; }, { passive: true });

const DIRS: Vec[] = [
  { x: 1, y: 0 },  { x: -1, y: 0 },
  { x: 0, y: 1 },  { x: 0, y: -1 },
];

function spawnBike(): void {
  if (bikes.length >= MAX_BIKES) return;
  const W = window.innerWidth;
  const H = window.innerHeight;
  const color = TRAIL_HEX[Math.floor(Math.random() * TRAIL_HEX.length)];

  const dir = DIRS[Math.floor(Math.random() * DIRS.length)];
  const start: Vec = { x: 0, y: 0 };
  if (dir.x === 1)  { start.x = -20;    start.y = Math.random() * H; }
  if (dir.x === -1) { start.x = W + 20; start.y = Math.random() * H; }
  if (dir.y === 1)  { start.x = Math.random() * W; start.y = -20; }
  if (dir.y === -1) { start.x = Math.random() * W; start.y = H + 20; }

  const polyline = document.createElementNS(SVG_NS, "polyline") as SVGPolylineElement;
  polyline.setAttribute("fill", "none");
  polyline.setAttribute("stroke", color);
  polyline.setAttribute("stroke-width", "1.5");
  polyline.setAttribute("stroke-linecap", "round");
  polyline.setAttribute("stroke-linejoin", "round");
  polyline.setAttribute("opacity", "0.6");
  (polyline as SVGPolylineElement).style.filter =
    `drop-shadow(0 0 3px ${color})`;

  const headGlow = document.createElementNS(SVG_NS, "circle") as SVGCircleElement;
  headGlow.setAttribute("r", "4");
  headGlow.setAttribute("fill", color);
  headGlow.setAttribute("opacity", "0.15");
  (headGlow as SVGCircleElement).style.filter = `blur(2px)`;

  const head = document.createElementNS(SVG_NS, "circle") as SVGCircleElement;
  head.setAttribute("r", "2.5");
  head.setAttribute("fill", color);
  head.setAttribute("opacity", "0.8");
  (head as SVGCircleElement).style.filter = `drop-shadow(0 0 3px ${color})`;

  svgRoot.appendChild(polyline);
  svgRoot.appendChild(headGlow);
  svgRoot.appendChild(head);

  bikes.push({
    color,
    points: [{ ...start }, { ...start }], // start + head (movable)
    dir: { ...dir },
    speed: 0.17 + Math.random() * 0.22,   // 170–390 px/s
    turnsLeft: 2 + Math.floor(Math.random() * 3), // 2–4 turns
    turnCooldownUntil: 0,
    polyline,
    head,
    headGlow,
  });
}

function turn(b: Bike, now: number): void {
  if (b.turnsLeft <= 0 || now < b.turnCooldownUntil) return;
  // Freeze the current head as a new vertex — this is the corner.
  const headPt = b.points[b.points.length - 1];
  const corner = { x: headPt.x, y: headPt.y };
  b.points[b.points.length - 1] = corner;   // lock corner
  b.points.push({ ...corner });              // new movable head

  // Choose perpendicular direction; prefer the one pointing away from cursor.
  const perpA: Vec = { x: -b.dir.y, y: b.dir.x };
  const perpB: Vec = { x:  b.dir.y, y: -b.dir.x };
  const dxA = (corner.x + perpA.x * 20) - cursor.x;
  const dyA = (corner.y + perpA.y * 20) - cursor.y;
  const dxB = (corner.x + perpB.x * 20) - cursor.x;
  const dyB = (corner.y + perpB.y * 20) - cursor.y;
  const distA2 = dxA * dxA + dyA * dyA;
  const distB2 = dxB * dxB + dyB * dyB;
  // 15% chance of picking the "wrong" direction for randomness.
  const awayWins = Math.random() < 0.85;
  const pick = (distA2 > distB2) === awayWins ? perpA : perpB;
  b.dir = pick;
  b.turnsLeft--;
  b.turnCooldownUntil = now + 180;
}

function updateGeometry(b: Bike): void {
  const pts = b.points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  b.polyline.setAttribute("points", pts);
  const head = b.points[b.points.length - 1];
  const cx = head.x.toFixed(1);
  const cy = head.y.toFixed(1);
  b.head.setAttribute("cx", cx);
  b.head.setAttribute("cy", cy);
  b.headGlow.setAttribute("cx", cx);
  b.headGlow.setAttribute("cy", cy);
}

function isOffscreen(v: Vec): boolean {
  const M = 40;
  return v.x < -M || v.x > window.innerWidth + M
      || v.y < -M || v.y > window.innerHeight + M;
}

let lastTick = performance.now();
function tick(now: number): void {
  const dt = Math.min(48, now - lastTick);
  lastTick = now;
  const r2 = SHIELD_RADIUS_PX * SHIELD_RADIUS_PX;

  for (let i = bikes.length - 1; i >= 0; i--) {
    const b = bikes[i];
    const head = b.points[b.points.length - 1];
    head.x += b.dir.x * b.speed * dt;
    head.y += b.dir.y * b.speed * dt;

    // Shield check — if the head is inside the cursor's shield, turn.
    if (cursor.inside && b.turnsLeft > 0 && now >= b.turnCooldownUntil) {
      const dx = head.x - cursor.x;
      const dy = head.y - cursor.y;
      if (dx * dx + dy * dy <= r2) {
        turn(b, now);
      }
    }

    updateGeometry(b);

    // Remove when head exits viewport (and has at least moved a bit).
    if (isOffscreen(head) && b.points.length > 1) {
      b.polyline.remove();
      b.head.remove();
      b.headGlow.remove();
      bikes.splice(i, 1);
    }
  }

  requestAnimationFrame(tick);
}

if (!prefersReducedMotion) {
  requestAnimationFrame(tick);
  // Ambient spawner — one new bike every 500–1300ms.
  const scheduleSpawn = () => {
    const next = 500 + Math.random() * 800;
    window.setTimeout(() => {
      if (!document.hidden) spawnBike();
      scheduleSpawn();
    }, next);
  };
  scheduleSpawn();
  // Seed a few bikes immediately so the screen isn't empty on load.
  for (let i = 0; i < 4; i++) window.setTimeout(spawnBike, i * 180);
}

// ------------------------------------------------------------------ //
// Toasts
// ------------------------------------------------------------------ //

initToasts();

// ------------------------------------------------------------------ //
// Router
// ------------------------------------------------------------------ //

register("home", mountHome);
// Legacy alias — some in-app callers still `navigate("welcome")`. The router
// collapses it to `home` before mounting, but register it here too so a
// direct lookup doesn't miss.
register("welcome", mountHome);
register("spec", mountSpec);
register("execution", mountExecution);
register("results", mountResults);

initRouter(main);

function syncChrome() {
  renderNav();
  renderHeader();
}

store.subscribe(syncChrome);
window.addEventListener("hashchange", syncChrome);

// ------------------------------------------------------------------ //
// Boot
// ------------------------------------------------------------------ //

(async () => {
  try {
    await health();
    store.set({ backendOnline: true });
    statusEl.classList.remove("offline");
    const label = statusEl.querySelector("#status-label");
    if (label) label.textContent = "online";
  } catch {
    store.set({ backendOnline: false });
  }
  syncChrome();
  mountRoute(parseHash());
})();
