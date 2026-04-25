// Spec Browser — shell with two modes:
//
//   List mode    — Saved specs, Connected specs (URL-sourced, refreshed on
//                  open), Import new spec. Shown when no spec is loaded.
//   Detail mode  — Spec header + "Back to list" + tab bar. Tabs:
//                    • Spec          (endpoint browser — tag chips, search, list+detail)
//                    • Test Cases    (plan editor; empty state → GENERATE)
//                    • History Runs  (past runs, drill-down shows cases + perf)
//
// Execution + Results remain transient routed screens triggered from the
// Test Cases tab; this shell does not host them.

import {
  deleteSavedSpec,
  generatePlanStreaming,
  getConfig,
  listSavedSpecs,
  loadSavedPlan,
  loadSavedSpec,
  loadSpec,
} from "../api";
import { h } from "../dom";
import { renderEndpointDetail } from "../endpoint-detail";
import { openRegenerateOptions, type RegenerateChoice } from "../modals/regenerate-options";
import { revealUp, staggerIn } from "../motion";
import { createProgressOverlay } from "../progress-overlay";
import { store } from "../state";
import { toast } from "../toast";
import type { Endpoint, ParsedSpec } from "../types";
import { renderHistoryView } from "./history-view";
import { renderPlanView } from "./plan-view";

// Top-level mount: decides list vs detail based on whether a spec is loaded,
// and re-renders when that flips.
export function mountSpec(container: HTMLElement): () => void {
  let cleanup: (() => void) | null = null;

  function render() {
    container.innerHTML = "";
    if (cleanup) {
      cleanup();
      cleanup = null;
    }
    if (store.state.spec) {
      cleanup = renderDetailMode(container);
    } else {
      cleanup = renderListMode(container);
    }
  }
  render();

  const unsub = store.subscribe(() => {
    const showingDetail = !!container.querySelector("[data-spec-mode='detail']");
    const hasSpec = !!store.state.spec;
    if (hasSpec !== showingDetail) render();
  });

  return () => {
    unsub();
    if (cleanup) cleanup();
  };
}

// ====================================================================== //
// LIST MODE
// ====================================================================== //

function renderListMode(container: HTMLElement): () => void {
  const importInput = h("input.input", {
    type: "text",
    placeholder: "https://api.example.com/openapi.json   or   /path/to/spec.yaml",
    autofocus: true,
  }) as HTMLInputElement;

  const importBtn = h(
    "button.btn.primary",
    { onclick: () => doImport() },
    "ENGAGE →",
  ) as HTMLButtonElement;

  async function doImport() {
    const source = importInput.value.trim();
    if (!source) {
      toast("INPUT", "Enter a spec URL or file path", "error");
      return;
    }
    importBtn.disabled = true;
    importBtn.textContent = "SCANNING…";
    try {
      const res = await loadSpec(source);
      store.set({
        spec: res.spec,
        specSource: source,
        plan: null,
        lastReport: null,
      });
      toast(
        "TARGETS LOCKED",
        `${res.spec.title} — ${res.spec.endpoints.length} endpoints`,
        "success",
      );
      // mountSpec's subscription handles the re-render to detail mode.
    } catch (err) {
      toast("SCAN FAILED", String((err as Error).message), "error");
      importBtn.disabled = false;
      importBtn.textContent = "ENGAGE →";
    }
  }

  importInput.addEventListener("keydown", (e) => {
    if ((e as KeyboardEvent).key === "Enter") doImport();
  });

  const connectedList = h(".list.bare");
  const savedList = h(".list.bare");
  const connectedPanel = h(
    ".panel",
    { style: { display: "none" } },
    h(
      ".panel-h",
      h("span.accent"),
      h("h2", "Connected specs"),
      h(
        "span.muted.mono",
        { style: { marginLeft: "var(--s-3)", fontSize: "11px" } },
        "re-fetched from source on open",
      ),
    ),
    connectedList,
  );
  const savedPanel = h(
    ".panel",
    { style: { display: "none" } },
    h(".panel-h", h("span.accent"), h("h2", "Saved specs")),
    savedList,
  );

  type SavedRow = {
    id: string;
    title: string;
    source: string;
    source_type: string;
    saved_at: string;
  };

  function openSaved(s: SavedRow): void {
    importBtn.disabled = true;
    importBtn.textContent = "LOADING…";
    loadSpec(s.source)
      .then((res) => {
        store.set({
          spec: res.spec,
          specSource: s.source,
          plan: null,
          lastReport: null,
        });
      })
      .catch(async (err) => {
        // Primary source unreachable — fall back to the cached snapshot.
        try {
          const saved = await loadSavedSpec(s.id);
          const cached = (saved?.raw_spec ? saved : null) as unknown as {
            spec?: ParsedSpec;
            raw_spec?: Record<string, unknown>;
          } | null;
          const cachedSpec = (saved as unknown as { spec?: ParsedSpec })?.spec;
          if (cachedSpec) {
            store.set({
              spec: cachedSpec,
              specSource: s.source,
              plan: null,
              lastReport: null,
            });
            toast(
              "USING CACHED",
              `Source unreachable — loaded last saved copy of ${s.title}`,
              "default",
            );
            return;
          }
          throw err;
        } catch (err2) {
          toast("LOAD FAILED", String((err2 as Error).message || (err as Error).message), "error");
        }
      })
      .finally(() => {
        importBtn.disabled = false;
        importBtn.textContent = "ENGAGE →";
      });
  }

  function row(s: SavedRow): HTMLElement {
    const isUrl = s.source_type === "url";
    const rowEl = h(
      ".row",
      { onclick: () => openSaved(s) },
      h("span.tag" + (isUrl ? "" : ".muted"), isUrl ? "URL" : "FILE"),
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
            title: "Delete",
            onclick: (e: Event) => {
              e.stopPropagation();
              deleteSavedSpec(s.id)
                .then(() => {
                  rowEl.remove();
                  toast("DELETED", s.title, "default");
                  if (!connectedList.querySelector(".row"))
                    connectedPanel.style.display = "none";
                  if (!savedList.querySelector(".row"))
                    savedPanel.style.display = "none";
                })
                .catch((err) =>
                  toast("ERROR", String((err as Error).message), "error"),
                );
            },
          },
          "✕",
        ),
      ),
    );
    return rowEl;
  }

  listSavedSpecs(20)
    .then((specs) => {
      const urls = specs.filter((s) => s.source_type === "url");
      const files = specs.filter((s) => s.source_type !== "url");
      if (urls.length) {
        connectedPanel.style.display = "";
        for (const s of urls) connectedList.appendChild(row(s));
        staggerIn(connectedList.querySelectorAll(".row"));
      }
      if (files.length) {
        savedPanel.style.display = "";
        for (const s of files) savedList.appendChild(row(s));
        staggerIn(savedList.querySelectorAll(".row"));
      }
    })
    .catch(() => {
      // Backend not up yet — stay quiet.
    });

  const importPanel = h(
    ".panel",
    h(".panel-h", h("span.accent"), h("h2", "Import new spec")),
    h(
      "div",
      { style: { padding: "var(--s-3)" } },
      h(".label", "OpenAPI spec source"),
      h(".row-inline", importInput, importBtn),
      h(
        ".muted",
        { style: { fontSize: "12px", marginTop: "8px" } },
        "↵  URL or file path  ·  saved automatically after a successful scan",
      ),
    ),
  );

  const root = h(
    ".stack",
    { "data-spec-mode": "list" },
    connectedPanel,
    savedPanel,
    importPanel,
  );
  container.appendChild(root);
  revealUp([...root.children] as Element[], {
    delay: (_: Element, i: number) => 60 + i * 60,
  });

  return () => {};
}

// ====================================================================== //
// DETAIL MODE — tabbed workspace
// ====================================================================== //

function renderDetailMode(container: HTMLElement): () => void {
  const spec = store.state.spec!;

  const backBtn = h(
    "button.btn",
    {
      onclick: () => {
        store.set({
          spec: null,
          specSource: "",
          plan: null,
          lastReport: null,
        });
      },
    },
    "← Back to list",
  );

  const header = h(
    ".panel-h",
    h("span.accent"),
    h("h2", spec.title),
    h(
      "span.muted.mono",
      { style: { marginLeft: "var(--s-3)" } },
      `v${spec.version}  ·  ${spec.endpoints.length} endpoints`,
    ),
    h("span.flex-1"),
    h(
      "button.btn",
      {
        onclick: async () => {
          try {
            const res = await loadSpec(store.state.specSource);
            store.set({ spec: res.spec });
            toast("REFRESHED", `${res.spec.endpoints.length} endpoints`, "success");
            // Force a re-render of the spec tab by re-triggering the tab.
            setTab(activeTab);
          } catch (e) {
            toast("REFRESH FAILED", String((e as Error).message), "error");
          }
        },
      },
      "Refresh",
    ),
    backBtn,
  );

  // --- Tab bar ---
  type Tab = "spec" | "cases" | "history";
  const initialPending = store.state.pendingSelection;
  let activeTab: Tab = (initialPending?.tab ?? "spec") as Tab;

  const tabBar = h("div", {
    style: {
      display: "flex",
      gap: "0",
      padding: "0 var(--s-4)",
      borderBottom: "1px solid var(--border)",
    },
  });
  const tabBody = h("div", {
    style: {
      flex: "1 1 0",
      minHeight: "0",
      overflow: "auto",
      padding: "var(--s-3)",
    },
  });

  function renderTabs() {
    tabBar.innerHTML = "";
    const mk = (key: Tab, label: string) => {
      const active = activeTab === key;
      return h(
        "button",
        {
          onclick: () => setTab(key),
          style: {
            background: "transparent",
            border: "none",
            borderBottom: active
              ? "2px solid var(--primary, #d4a828)"
              : "2px solid transparent",
            color: active ? "var(--text, #e5e7eb)" : "var(--muted, #9ca3af)",
            padding: "var(--s-3) var(--s-4)",
            fontSize: "13px",
            fontWeight: active ? "600" : "500",
            letterSpacing: "0.04em",
            cursor: "pointer",
            transition: "color 120ms ease, border-color 120ms ease",
            marginBottom: "-1px",
            fontFamily: "inherit",
          },
          onmouseenter: (e: Event) => {
            if (!active) (e.currentTarget as HTMLElement).style.color = "var(--text, #e5e7eb)";
          },
          onmouseleave: (e: Event) => {
            if (!active) (e.currentTarget as HTMLElement).style.color = "var(--muted, #9ca3af)";
          },
        },
        label,
      );
    };
    tabBar.appendChild(mk("spec", "Spec"));
    const planCount = store.state.plan?.test_cases?.length ?? 0;
    tabBar.appendChild(
      mk("cases", planCount ? `Test Cases (${planCount})` : "Test Cases"),
    );
    tabBar.appendChild(mk("history", "History Runs"));
  }

  function setTab(t: Tab) {
    activeTab = t;
    renderTabs();
    tabBody.innerHTML = "";
    if (t === "spec") tabBody.appendChild(renderSpecTab());
    else if (t === "cases") tabBody.appendChild(renderCasesTab());
    else tabBody.appendChild(renderHistoryView());
  }

  // Auto-load a saved plan (if any) so Test Cases has content on first open.
  loadSavedPlan(spec.title)
    .then((saved) => {
      if (saved && !store.state.plan) {
        store.set({ plan: saved });
        renderTabs();
        if (activeTab === "cases") {
          tabBody.innerHTML = "";
          tabBody.appendChild(renderCasesTab());
        }
      }
    })
    .catch(() => {});

  renderTabs();
  setTab("spec");

  const shell = h(
    "div",
    {
      "data-spec-mode": "detail",
      style: {
        display: "flex",
        flexDirection: "column",
        height: "100%",
        minHeight: "0",
      },
    },
    h(
      ".panel",
      {
        style: {
          flex: "1 1 0",
          minHeight: "0",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        },
      },
      tabBar,
      header,
      tabBody,
    ),
  );
  container.appendChild(shell);

  // Claim full main area.
  const mainEl = container.closest(".main") as HTMLElement | null;
  const prevOverflow = mainEl?.style.overflow ?? "";
  const prevDisplay = mainEl?.style.display ?? "";
  const prevPadding = mainEl?.style.padding ?? "";
  const prevFlexDirection = mainEl?.style.flexDirection ?? "";
  if (mainEl) {
    mainEl.style.overflow = "hidden";
    mainEl.style.display = "flex";
    mainEl.style.flexDirection = "column";
    mainEl.style.padding = "var(--s-4)";
  }

  revealUp([shell], { delay: (_: Element, i: number) => i * 90 });

  return () => {
    if (mainEl) {
      mainEl.style.overflow = prevOverflow;
      mainEl.style.display = prevDisplay;
      mainEl.style.padding = prevPadding;
      mainEl.style.flexDirection = prevFlexDirection;
    }
  };

  // ------------------------------------------------------------------ //
  // Tab: Spec (endpoint browser)
  // ------------------------------------------------------------------ //
  function renderSpecTab(): HTMLElement {
    const spec = store.state.spec!;
    const grouped = new Map<string, Endpoint[]>();
    for (const ep of spec.endpoints) {
      const tags = ep.tags?.length ? ep.tags : ["default"];
      for (const t of tags) {
        if (!grouped.has(t)) grouped.set(t, []);
        grouped.get(t)!.push(ep);
      }
    }
    const tagOrder = [...grouped.keys()].sort();

    const filterBar = h(".inline", {
      style: { flexWrap: "wrap", gap: "var(--s-2)", marginBottom: "var(--s-3)" },
    });
    let activeTag: string | null = null;

    function chip(label: string, count: number, tag: string | null): HTMLElement {
      const isActive = activeTag === tag;
      return h(
        `button.btn.sm${isActive ? ".primary" : ""}`,
        { onclick: () => selectTag(tag) },
        `${label.toUpperCase()}  `,
        h("span.muted.mono", { style: { marginLeft: "4px" } }, String(count)),
      );
    }

    function renderFilterBar() {
      filterBar.innerHTML = "";
      filterBar.appendChild(chip("All", spec.endpoints.length, null));
      for (const tag of tagOrder) {
        filterBar.appendChild(chip(tag, grouped.get(tag)!.length, tag));
      }
    }

    let searchQuery = "";
    const searchInput = h("input.input", {
      type: "text",
      placeholder: "Search endpoints — path, method, summary, tag…",
      style: { marginBottom: "var(--s-2)" },
      oninput: (e: Event) => {
        searchQuery = (e.target as HTMLInputElement).value;
        applyFilters();
      },
    }) as HTMLInputElement;

    const listEl = h("div", {
      style: {
        overflowY: "auto",
        border: "1px solid var(--border)",
        borderRadius: "var(--r-2)",
        padding: "var(--s-1)",
        flex: "1 1 0",
        minHeight: "0",
      },
    });
    const leftCol = h(
      "div",
      {
        style: {
          display: "flex",
          flexDirection: "column",
          minHeight: "0",
          height: "100%",
        },
      },
      searchInput,
      listEl,
    );
    const detailEl = h("div", {
      style: {
        overflowY: "auto",
        padding: "var(--s-4)",
        border: "1px solid var(--border)",
        borderRadius: "var(--r-2)",
        background: "var(--bg-muted)",
        height: "100%",
        minHeight: "0",
      },
    });

    let selectedRow: HTMLElement | null = null;
    let selectedEp: Endpoint | null = null;

    function selectTag(tag: string | null) {
      activeTag = tag;
      renderFilterBar();
      applyFilters();
    }

    function fuzzyMatch(text: string, q: string): boolean {
      if (!q) return true;
      const t = text.toLowerCase();
      const s = q.toLowerCase();
      let i = 0;
      for (const ch of t) {
        if (ch === s[i]) i++;
        if (i === s.length) return true;
      }
      return false;
    }
    function endpointHaystack(ep: Endpoint) {
      return [
        ep.method,
        ep.path,
        ep.summary || "",
        ep.description || "",
        ep.operation_id || "",
        (ep.tags || []).join(" "),
      ].join(" ");
    }

    function applyFilters() {
      const tagPool =
        activeTag === null ? spec.endpoints : grouped.get(activeTag) || [];
      const visible = searchQuery.trim()
        ? tagPool.filter((ep) => fuzzyMatch(endpointHaystack(ep), searchQuery.trim()))
        : tagPool;
      renderEndpoints(visible);

      // Honor a pending endpoint selection from Home search.
      const pending = store.state.pendingSelection;
      if (pending?.endpointKey && pending.tab === "spec") {
        const match = visible.find(
          (ep) => `${ep.method} ${ep.path}` === pending.endpointKey,
        );
        if (match) {
          // Find the row we just rendered for this ep.
          const rows = [...listEl.querySelectorAll(".row")] as HTMLElement[];
          const idx = visible.indexOf(match);
          const rowEl = rows[idx];
          if (rowEl) {
            selectEndpoint(match, rowEl);
            store.set({ pendingSelection: null });
            rowEl.scrollIntoView({ block: "nearest" });
            return;
          }
        }
      }

      if (!selectedEp || !visible.includes(selectedEp)) {
        if (visible.length) {
          const firstRow = listEl.querySelector(".row") as HTMLElement | null;
          firstRow?.click();
        } else {
          detailEl.innerHTML = "";
          detailEl.appendChild(
            h(".muted", { style: { padding: "var(--s-4)" } }, "No endpoints match."),
          );
          selectedEp = null;
        }
      }
    }

    function renderEndpoints(eps: Endpoint[]) {
      listEl.innerHTML = "";
      for (const ep of eps) {
        const rowEl = h(
          ".row",
          {
            style: { cursor: "pointer" },
            onclick: () => selectEndpoint(ep, rowEl),
          },
          h(`span.method.${ep.method}`, ep.method),
          h(
            "div",
            h(".path", ep.path),
            h(".sub", ep.summary || ep.operation_id || ""),
          ),
        );
        listEl.appendChild(rowEl);
        if (selectedEp === ep) {
          rowEl.style.background = "var(--bg-hover, rgba(255,255,255,0.04))";
          selectedRow = rowEl;
        }
      }
      staggerIn(listEl.querySelectorAll(".row"));
    }

    function selectEndpoint(ep: Endpoint, rowEl: HTMLElement) {
      if (selectedRow) selectedRow.style.background = "";
      rowEl.style.background = "var(--bg-hover, rgba(255,255,255,0.04))";
      selectedRow = rowEl;
      selectedEp = ep;
      detailEl.innerHTML = "";
      detailEl.appendChild(renderEndpointDetail(ep));
    }

    selectTag(null);

    return h(
      "div",
      {
        style: {
          display: "flex",
          flexDirection: "column",
          height: "100%",
          minHeight: "0",
        },
      },
      filterBar,
      h(
        "div",
        {
          style: {
            display: "grid",
            gridTemplateColumns: "360px 1fr",
            gap: "var(--s-3)",
            flex: "1 1 0",
            minHeight: "0",
          },
        },
        leftCol,
        detailEl,
      ),
    );
  }

  // ------------------------------------------------------------------ //
  // Tab: Test Cases
  // ------------------------------------------------------------------ //
  function renderCasesTab(): HTMLElement {
    if (store.state.plan) return renderPlanView();

    // Empty state — big GENERATE button.
    const genBtn = h(
      "button.btn.primary",
      {
        style: { fontSize: "14px", padding: "12px 24px" },
        onclick: () => doGenerate(),
      },
      "GENERATE TEST CASES →",
    ) as HTMLButtonElement;

    return h(
      ".welcome-card",
      {
        style: {
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: "var(--s-6)",
          gap: "var(--s-3)",
          minHeight: "400px",
        },
      },
      h("h2", "No test cases yet"),
      h(
        "p.muted",
        { style: { maxWidth: "460px", textAlign: "center", margin: 0 } },
        "Generate a plan from this spec. Happy paths (2xx), sad paths (4xx/5xx), and optional AI-driven scenarios — configurable before generation.",
      ),
      genBtn,
    );
  }

  async function doGenerate() {
    let aiOn = false;
    try {
      const cfg = await getConfig();
      aiOn = cfg.ai_enabled;
    } catch {
      /* proceed without config */
    }
    const choice = await openRegenerateOptions({
      defaults: { include_happy: true, include_sad: true, include_ai: aiOn },
    });
    if (!choice) return;
    startGenerate(choice);
  }

  function startGenerate(choice: RegenerateChoice) {
    const overlay = createProgressOverlay("Generating Test Plan");
    document.body.appendChild(overlay.el);

    const spec = store.state.spec!;
    const ws = generatePlanStreaming(
      spec.raw_spec,
      store.state.specSource,
      (ev) => {
        switch (ev.event) {
          case "step":
            overlay.update(ev.step || "", ev.progress || 0, ev.detail, ev.model);
            break;
          case "complete":
            overlay.done();
            if (ev.plan) {
              store.set({ plan: ev.plan });
              const aiCount = ev.plan.test_cases.filter(
                (tc: { ai_generated?: boolean }) => tc.ai_generated,
              ).length;
              toast(
                "PLAN GENERATED",
                `${ev.plan.test_cases.length} test cases` +
                  (aiCount ? ` (${aiCount} AI-generated)` : "") +
                  (ev.merge ? ` · ${ev.merge.kept} intel preserved` : ""),
                "success",
              );
              setTab("cases");
            }
            break;
          case "error":
            overlay.error(ev.message || "Generation failed");
            toast("GENERATE FAILED", ev.message || "Unknown error", "error");
            break;
        }
      },
      choice,
    );

    overlay.onCancel = () => {
      ws.cancel();
      overlay.el.remove();
      toast("CANCELLED", "Generation cancelled", "default");
    };
  }
}
