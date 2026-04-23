// Minimal hash router — each route = a mount function that returns cleanup.
//
// Active routes are `home` and `spec`. The old `welcome`, `plan`, `history`
// routes were collapsed into the Spec Browser shell (see screens/spec.ts).
// `execution` and `results` remain as transient full-screen routes pushed
// from the Test Cases tab — they no longer have sidebar entries.
//
// Legacy routes (`welcome`, `plan`, `history`) redirect to `home` so deep
// links don't break. `welcome` is kept as an alias for `home` so existing
// `navigate("welcome")` calls in-app still land somewhere sensible.

export type Route =
  | { name: "home" }
  | { name: "welcome" } // alias → home (kept for back-compat)
  | { name: "spec" }
  | { name: "execution" }
  | { name: "results" };

type MountFn = (container: HTMLElement) => void | (() => void);

const routes = new Map<Route["name"], MountFn>();
let current: (() => void) | undefined;
let container: HTMLElement;

export function register(name: Route["name"], mount: MountFn): void {
  routes.set(name, mount);
}

export function initRouter(el: HTMLElement): void {
  container = el;
  window.addEventListener("hashchange", () => {
    const name = parseHash();
    mountRoute(name);
  });
}

export function navigate(name: Route["name"]): void {
  // Collapse legacy aliases so the URL stays canonical.
  const resolved = name === "welcome" ? "home" : name;
  location.hash = `#/${resolved}`;
}

export function mountRoute(name: Route["name"]): void {
  const resolved = name === "welcome" ? "home" : name;
  const fn = routes.get(resolved);
  if (!fn) {
    console.error(`No route registered: ${resolved}`);
    return;
  }
  if (current) current();
  container.innerHTML = "";
  const cleanup = fn(container);
  current = typeof cleanup === "function" ? cleanup : undefined;
}

// Returns the canonical route name for the current hash. Legacy values
// (`welcome`, `plan`, `history`) collapse to `home`.
export function parseHash(): Route["name"] {
  const h = location.hash.replace(/^#\/?/, "");
  if (h === "plan" || h === "history" || h === "welcome" || h === "") return "home";
  const valid: Route["name"][] = ["home", "spec", "execution", "results"];
  return (valid as string[]).includes(h) ? (h as Route["name"]) : "home";
}
