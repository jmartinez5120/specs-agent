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
const header = h(
  ".header",
  headerTitle,
  headerSubtitle,
  h(".spacer"),
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
