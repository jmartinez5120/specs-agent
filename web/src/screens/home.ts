// Home screen — search-first landing. Backed by the server-side
// Elasticsearch `/search` endpoint: every keystroke (debounced) fires a
// `POST /api/search` and renders the grouped, highlighted results.
//
// Results come back with ES highlights already wrapped in `<mark>` tags.
// We render `title` / `subtitle` via innerHTML — SAFE because the server
// HTML-escapes every user-supplied spec string before indexing, so the
// only unescaped markup ES can introduce is the `<mark>` wrapper itself.
// See src/specs_agent/search/converters.py (XSS contract) and
// src/specs_agent/search/service.py (highlight setup).

import {
  listSavedSpecs,
  loadSavedSpec,
  loadSpec,
  reindexSearch,
  searchSpecs,
} from "../api";
import { h } from "../dom";
import { openModal } from "../modal";
import { revealUp } from "../motion";
import { navigate } from "../router";
import { store } from "../state";
import { toast } from "../toast";
import { renderEndpointDetail } from "../endpoint-detail";
import type { Endpoint, LoadSpecResponse } from "../types";
import type { SearchHit, SearchKind, SearchResult } from "../api";

// Kinds exposed in the Home search dropdown. Test cases + runs are
// intentionally excluded — noisy for the "find a spec/endpoint" use case.
const SEARCH_KINDS: SearchKind[] = ["spec", "endpoint"];
const KIND_ORDER: SearchKind[] = ["spec", "endpoint", "test_case", "run"];
const KIND_LABEL: Record<SearchKind, string> = {
  spec: "Specs",
  endpoint: "Endpoints",
  test_case: "Test Cases",
  run: "Runs",
};
const KIND_BADGE: Record<SearchKind, string> = {
  spec: "SPEC",
  endpoint: "EP",
  test_case: "TC",
  run: "RUN",
};

// Cap per-group rendering. The backend returns up to `limit` total hits;
// we take top N per kind for display and show an "N of M" overflow label.
const TOP_N_PER_KIND = 5;

// Debounce between keystrokes and search dispatch. Balances perceived
// responsiveness against server load.
const DEBOUNCE_MS = 120;

export function mountHome(container: HTMLElement): () => void {
  // ---------- Status pill ---------- //
  const statusPill = h(
    ".status-pill",
    {
      style: {
        display: "inline-flex",
        alignItems: "center",
        gap: "var(--s-2)",
        padding: "6px 12px",
        borderRadius: "999px",
        border: "1px solid var(--border)",
        fontSize: "12px",
        fontFamily: "var(--font-mono, monospace)",
      },
    },
    h("span.dot", {
      style: {
        width: "8px",
        height: "8px",
        borderRadius: "50%",
        background: "var(--muted)",
      },
    }),
    h("span", { id: "home-status-label" }, "checking…"),
  );

  // ---------- Search input ---------- //
  const input = h("input.input", {
    type: "text",
    placeholder: "Search specs, endpoints, test cases, runs…",
    autofocus: true,
    style: {
      fontSize: "15px",
      padding: "14px 18px",
      width: "100%",
    },
  }) as HTMLInputElement;

  const reindexBtn = h(
    "button.btn.sm.ghost",
    {
      onclick: async () => {
        (reindexBtn as HTMLButtonElement).disabled = true;
        searchMeta.textContent = "re-indexing…";
        try {
          const res = await reindexSearch();
          searchMeta.textContent = `re-indexed ${res.reindexed} docs`;
          // If the input holds a query, re-run it against the fresh index.
          if (input.value.trim()) runSearch(input.value.trim());
        } catch (e) {
          searchMeta.textContent = "re-index failed";
          toast("SEARCH", (e as Error).message, "error");
        } finally {
          (reindexBtn as HTMLButtonElement).disabled = false;
        }
      },
      style: { fontSize: "11px" },
    },
    "Re-index",
  );

  const searchMeta = h("span.muted.mono", { style: { fontSize: "11px" } }, "");

  const importToggleBtn = h(
    "button.btn.sm.primary",
    {
      onclick: () => openImportModal(),
      style: { fontSize: "11px" },
    },
    "+ Import spec",
  ) as HTMLButtonElement;

  const searchBar = h(
    ".card",
    { style: { padding: "var(--s-4)", marginTop: "var(--s-4)" } },
    input,
    h(
      "div",
      {
        style: {
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginTop: "var(--s-2)",
          gap: "var(--s-3)",
        },
      },
      h("span.muted", { style: { fontSize: "12px" } },
        "Type to search · ↑↓ navigate · Enter to open"),
      h("div", { style: { display: "flex", gap: "var(--s-2)", alignItems: "center" } },
        searchMeta, reindexBtn, importToggleBtn),
    ),
  );

  function openImportModal(): void {
    const modalInput = h("input.input", {
      type: "text",
      placeholder: "https://api.example.com/openapi.json  or  /path/to/spec.yaml",
      autofocus: true,
      style: { width: "100%" },
    }) as HTMLInputElement;

    const engage = h(
      "button.btn.primary",
      { onclick: () => submit() },
      "ENGAGE →",
    ) as HTMLButtonElement;

    const cancel = h(
      "button.btn.ghost",
      { onclick: () => close() },
      "Cancel",
    );

    const body = h(
      "div",
      { style: { minWidth: "460px" } },
      h(".label", { style: { marginBottom: "var(--s-2)" } },
        "OpenAPI spec source"),
      modalInput,
      h(".muted", { style: { fontSize: "12px", marginTop: "var(--s-2)" } },
        "↵  URL or file path  ·  saved automatically after a successful scan"),
    );

    modalInput.addEventListener("keydown", (e) => {
      if ((e as KeyboardEvent).key === "Enter") submit();
    });

    async function submit(): Promise<void> {
      const source = modalInput.value.trim();
      if (!source) {
        toast("IMPORT", "Enter a spec URL or file path", "error");
        return;
      }
      engage.disabled = true;
      engage.textContent = "SCANNING…";
      try {
        // Preview-only load — does NOT persist to storage.
        const res = await loadSpec(source, { save: false });
        close();
        openScanPreview(res, source);
      } catch (e) {
        toast("IMPORT FAILED", (e as Error).message, "error");
        engage.disabled = false;
        engage.textContent = "ENGAGE →";
      }
    }

    const close = openModal({
      title: "Import new OpenAPI spec",
      body,
      actions: [cancel, engage],
    });

    setTimeout(() => modalInput.focus(), 0);
  }

  // Two-step import: preview the loaded spec (parse-only, not persisted),
  // then commit on user confirmation by re-loading with save=true.
  function openScanPreview(res: LoadSpecResponse, source: string): void {
    const spec = res.spec;
    const tags = [...new Set(
      spec.endpoints.flatMap((e) => e.tags?.length ? e.tags : ["default"]),
    )];
    const methods = spec.endpoints.reduce((acc, e) => {
      acc[e.method] = (acc[e.method] || 0) + 1;
      return acc;
    }, {} as Record<string, number>);

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

    let selectedRow: HTMLElement | null = null;
    spec.endpoints.forEach((ep, i) => {
      const row = h(".row", {
        style: { cursor: "pointer" },
        onclick: () => {
          if (selectedRow) selectedRow.style.background = "";
          row.style.background = "var(--bg-hover, rgba(255,255,255,0.04))";
          selectedRow = row;
          detailPane.innerHTML = "";
          detailPane.appendChild(renderEndpointDetail(ep as Endpoint));
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
      if (i === 0) queueMicrotask(() => row.click());
    });

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
              h("label.label", { style: { color: "var(--warning)" } },
                `Warnings (${res.warnings.length})`),
              ...res.warnings.map((w) =>
                h(".sub", { style: { color: "var(--warning)" } }, w)),
            )
          : null as unknown as HTMLElement,
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
      onclick: async () => {
        (proceed as HTMLButtonElement).disabled = true;
        proceed.textContent = "IMPORTING…";
        try {
          // Commit: re-load with save=true to actually persist.
          const committed = await loadSpec(source, { save: true });
          store.set({ spec: committed.spec, specSource: source });
          toast(
            "IMPORTED",
            `${committed.spec.title} · ${committed.spec.endpoints.length} endpoints`,
            "success",
          );
          close();
          navigate("spec");
        } catch (e) {
          toast("IMPORT FAILED", (e as Error).message, "error");
          (proceed as HTMLButtonElement).disabled = false;
          proceed.textContent = `IMPORT → ${spec.endpoints.length} endpoints`;
        }
      },
    }, `IMPORT → ${spec.endpoints.length} endpoints`) as HTMLButtonElement;

    const cancel = h("button.btn.ghost", {
      onclick: () => close(),
    }, "Cancel");

    const close = openModal({
      title: `Preview — ${spec.title}`,
      body,
      actions: [cancel, proceed],
    });
  }

  // ---------- Search dropdown (floats under the input) ---------- //
  // Only visible while there's an active query; never displaces the content
  // below. The Recent Specs section stays in normal flow.
  const dropdownEl = h(".search-dropdown", {
    style: {
      position: "absolute",
      top: "calc(100% + 6px)",
      left: "0",
      right: "0",
      zIndex: "30",
      display: "none",
      flexDirection: "column",
      gap: "var(--s-3)",
      padding: "var(--s-4)",
      background: "var(--bg-raised)",
      border: "1px solid var(--border-strong)",
      borderRadius: "var(--r-3)",
      maxHeight: "60vh",
      overflowY: "auto",
      boxShadow: "var(--shadow-lg)",
    },
  });

  // Wrap the search card in a relative container so the dropdown can
  // position itself against it.
  const searchWrap = h("div", { style: { position: "relative" } }, searchBar, dropdownEl);

  // ---------- Recent specs (always in flow, below the search) ---------- //
  const recentEl = h("div", {
    style: {
      marginTop: "var(--s-7)",
      display: "flex",
      flexDirection: "column",
      gap: "var(--s-3)",
    },
  });

  // ---------- Hero ---------- //
  const hero = h(
    "div",
    { style: { textAlign: "center", maxWidth: "720px", margin: "0 auto" } },
    h("h1.logo", { style: { fontSize: "32px", margin: "0" } }, "specs-agent"),
    h(
      ".tag-line",
      { style: { marginTop: "var(--s-2)" } },
      "OpenAPI-driven functional + performance test runner.",
    ),
    h("div", { style: { marginTop: "var(--s-3)" } }, statusPill),
  );

  const card = h(
    "div",
    { style: { width: "100%", maxWidth: "820px", margin: "0 auto", padding: "var(--s-5)" } },
    hero,
    searchWrap,
    recentEl,
  );

  const screen = h(".welcome", card);
  container.appendChild(screen);

  revealUp(
    [screen.querySelector(".logo"), screen.querySelector(".tag-line"), statusPill, searchBar]
      .filter(Boolean) as Element[],
    { delay: (_: Element, i: number) => 40 + i * 70 },
  );

  // ---------- Backend status ---------- //
  const syncStatus = (online: boolean) => {
    const label = screen.querySelector("#home-status-label");
    const dot = statusPill.querySelector(".dot") as HTMLElement | null;
    if (label) label.textContent = online ? "backend online" : "backend offline";
    if (dot) dot.style.background = online
      ? "var(--lime, #4ade80)"
      : "var(--red, #f87171)";
  };
  syncStatus(store.state.backendOnline);
  const sub = store.subscribe((s) => syncStatus(s.backendOnline));

  // ---------- Keyboard nav state ---------- //
  let selectedIdx = 0;
  let activationOrder: SearchHit[] = [];
  // Track the latest in-flight query so late responses don't clobber
  // fresh ones. If a user types "p" then "pe" quickly, the "p" response
  // might arrive after the "pe" response — we discard the stale one.
  let requestSeq = 0;

  // ---------- Recent specs (always in flow, below the search) ---------- //
  async function renderRecent(): Promise<void> {
    // Clear whatever was there (initial render or re-render after edits).
    recentEl.innerHTML = "";
    // Hide any stale dropdown and reset keyboard-nav state.
    hideDropdown();

    let recent: { id: string; title: string; source: string; source_type: string; saved_at: string }[] = [];
    try {
      recent = await listSavedSpecs(5);
    } catch {
      /* ignore */
    }

    const header = h(".muted", { style: { fontSize: "12px", textTransform: "uppercase", letterSpacing: "0.08em" } }, "Recent specs");
    recentEl.appendChild(header);

    if (!recent.length) {
      recentEl.appendChild(h(".muted", { style: { padding: "var(--s-3)" } }, "No saved specs yet. Import one from Spec Browser."));
    } else {
      for (const s of recent) {
        const row = h(
          ".row",
          {
            style: { cursor: "pointer" },
            onclick: () => openSavedSpec(s.source, s.title),
          },
          h("span.tag", s.source_type === "url" ? "URL" : "FILE"),
          h("div",
            h(".path", s.title || s.source),
            h(".sub", s.source),
          ),
        );
        recentEl.appendChild(row);
      }
    }

    recentEl.appendChild(
      h("div", { style: { marginTop: "var(--s-3)", textAlign: "center" } },
        h("button.btn.primary", { onclick: () => navigate("spec") }, "Open Spec Browser →"),
      ),
    );

    // Reveal the recent-specs children top-to-bottom once the data is in.
    // Continues the stagger started by the hero/search animation above so
    // the whole page reads as a single flowing top→bottom cascade.
    revealUp(Array.from(recentEl.children) as Element[], {
      delay: (_: Element, i: number) => 360 + i * 70,
    });
  }

  function hideDropdown(): void {
    dropdownEl.style.display = "none";
    dropdownEl.innerHTML = "";
    activationOrder = [];
    selectedIdx = 0;
  }
  function showDropdown(): void {
    dropdownEl.style.display = "flex";
    // Cap height so the dropdown never runs past the viewport bottom.
    // Leaves a 16px breathing gap below the panel.
    const searchRect = searchBar.getBoundingClientRect();
    const available = window.innerHeight - searchRect.bottom - 28;
    const cap = Math.max(180, Math.min(available, Math.floor(window.innerHeight * 0.7)));
    dropdownEl.style.maxHeight = `${cap}px`;
  }

  // Recompute the height cap on resize so the dropdown stays bounded.
  const onResize = () => {
    if (dropdownEl.style.display === "flex") showDropdown();
  };
  window.addEventListener("resize", onResize);

  // ---------- Search ---------- //
  async function runSearch(q: string): Promise<void> {
    const mySeq = ++requestSeq;
    searchMeta.textContent = "searching…";

    let result: SearchResult;
    try {
      // Ask for a generous total — we still slice per-kind client-side.
      // `TOP_N_PER_KIND * kinds.length * 2` gives us headroom to show
      // meaningful overflow counts.
      result = await searchSpecs(q, SEARCH_KINDS, TOP_N_PER_KIND * SEARCH_KINDS.length * 2);
    } catch (e) {
      if (mySeq !== requestSeq) return; // stale
      dropdownEl.innerHTML = "";
      showDropdown();
      const msg = (e as Error).message || "Search failed";
      // A 503 here means the backend is running in file-storage mode.
      // Show an actionable error instead of the generic toast.
      dropdownEl.appendChild(h(".muted", {
        style: { padding: "var(--s-3)", textAlign: "center" },
      }, `Search unavailable: ${msg}`));
      searchMeta.textContent = "error";
      activationOrder = [];
      return;
    }

    if (mySeq !== requestSeq) return; // a newer query has arrived

    searchMeta.textContent = `${result.total} match${result.total === 1 ? "" : "es"}`;

    if (!result.total) {
      dropdownEl.innerHTML = "";
      showDropdown();
      dropdownEl.appendChild(h(".muted", { style: { padding: "var(--s-3)", textAlign: "center" } },
        "No matches — try different words."));
      activationOrder = [];
      return;
    }

    dropdownEl.innerHTML = "";
    showDropdown();
    activationOrder = [];

    for (const kind of KIND_ORDER) {
      const hits = result.groups[kind] ?? [];
      if (!hits.length) continue;
      const section = h(
        "div",
        h(
          "div",
          {
            style: {
              display: "flex",
              justifyContent: "space-between",
              fontSize: "12px",
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              marginBottom: "var(--s-1)",
            },
          },
          h("span.muted", `${KIND_LABEL[kind]} · ${hits.length}`),
          hits.length > TOP_N_PER_KIND
            ? h("span.muted", `showing ${TOP_N_PER_KIND} of ${hits.length}`)
            : (null as unknown as HTMLElement),
        ),
      );
      for (const hit of hits.slice(0, TOP_N_PER_KIND)) {
        const idx = activationOrder.length;
        activationOrder.push(hit);
        section.appendChild(resultRow(hit, idx));
      }
      dropdownEl.appendChild(section);
    }

    selectedIdx = 0;
    updateSelection();
  }

  function resultRow(hit: SearchHit, idx: number): HTMLElement {
    // `title` / `subtitle` carry `<mark>...</mark>` wrappers from ES. We
    // render via innerHTML — safe per the XSS contract at the top of this
    // file (backend escapes before indexing, only ES-added markup is <mark>).
    const meta = (hit.meta ?? {}) as Record<string, unknown>;

    // Left badge: method pill for endpoints, plain kind tag otherwise.
    let badge: HTMLElement;
    if (hit.kind === "endpoint" && typeof meta.method === "string") {
      const method = String(meta.method).toUpperCase();
      badge = h(`span.method.${method}`, method);
    } else {
      badge = h(`span.kind-tag.kind-${hit.kind}`, KIND_BADGE[hit.kind]);
    }

    // For endpoints, prefer the raw path (with highlights from the title).
    // The backend composes title as "GET /path" — strip the leading METHOD
    // so the row shows just the path, matching the method-pill layout.
    let titleHtml = hit.title || "";
    if (hit.kind === "endpoint" && typeof meta.method === "string") {
      const method = String(meta.method).toUpperCase();
      const prefix = `${method} `;
      if (titleHtml.startsWith(prefix)) titleHtml = titleHtml.slice(prefix.length);
    }

    const titleEl = h(".path");
    titleEl.innerHTML = titleHtml;
    const subEl = h(".sub");
    subEl.innerHTML = hit.subtitle || "";

    const row = h(
      ".row",
      {
        style: { cursor: "pointer" },
        "data-idx": String(idx),
        onclick: () => activate(hit),
        onmouseenter: () => {
          selectedIdx = idx;
          updateSelection();
        },
      },
      badge,
      h("div", titleEl, subEl),
    );
    return row;
  }

  function updateSelection(): void {
    const rows = dropdownEl.querySelectorAll<HTMLElement>(".row[data-idx]");
    rows.forEach((r) => {
      const idx = Number(r.getAttribute("data-idx"));
      r.style.background = idx === selectedIdx ? "var(--bg-hover, rgba(255,255,255,0.06))" : "";
    });
  }

  // ---------- Activation ---------- //
  async function activate(hit: SearchHit): Promise<void> {
    const meta = (hit.meta || {}) as Record<string, unknown>;
    // Spec docs have `source` directly on their meta. For endpoint /
    // test_case / run docs, we look up the owning spec via spec_id.
    let specSource = String(meta.source || "");
    if (!specSource && hit.spec_id) {
      try {
        const saved = await loadSavedSpec(hit.spec_id);
        specSource = String((saved as Record<string, unknown>)?.source || "");
      } catch {
        /* ignore — will toast below */
      }
    }

    // Stash a hint for the Spec Browser to pick up on mount.
    sessionStorage.setItem("spec-browser-hint", JSON.stringify({
      kind: hit.kind,
      spec_id: hit.spec_id,
      meta: meta,
    }));

    if (!specSource) {
      toast("OPEN FAILED", "Could not resolve spec source", "error");
      return;
    }
    // Strip mark tags from the title for the toast — plain text only.
    const label = stripMark(hit.title) || String(meta.spec_title || "");
    try {
      const res = await loadSpec(specSource);
      store.set({ spec: res.spec, specSource });
      toast("OPENING", label, "default");
      navigate("spec");
    } catch (e) {
      toast("LOAD FAILED", (e as Error).message, "error");
    }
  }

  function stripMark(s: string): string {
    return s.replace(/<\/?mark>/g, "");
  }

  async function openSavedSpec(source: string, title: string): Promise<void> {
    try {
      const res = await loadSpec(source);
      store.set({ spec: res.spec, specSource: source });
      toast("OPENING", title, "default");
      navigate("spec");
    } catch (e) {
      toast("LOAD FAILED", (e as Error).message, "error");
    }
  }

  // ---------- Input handling ---------- //
  let debounceTimer: number | undefined;
  input.addEventListener("input", () => {
    const q = input.value.trim();
    window.clearTimeout(debounceTimer);
    debounceTimer = window.setTimeout(() => {
      if (!q) hideDropdown();
      else runSearch(q);
    }, DEBOUNCE_MS);
  });

  // Dismiss dropdown on Escape or when clicking outside the search wrap.
  input.addEventListener("keydown", (e) => {
    if ((e as KeyboardEvent).key === "Escape") {
      input.value = "";
      hideDropdown();
    }
  });
  document.addEventListener("mousedown", (e) => {
    if (!searchWrap.contains(e.target as Node)) hideDropdown();
  });

  input.addEventListener("keydown", (e) => {
    const key = (e as KeyboardEvent).key;
    if (!activationOrder.length) return;
    if (key === "ArrowDown") {
      e.preventDefault();
      selectedIdx = Math.min(activationOrder.length - 1, selectedIdx + 1);
      updateSelection();
    } else if (key === "ArrowUp") {
      e.preventDefault();
      selectedIdx = Math.max(0, selectedIdx - 1);
      updateSelection();
    } else if (key === "Enter") {
      e.preventDefault();
      const hit = activationOrder[selectedIdx];
      if (hit) activate(hit);
    }
  });

  // ---------- Boot ---------- //
  renderRecent();

  return () => {
    sub();
    window.clearTimeout(debounceTimer);
    window.removeEventListener("resize", onResize);
  };
}
