// Plan editor — list of test cases, enable/disable, open detail,
// edit auth/global headers, save, regenerate, configure and launch execution.

import { aiBadge, aiIcon } from "../ai-icon";
import { generatePlanStreaming, getConfig, listHistory, loadHistoryRun, savePlan } from "../api";
import { openRegenerateOptions } from "../modals/regenerate-options";
import { copyCurl } from "../curl";
import { createProgressOverlay } from "../progress-overlay";
import { h } from "../dom";
import { openTestConfigModal } from "../modals/test-config";
import { openTestCaseDetail } from "../modals/test-case";
import { openVariablesModal } from "../modals/variables";
import { staggerIn, revealUp } from "../motion";
import { navigate } from "../router";
import { store } from "../state";
import { toast } from "../toast";
import type { TestCase } from "../types";

export function mountPlan(container: HTMLElement): () => void {
  const state = store.state;
  if (!state.plan || !state.spec) {
    navigate("welcome");
    return () => {};
  }
  const plan = state.plan;

  // Remember last Regenerate choice (seeded from config.ai_enabled so users
  // who enabled AI previously still get the toggle on by default).
  let lastChoice: { include_happy: boolean; include_sad: boolean; include_ai: boolean } = {
    include_happy: true,
    include_sad: true,
    include_ai: false,
  };
  getConfig().then((cfg) => { lastChoice.include_ai = !!cfg.ai_enabled; }).catch(() => {});

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
        const ws = generatePlanStreaming(spec.raw_spec, store.state.specSource, (ev) => {
          if (ev.event === "step") {
            overlay.update(ev.step || "", ev.progress || 0, ev.detail, ev.model);
          } else if (ev.event === "complete" && ev.plan) {
            overlay.done();
            const newPlan = ev.plan;
            newPlan.auth_type = plan.auth_type;
            newPlan.auth_value = plan.auth_value;
            newPlan.global_headers = plan.global_headers;
            store.set({ plan: newPlan });
            plan.test_cases = newPlan.test_cases;
            plan.performance_slas = newPlan.performance_slas;
            refreshStats();
            refreshList();
            const aiCount = newPlan.test_cases.filter((tc: TestCase) => tc.ai_generated).length;
            toast("REGENERATED",
              `${newPlan.test_cases.length} test cases` +
                (aiCount ? ` · ${aiCount} AI scenarios` : "") +
                (ev.merge ? ` · ${ev.merge.kept} intel preserved` : ""),
              "success");
            (regenBtn as HTMLButtonElement).disabled = false;
            regenBtn.textContent = "Regenerate";
          } else if (ev.event === "error") {
            overlay.error(ev.message || "Failed");
            toast("REGENERATE FAILED", ev.message || "", "error");
            (regenBtn as HTMLButtonElement).disabled = false;
            regenBtn.textContent = "Regenerate";
          }
        }, choice);

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

  // --- Header bar ---
  const header = h(
    ".panel-h",
    h("h2", plan.name),
    h("span.muted.mono", { style: { marginLeft: "var(--s-3)" } }, plan.base_url),
    h("span.flex-1"),
    h("button.btn.sm", { onclick: () => enableAll(true) }, "Enable all"),
    h("button.btn.sm", { onclick: () => enableAll(false) }, "Disable all"),
    h("button.btn.sm", { onclick: () => openVariablesModal() }, "VARS"),
    regenBtn,
    h("button.btn", { onclick: async () => {
      try {
        await savePlan(plan);
        toast("SAVED", "Plan persisted", "success");
      } catch (e) {
        toast("SAVE FAILED", String((e as Error).message), "error");
      }
    }}, "SAVE"),
    h("button.btn.primary", {
      onclick: () => openTestConfigModal(() => navigate("execution")),
    }, "RUN TESTS →"),
  );

  // --- Stats strip ---
  const statsWrap = h(".grid");

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

  const filterBar = h(".filter-bar",
    h("span.muted.mono", { style: { fontSize: "11px", marginRight: "var(--s-2)" } }, "SHOW"),
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
      const statEl = h(`.stat${cls && cls !== "ai" ? "." + cls : ""}`, h(".k", k), h(".v", String(v)));
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
      // Three disjoint categories: AI-generated wins over test_type.
      // A case is shown only if its category's pill is ON.
      const categoryOn = tc.ai_generated
        ? filters.ai
        : tc.test_type === "happy"
          ? filters.happy
          : filters.sad;
      if (!categoryOn) return false;
      // Text search across common fields.
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
      listEl.appendChild(h(".muted.center", { style: { padding: "var(--s-5)" } }, msg));
    }
    staggerIn(listEl.querySelectorAll(".row"));
  }

  function row(tc: TestCase): HTMLElement {
    const toggle = h(
      "input",
      {
        type: "checkbox",
        checked: tc.enabled,
        onclick: (e: Event) => {
          e.stopPropagation();
          tc.enabled = (e.target as HTMLInputElement).checked;
          rowEl.classList.toggle("disabled", !tc.enabled);
          refreshStats();
        },
      },
    );
    const rowEl = h(
      `.row${tc.enabled ? "" : ".disabled"}`,
      { onclick: () => openDetail(tc) },
      h(
        ".inline",
        toggle,
        h(`span.method.${tc.method}`, tc.method),
      ),
      h(
        "div",
        h(".path", tc.name || `${tc.method} ${tc.endpoint_path}`),
        h(".sub", tc.description || tc.endpoint_path),
      ),
      h(
        ".inline",
        h("button.btn.sm.ghost", {
          title: "Copy cURL",
          onclick: (e: Event) => {
            e.stopPropagation();
            const specUrl = store.state.spec?.servers?.[0]?.url || plan.base_url;
            copyCurl(tc, specUrl, plan.auth_type, plan.auth_value)
              .then(() => toast("COPIED", "cURL copied to clipboard", "success", 1500));
          },
        }, "⧉"),
        tc.ai_generated
          ? h("span.badge.ai", aiIcon(14), tc.ai_category || "AI")
          : tc.ai_fields?.length
            ? aiBadge(tc.ai_fields.length)
            : null as unknown as HTMLElement,
        tc.test_type === "sad"
          ? h("span.badge.error", "SAD")
          : h("span.badge.passed", "HAPPY"),
      ),
    );
    return rowEl;
  }

  function enableAll(v: boolean): void {
    plan.test_cases.forEach((t) => (t.enabled = v));
    refreshList();
    refreshStats();
  }

  function openDetail(tc: TestCase): void {
    openTestCaseDetail(
      tc,
      () => refreshList(),
      plan.base_url,
      plan.auth_type,
      plan.auth_value,
    );
  }

  refreshStats();
  refreshList();

  // --- History panel ---
  const historyList = h(".list.bare");
  const historyPanel = h(
    ".panel",
    { style: { display: "none" } },
    h(".panel-h", h("h2", "Recent Runs")),
    historyList,
  );

  const specUrl = store.state.spec?.servers?.[0]?.url || plan.base_url;
  listHistory(plan.spec_title, specUrl, 10).then((runs) => {
    if (!runs.length) return;
    historyPanel.style.display = "";
    for (const r of runs) {
      historyList.appendChild(
        h(".row", {
          onclick: async () => {
            try {
              const report = await loadHistoryRun(plan.spec_title, specUrl, r.filename);
              store.set({ lastReport: report });
              navigate("results");
            } catch (e) {
              toast("LOAD FAILED", String((e as Error).message), "error");
            }
          },
        },
          h(".mono.muted", { style: { fontSize: "11px" } }, r.timestamp?.slice(0, 16).replace("T", " ") || ""),
          h("div",
            h(".path", `${r.passed}/${r.total} passed · ${r.pass_rate.toFixed(0)}%`),
            h(".sub", r.perf_requests ? `perf: ${r.perf_requests} req · p95 ${r.perf_p95_ms.toFixed(0)}ms` : `${r.duration.toFixed(1)}s`),
          ),
          h(`span.badge.${r.failed === 0 && r.errors === 0 ? "passed" : "failed"}`, `${r.duration.toFixed(1)}s`),
        ),
      );
    }
    staggerIn(historyList.querySelectorAll(".row"));
  }).catch(() => {});

  const layout = h(
    ".stack",
    h(".panel", header),
    statsWrap,
    h(".panel", h(".panel-h", h("h2", "Test cases")), filterBar, searchInput, listEl),
    historyPanel,
  );
  container.appendChild(layout);
  revealUp([...layout.children] as Element[], { delay: (_: Element, i: number) => 60 + i * 60 });

  return () => {};
}

