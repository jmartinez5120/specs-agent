// Welcome screen — hero, spec-source input, recent specs.

import { deleteSavedSpec, listSavedSpecs, loadSavedSpec, loadSpec } from "../api";
import { h } from "../dom";
import { openModal } from "../modal";
import { revealUp, staggerIn } from "../motion";
import { navigate } from "../router";
import { store } from "../state";
import { toast } from "../toast";
import { renderEndpointDetail } from "../endpoint-detail";
import type { LoadSpecResponse } from "../types";

export function mountWelcome(container: HTMLElement): () => void {
  const input = h("input.input", {
    type: "text",
    placeholder: "https://api.example.com/openapi.json   or   /path/to/spec.yaml",
    autofocus: true,
  }) as HTMLInputElement;

  const loadBtn = h(
    "button.btn.primary",
    { onclick: () => run() },
    "ENGAGE →",
  ) as HTMLButtonElement;

  async function run() {
    const source = input.value.trim();
    if (!source) {
      toast("INPUT", "Enter a spec URL or file path", "error");
      return;
    }
    loadBtn.disabled = true;
    loadBtn.textContent = "SCANNING…";
    try {
      const res = await loadSpec(source);
      store.set({ spec: res.spec, specSource: source });
      // Show scan preview before navigating
      showScanPreview(res, source);
    } catch (err) {
      toast("SCAN FAILED", String((err as Error).message), "error");
      loadBtn.disabled = false;
      loadBtn.textContent = "ENGAGE →";
    }
  }

  input.addEventListener("keydown", (e) => {
    if ((e as KeyboardEvent).key === "Enter") run();
  });

  const savedList = h(".list.bare");
  const savedPanel = h(
    ".card.recent",
    h(".card-h", h("h2", "Saved Specs")),
    savedList,
  );
  savedPanel.style.display = "none";

  // Load saved specs from backend
  listSavedSpecs(10)
    .then((specs) => {
      if (!specs || specs.length === 0) return;
      savedPanel.style.display = "";
      for (const s of specs) {
        savedList.appendChild(savedSpecRow(s));
      }
      staggerIn(savedList.querySelectorAll(".row"));
    })
    .catch(() => {
      // Backend might not be up yet
    });

  function savedSpecRow(s: { id: string; title: string; source: string; source_type: string; saved_at: string }): HTMLElement {
    const row = h(
      ".row",
      { onclick: () => loadFromSaved(s) },
      h("span.tag" + (s.source_type === "url" ? "" : ".muted"), s.source_type === "url" ? "URL" : "FILE"),
      h(
        "div",
        h(".path", s.title || s.source),
        h(".sub", s.source),
      ),
      h(
        ".inline",
        h(".sub", s.saved_at?.slice(0, 16).replace("T", " ") || ""),
        h(
          "button.btn.sm.ghost",
          {
            onclick: (e: Event) => {
              e.stopPropagation();
              deleteSavedSpec(s.id).then(() => {
                row.remove();
                toast("DELETED", s.title, "default");
                if (!savedList.querySelector(".row")) savedPanel.style.display = "none";
              }).catch((err) => toast("ERROR", String((err as Error).message), "error"));
            },
          },
          "✕",
        ),
      ),
    );
    return row;
  }

  async function loadFromSaved(s: { id: string; title: string; source: string }) {
    loadBtn.disabled = true;
    loadBtn.textContent = "LOADING…";
    try {
      // Re-load from the original source for fresh data
      const res = await loadSpec(s.source);
      store.set({ spec: res.spec, specSource: s.source });
      toast("TARGETS LOCKED", `${res.spec.title} — ${res.spec.endpoints.length} endpoints`, "success");
      navigate("spec");
    } catch {
      // If original source is unavailable, load the saved raw_spec directly
      try {
        const saved = await loadSavedSpec(s.id);
        if (saved?.raw_spec) {
          // Use the loadSpec flow with the saved source
          input.value = s.source;
          toast("LOADED FROM CACHE", `Using saved version of ${s.title}`, "default");
          run();
        }
      } catch (err2) {
        toast("LOAD FAILED", String((err2 as Error).message), "error");
      }
    } finally {
      loadBtn.disabled = false;
      loadBtn.textContent = "ENGAGE →";
    }
  }

  const card = h(
    ".welcome-card",
    h("h1.logo", "specs-agent"),
    h(".tag-line", "Load an OpenAPI spec to start building a test plan"),
    h(".card", { style: { textAlign: "left" } },
      h(".label", "OpenAPI spec source"),
      h(".row-inline", input, loadBtn),
      h(".muted", { style: { fontSize: "12px", marginTop: "8px" } },
        "↵  URL or file path  ·  backend: ",
        h("span.mono", { id: "welcome-api-status" }, "…"),
      ),
    ),
    savedPanel,
  );

  const screen = h(".welcome", card);
  container.appendChild(screen);

  revealUp([
    screen.querySelector(".logo"),
    screen.querySelector(".tag-line"),
    screen.querySelector(".panel.glow"),
    screen.querySelector(".recent"),
  ].filter(Boolean) as Element[], { delay: (_: Element, i: number) => 60 + i * 80 });

  // Live backend status
  const statusEl = screen.querySelector("#welcome-api-status");
  const sub = store.subscribe((s) => {
    if (!statusEl) return;
    statusEl.textContent = s.backendOnline ? "ONLINE" : "OFFLINE";
    (statusEl as HTMLElement).style.color = s.backendOnline
      ? "var(--lime)"
      : "var(--red)";
  });

  return () => sub();
}

function showScanPreview(res: LoadSpecResponse, source: string): void {
  const spec = res.spec;
  const tags = [...new Set(spec.endpoints.flatMap((e) => e.tags?.length ? e.tags : ["default"]))];
  const methods = spec.endpoints.reduce((acc, e) => {
    acc[e.method] = (acc[e.method] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  // --- Header strip: compact, single block ---
  const headerStrip = h("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
      gap: "var(--s-3)",
      marginBottom: "var(--s-4)",
    },
  },
    h(".stat.accent", h(".k", "Endpoints"), h(".v", String(spec.endpoints.length))),
    h(".stat", h(".k", "Tags"), h(".v", String(tags.length))),
    h(".stat", h(".k", "Version"), h(".v", spec.version)),
    h(".stat", h(".k", "Spec"), h(".v", spec.spec_version || "3.0")),
  );

  const metaRow = h("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: "var(--s-3) var(--s-5)",
      marginBottom: "var(--s-4)",
      fontSize: "12px",
    },
  },
    h("div", h(".label", "Server"), h(".mono", spec.servers?.[0]?.url || "—")),
    h("div", h(".label", "Source"), h(".mono.muted", { style: { wordBreak: "break-all" } }, source)),
    h("div",
      h(".label", "Methods"),
      h(".inline", { style: { flexWrap: "wrap", gap: "4px" } },
        ...Object.entries(methods).map(([m, count]) =>
          h(`span.method.${m}`, `${m} ×${count}`),
        ),
      ),
    ),
    h("div",
      h(".label", "Tags"),
      h(".inline", { style: { flexWrap: "wrap", gap: "4px" } },
        ...tags.map((t) => h("span.tag", t)),
      ),
    ),
  );

  // --- Two-pane body: endpoint list (left) + detail (right) ---
  const detailPane = h("div", {
    style: {
      flex: "1 1 0",
      minWidth: "0",
      overflowY: "auto",
      padding: "var(--s-4)",
      border: "1px solid var(--border)",
      borderRadius: "var(--r-2)",
      background: "var(--bg-muted)",
    },
  });

  const listPane = h("div", {
    style: {
      flex: "0 0 420px",
      overflowY: "auto",
      border: "1px solid var(--border)",
      borderRadius: "var(--r-2)",
    },
  });

  let selected: HTMLElement | null = null;
  spec.endpoints.forEach((ep, i) => {
    const row = h(".row", {
      style: { cursor: "pointer" },
      onclick: () => {
        if (selected) selected.style.background = "";
        row.style.background = "var(--bg-hover, rgba(255,255,255,0.04))";
        selected = row;
        renderDetail(ep);
      },
    },
      h(`span.method.${ep.method}`, ep.method),
      h("div",
        h(".path", ep.path),
        h(".sub",
          ep.summary || ep.operation_id || "",
          ep.tags?.length ? `  ·  ${ep.tags.join(", ")}` : "",
        ),
      ),
    );
    listPane.appendChild(row);
    if (i === 0) {
      // Auto-select first endpoint so the detail pane isn't empty
      queueMicrotask(() => row.click());
    }
  });

  function renderDetail(ep: import("../types").Endpoint): void {
    detailPane.innerHTML = "";
    detailPane.appendChild(renderEndpointDetail(ep));
  }

  // Body is a flex column that fills the modal. Header blocks have fixed size;
  // the two-pane row takes the remaining space so the overall modal never
  // resizes with the selected endpoint's content.
  const body = h("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      height: "100%",
      minHeight: "0",
    },
  },
    h("div", { style: { flex: "0 0 auto" } },
      headerStrip,
      metaRow,
      res.warnings.length
        ? h(".field", { style: { marginBottom: "var(--s-3)" } },
            h("label.label", { style: { color: "var(--warning)" } }, `Warnings (${res.warnings.length})`),
            ...res.warnings.map((w) => h(".sub", { style: { color: "var(--warning)" } }, w)),
          )
        : (null as unknown as HTMLElement),
    ),
    h("div", {
      style: {
        display: "flex",
        gap: "var(--s-3)",
        flex: "1 1 0",
        minHeight: "0",
      },
    },
      listPane,
      detailPane,
    ),
  );

  const proceed = h("button.btn.primary", {
    onclick: () => {
      close();
      toast("TARGETS LOCKED", `${spec.title} — ${spec.endpoints.length} endpoints`, "success");
      navigate("spec");
    },
  }, `PROCEED → ${spec.endpoints.length} endpoints`);

  const cancel = h("button.btn.ghost", {
    onclick: () => {
      close();
      store.set({ spec: null, specSource: "" });
    },
  }, "Cancel");

  const close = openModal({
    title: `${spec.title}`,
    body,
    actions: [cancel, proceed],
    maxWidth: "min(98vw, 1700px)",
    fixedSize: true,
  });
}


