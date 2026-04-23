// Plan-view — the test-case editor UI, rendered inside any container.
// Extracted from screens/plan.ts so it can be mounted as the Test Cases tab
// inside the Spec Browser shell. Keeps all the same features:
// enable/disable, search/filter, row click → detail modal, cURL copy,
// regenerate, save, RUN TESTS, Variables (global+local) panel, and a
// "+ Add Test Case" button to create cases manually.

import { aiBadge, aiIcon } from "../ai-icon";
import {
  generatePlanStreaming,
  getConfig,
  savePlan,
} from "../api";
import { copyCurl } from "../curl";
import { h } from "../dom";
import { openRegenerateOptions } from "../modals/regenerate-options";
import { openTestCaseDetail } from "../modals/test-case";
import { openTestConfigModal } from "../modals/test-config";
import { openVariablesModal } from "../modals/variables";
import { createProgressOverlay } from "../progress-overlay";
import { navigate } from "../router";
import { staggerIn } from "../motion";
import { store } from "../state";
import { toast } from "../toast";
import type { TestCase, TestPlan } from "../types";

// Returns a DOM node that renders the plan editor for the currently-loaded
// plan. The caller is responsible for clearing/re-rendering on plan change.
export function renderPlanView(): HTMLElement {
  const state = store.state;
  const plan = state.plan!;

  // Last Regenerate choice, seeded from config.ai_enabled.
  let lastChoice = {
    include_happy: true,
    include_sad: true,
    include_ai: false,
  };
  getConfig()
    .then((cfg) => {
      lastChoice.include_ai = !!cfg.ai_enabled;
    })
    .catch(() => {});

  // --- Regenerate button ---
  const regenBtn = h(
    "button.btn",
    {
      onclick: async () => {
        const choice = await openRegenerateOptions({ defaults: lastChoice });
        if (!choice) return;
        lastChoice = choice;

        (regenBtn as HTMLButtonElement).disabled = true;
        regenBtn.textContent = "Regenerating…";

        const overlay = createProgressOverlay("Regenerating Test Plan");
        document.body.appendChild(overlay.el);

        const spec = store.state.spec!;
        const ws = generatePlanStreaming(
          spec.raw_spec,
          store.state.specSource,
          (ev) => {
            if (ev.event === "step") {
              overlay.update(ev.step || "", ev.progress || 0, ev.detail, ev.model);
            } else if (ev.event === "complete" && ev.plan) {
              overlay.done();
              const newPlan = ev.plan;
              newPlan.auth_type = plan.auth_type;
              newPlan.auth_value = plan.auth_value;
              newPlan.global_headers = plan.global_headers;
              newPlan.global_variables = plan.global_variables;
              store.set({ plan: newPlan });
              plan.test_cases = newPlan.test_cases;
              plan.performance_slas = newPlan.performance_slas;
              refreshStats();
              refreshList();
              const aiCount = newPlan.test_cases.filter((tc: TestCase) => tc.ai_generated).length;
              toast(
                "REGENERATED",
                `${newPlan.test_cases.length} test cases` +
                  (aiCount ? ` · ${aiCount} AI scenarios` : "") +
                  (ev.merge ? ` · ${ev.merge.kept} intel preserved` : ""),
                "success",
              );
              (regenBtn as HTMLButtonElement).disabled = false;
              regenBtn.textContent = "Regenerate";
            } else if (ev.event === "error") {
              overlay.error(ev.message || "Failed");
              toast("REGENERATE FAILED", ev.message || "", "error");
              (regenBtn as HTMLButtonElement).disabled = false;
              regenBtn.textContent = "Regenerate";
            }
          },
          choice,
        );

        overlay.onCancel = () => {
          ws.cancel();
          overlay.el.remove();
          (regenBtn as HTMLButtonElement).disabled = false;
          regenBtn.textContent = "Regenerate";
          toast("CANCELLED", "Keeping current plan", "default");
        };
      },
    },
    "Regenerate",
  );

  // --- Header actions ---
  const header = h(
    ".panel-h",
    h("h2", "Test Cases"),
    h("span.muted.mono", { style: { marginLeft: "var(--s-3)" } }, plan.base_url),
    h("span.flex-1"),
    h("button.btn.sm", { onclick: () => enableAll(true) }, "Enable all"),
    h("button.btn.sm", { onclick: () => enableAll(false) }, "Disable all"),
    h("button.btn.sm", { onclick: () => openVariablesModal() }, "Built-in VARS"),
    h(
      "button.btn",
      { onclick: () => addNewTestCase() },
      "+ Add Test Case",
    ),
    regenBtn,
    h(
      "button.btn",
      {
        onclick: async () => {
          try {
            await savePlan(plan);
            toast("SAVED", "Plan persisted", "success");
          } catch (e) {
            toast("SAVE FAILED", String((e as Error).message), "error");
          }
        },
      },
      "SAVE",
    ),
    h(
      "button.btn.primary",
      {
        onclick: () =>
          openTestConfigModal(() => navigate("execution")),
      },
      "RUN TESTS →",
    ),
  );

  // --- Stats strip ---
  const statsWrap = h(".grid");

  // --- Variables panel (collapsible, global + local is per-case via modal) ---
  if (!plan.global_variables) plan.global_variables = {};
  const varsPanel = renderVariablesPanel(plan);

  // --- Search / filter ---
  let filterText = "";
  const filters = { happy: true, sad: true, ai: true };

  const searchInput = h("input.input", {
    type: "text",
    placeholder: "Search test cases… (method, path, name)",
    oninput: (e: Event) => {
      filterText = (e.target as HTMLInputElement).value.toLowerCase();
      refreshList();
    },
    style: { marginBottom: "var(--s-3)" },
  }) as HTMLInputElement;

  const makeFilterPill = (
    label: string,
    key: keyof typeof filters,
    accent: string,
  ): HTMLButtonElement => {
    const btn = h("button.filter-pill", {
      "data-on": "true",
      "data-accent": accent,
      onclick: () => {
        filters[key] = !filters[key];
        btn.setAttribute("data-on", filters[key] ? "true" : "false");
        refreshList();
      },
    }, label) as HTMLButtonElement;
    return btn;
  };

  const filterBar = h(
    ".filter-bar",
    h(
      "span.muted.mono",
      { style: { fontSize: "11px", marginRight: "var(--s-2)" } },
      "SHOW",
    ),
    makeFilterPill("Happy", "happy", "pass"),
    makeFilterPill("Sad", "sad", "err"),
    makeFilterPill("AI", "ai", "ai"),
  );

  // --- List ---
  const listEl = h(".list");

  function refreshStats() {
    const total = plan.test_cases.length;
    const enabled = plan.test_cases.filter((t) => t.enabled).length;
    const happy = plan.test_cases.filter((t) => t.test_type === "happy").length;
    const sad = total - happy;
    const aiGenerated = plan.test_cases.filter((t) => t.ai_generated).length;
    const aiEnhanced = plan.test_cases.filter((t) => !t.ai_generated && t.ai_fields?.length).length;
    const aiCount = aiGenerated + aiEnhanced;
    statsWrap.innerHTML = "";
    for (const [k, v, cls] of [
      ["Total", total, ""],
      ["Enabled", enabled, "accent"],
      ["Happy", happy, "pass"],
      ["Sad", sad, "err"],
      ["AI", aiCount, "ai"],
    ] as [string, number, string][]) {
      const statEl = h(
        `.stat${cls && cls !== "ai" ? "." + cls : ""}`,
        h(".k", k),
        h(".v", String(v)),
      );
      if (cls === "ai" && v > 0) {
        statEl.style.borderColor = "#a78bfa";
        (statEl.querySelector(".v") as HTMLElement).style.color = "#a78bfa";
      }
      statsWrap.appendChild(statEl);
    }
  }

  function refreshList() {
    listEl.innerHTML = "";
    const filtered = plan.test_cases.filter((tc) => {
      const categoryOn = tc.ai_generated
        ? filters.ai
        : tc.test_type === "happy"
          ? filters.happy
          : filters.sad;
      if (!categoryOn) return false;
      if (!filterText) return true;
      const text = `${tc.method} ${tc.endpoint_path} ${tc.name} ${tc.description} ${tc.ai_category}`.toLowerCase();
      return text.includes(filterText);
    });
    for (const tc of filtered) {
      listEl.appendChild(row(tc));
    }
    if (filtered.length === 0) {
      const msg = filterText
        ? `No cases match "${filterText}"`
        : "No cases match the current filters";
      listEl.appendChild(
        h(".muted.center", { style: { padding: "var(--s-5)" } }, msg),
      );
    }
    staggerIn(listEl.querySelectorAll(".row"));
  }

  function row(tc: TestCase): HTMLElement {
    const toggle = h("input", {
      type: "checkbox",
      checked: tc.enabled,
      onclick: (e: Event) => {
        e.stopPropagation();
        tc.enabled = (e.target as HTMLInputElement).checked;
        rowEl.classList.toggle("disabled", !tc.enabled);
        refreshStats();
      },
    });
    const rowEl = h(
      `.row${tc.enabled ? "" : ".disabled"}`,
      { onclick: () => openDetail(tc), "data-tc-id": tc.id },
      h(".inline", toggle, h(`span.method.${tc.method}`, tc.method)),
      h(
        "div",
        h(".path", tc.name || `${tc.method} ${tc.endpoint_path}`),
        h(".sub", tc.description || tc.endpoint_path),
      ),
      h(
        ".inline",
        h(
          "button.btn.sm.ghost",
          {
            title: "Copy cURL",
            onclick: (e: Event) => {
              e.stopPropagation();
              const specUrl =
                store.state.spec?.servers?.[0]?.url || plan.base_url;
              copyCurl(tc, specUrl, plan.auth_type, plan.auth_value).then(() =>
                toast("COPIED", "cURL copied to clipboard", "success", 1500),
              );
            },
          },
          "⧉",
        ),
        tc.ai_generated
          ? h("span.badge.ai", aiIcon(14), tc.ai_category || "AI")
          : tc.ai_fields?.length
            ? aiBadge(tc.ai_fields.length)
            : (null as unknown as HTMLElement),
        tc.test_type === "sad"
          ? h("span.badge.error", "SAD")
          : h("span.badge.passed", "HAPPY"),
      ),
    );
    return rowEl;
  }

  function enableAll(v: boolean) {
    plan.test_cases.forEach((t) => (t.enabled = v));
    refreshList();
    refreshStats();
  }

  function openDetail(tc: TestCase) {
    openTestCaseDetail(
      tc,
      () => refreshList(),
      plan.base_url,
      plan.auth_type,
      plan.auth_value,
    );
  }

  // "+ Add Test Case" creates a minimal empty happy-path case and opens the
  // detail modal for editing. Picks the first endpoint as a reasonable default.
  function addNewTestCase() {
    const firstEp = store.state.spec?.endpoints?.[0];
    const tc: TestCase = {
      id: Math.random().toString(36).slice(2, 10),
      endpoint_path: firstEp?.path || "/",
      method: (firstEp?.method as string) || "GET",
      name: "New test case",
      description: "",
      enabled: true,
      path_params: {},
      query_params: {},
      headers: {},
      body: null,
      assertions: [{ type: "status_code", expected: 200, description: "" }],
      depends_on: null,
      needs_input: false,
      test_type: "happy",
      ai_fields: [],
      ai_generated: false,
      ai_category: "",
      local_variables: {},
    };
    plan.test_cases.push(tc);
    refreshStats();
    refreshList();
    openDetail(tc);
  }

  refreshStats();
  refreshList();

  // Honor a pending test-case selection (e.g. from Home search).
  const pending = store.state.pendingSelection;
  if (pending?.tab === "cases" && (pending.testCaseId || pending.testCaseName)) {
    const tc = plan.test_cases.find(
      (t) => t.id === pending.testCaseId || t.name === pending.testCaseName,
    );
    if (tc) {
      // Wait for staggerIn to paint, then scroll + highlight.
      setTimeout(() => {
        const rowEl = listEl.querySelector(
          `.row[data-tc-id="${CSS.escape(tc.id)}"]`,
        ) as HTMLElement | null;
        if (rowEl) {
          rowEl.scrollIntoView({ block: "center", behavior: "smooth" });
          rowEl.style.outline = "2px solid var(--primary)";
          setTimeout(() => (rowEl.style.outline = ""), 1800);
        }
        openDetail(tc);
        store.set({ pendingSelection: null });
      }, 50);
    }
  }

  return h(
    ".stack",
    h(".panel", header),
    statsWrap,
    varsPanel,
    h(".panel", h(".panel-h", h("h2", "Test cases")), filterBar, searchInput, listEl),
  );
}

// --- Variables panel (global + pointer to per-case local) ---
function renderVariablesPanel(plan: TestPlan): HTMLElement {
  const globalJson = JSON.stringify(plan.global_variables || {}, null, 2);
  const ta = h("textarea.textarea", {
    style: { minHeight: "120px", fontFamily: "var(--font-mono, monospace)", fontSize: "12px" },
  }, globalJson) as HTMLTextAreaElement;

  const status = h("span.muted.mono", { style: { fontSize: "11px" } }, "");

  const saveInline = h(
    "button.btn.sm.primary",
    {
      onclick: () => {
        try {
          const parsed = JSON.parse(ta.value || "{}");
          if (typeof parsed !== "object" || Array.isArray(parsed) || parsed === null) {
            throw new Error("Must be a JSON object");
          }
          plan.global_variables = parsed as Record<string, unknown>;
          status.textContent = "Saved (in memory — press SAVE on the plan to persist)";
          (status as HTMLElement).style.color = "var(--lime, #4ade80)";
        } catch (e) {
          status.textContent = `Parse error: ${(e as Error).message}`;
          (status as HTMLElement).style.color = "var(--red, #f87171)";
        }
      },
    },
    "Apply",
  );

  const body = h(
    "div",
    h(
      "p.muted",
      { style: { fontSize: "12px", margin: "0 0 var(--s-2) 0" } },
      "Plan-wide variables referenced by ",
      h("span.mono", "{{name}}"),
      " in any field. Per-test-case overrides live in the test case detail modal (Local Variables).",
    ),
    ta,
    h(
      ".inline",
      { style: { marginTop: "var(--s-2)", gap: "var(--s-2)" } },
      saveInline,
      status,
    ),
  );

  // Collapsible wrapper
  let open = false;
  const content = h("div", { style: { display: "none", padding: "var(--s-3)" } }, body);
  const toggle = h(
    ".panel-h",
    {
      style: { cursor: "pointer" },
      onclick: () => {
        open = !open;
        content.style.display = open ? "" : "none";
        caret.textContent = open ? "▾" : "▸";
      },
    },
    h("span.accent"),
    h("h2", "Variables"),
    h("span.muted.mono", { style: { marginLeft: "var(--s-3)", fontSize: "11px" } }, "global — applies to all test cases"),
    h("span.flex-1"),
    // caret text node
  );
  const caret = h("span.mono", { style: { marginLeft: "var(--s-2)" } }, "▸");
  toggle.appendChild(caret);

  return h(".panel", toggle, content);
}
