// History-view — rendered inside the Spec Browser's "History Runs" tab.
// Extracted from screens/history.ts. Clicking a row opens a drill-down modal
// that shows Test Cases + Performance sub-sections and flags a drift indicator
// when the run's spec hash differs from the current spec.

import { listHistory, loadHistoryRun } from "../api";
import { h } from "../dom";
import { openModal } from "../modal";
import { revealUp, staggerIn } from "../motion";
import { navigate } from "../router";
import { store } from "../state";
import { toast } from "../toast";
import type { Report, TestResult } from "../types";

export function renderHistoryView(): HTMLElement {
  const state = store.state;
  const plan = state.plan;
  const spec = state.spec!;

  // If there's no plan yet, history is empty by definition — show a hint.
  if (!plan) {
    return h(
      ".panel",
      h(".panel-h", h("span.accent"), h("h2", "History")),
      h(
        ".muted.center",
        { style: { padding: "var(--s-6)" } },
        "Generate a test plan first — history is tracked per plan.",
      ),
    );
  }

  const listEl = h(".list");
  const panel = h(
    ".panel",
    h(
      ".panel-h",
      h("span.accent"),
      h("h2", "History Runs"),
      h(
        "span.muted.mono",
        { style: { marginLeft: "var(--s-3)" } },
        plan.spec_title,
      ),
      h("span.flex-1"),
      state.lastReport
        ? h(
            "button.btn.primary",
            { onclick: () => navigate("results") },
            "CURRENT RUN",
          )
        : (null as unknown as HTMLElement),
    ),
    listEl,
  );

  const specUrl = spec?.servers?.[0]?.url || plan.base_url;

  listHistory(plan.spec_title, specUrl, 50)
    .then((runs) => {
      if (runs.length === 0) {
        listEl.appendChild(
          h(
            ".muted.center",
            { style: { padding: "var(--s-6)" } },
            "No past runs for this plan",
          ),
        );
        return;
      }
      const openRun = async (filename: string) => {
        try {
          const report = await loadHistoryRun(
            plan.spec_title,
            specUrl,
            filename,
          );
          openHistoryDetail(report);
        } catch (e) {
          toast("LOAD FAILED", String((e as Error).message), "error");
        }
      };
      for (const r of runs) {
        const row = h(
          ".row",
          {
            "data-run-filename": r.filename,
            onclick: () => openRun(r.filename),
          },
          h(
            ".mono.muted",
            { style: { fontSize: "11px" } },
            r.timestamp.slice(0, 19).replace("T", " "),
          ),
          h(
            "div",
            h(".path", `${r.passed}/${r.total} passed · ${r.pass_rate.toFixed(0)}%`),
            h(
              ".sub",
              r.perf_requests
                ? `perf: ${r.perf_requests} req · p95 ${r.perf_p95_ms.toFixed(0)}ms · ${r.perf_rps.toFixed(1)} rps`
                : `duration ${r.duration.toFixed(1)}s`,
            ),
          ),
          h(
            `span.badge.${r.failed === 0 && r.errors === 0 ? "passed" : "failed"}`,
            `${r.duration.toFixed(1)}s`,
          ),
        );
        listEl.appendChild(row);
      }
      staggerIn(listEl.querySelectorAll(".row"));

      // Honor a pending run selection from Home search.
      const pending = store.state.pendingSelection;
      if (pending?.tab === "history" && pending.runFilename) {
        const match = runs.find((rr) => rr.filename === pending.runFilename);
        if (match) {
          store.set({ pendingSelection: null });
          setTimeout(() => openRun(match.filename), 80);
        }
      }
    })
    .catch((e) => toast("HISTORY FAILED", String(e.message), "error"));

  revealUp([panel]);
  return panel;
}

// --- Drill-down modal: Test Cases + Performance sub-tabs, spec-drift badge ---
function openHistoryDetail(report: Report): void {
  const currentSpec = store.state.spec;
  // Best-effort spec-drift: compare spec_title + a rough hash of endpoints.
  // The backend doesn't currently surface a run-level spec hash, so we fall
  // back to comparing spec_title. (See "Deferred" in the report.)
  const driftLikely =
    !!currentSpec && report.spec_title && currentSpec.title !== report.spec_title;

  let activeTab: "cases" | "perf" = "cases";
  const tabBar = h(".inline", { style: { gap: "var(--s-2)", marginBottom: "var(--s-3)" } });
  const tabContent = h("div");

  const hasPerf = (report.performance_results?.length || 0) > 0;

  function renderCasesList(): HTMLElement {
    const list = h(".list");
    for (const r of report.functional_results) {
      list.appendChild(
        h(
          ".row",
          { onclick: () => openResultDetail(r) },
          h(`span.method.${r.method}`, r.method),
          h(
            "div",
            h(".path", r.test_case_name),
            h(
              ".sub",
              `${r.status_code ?? "-"} · ${Math.round(r.response_time_ms)}ms`,
              r.error_message ? ` · ${r.error_message.slice(0, 80)}` : "",
            ),
          ),
          h(`span.badge.${r.status}`, r.status.toUpperCase()),
        ),
      );
    }
    if (report.functional_results.length === 0) {
      list.appendChild(
        h(".muted.center", { style: { padding: "var(--s-5)" } }, "No functional results"),
      );
    }
    return list;
  }

  function renderPerfList(): HTMLElement {
    const list = h(".list");
    for (const pm of report.performance_results) {
      list.appendChild(
        h(
          ".row",
          { style: { cursor: "default" } },
          h(`span.method.${pm.method}`, pm.method),
          h(
            "div",
            h(".path", pm.endpoint),
            h(
              ".sub",
              `${pm.total_requests} req · p95 ${pm.p95_latency_ms.toFixed(0)}ms · p99 ${pm.p99_latency_ms.toFixed(0)}ms · ${pm.requests_per_second.toFixed(1)} rps · ${pm.error_rate_pct.toFixed(1)}% err`,
            ),
          ),
          pm.sla_p95_ms != null
            ? h(
                "span.badge." + (pm.p95_latency_ms <= pm.sla_p95_ms ? "passed" : "failed"),
                pm.p95_latency_ms <= pm.sla_p95_ms ? "SLA OK" : "SLA BREACH",
              )
            : (null as unknown as HTMLElement),
        ),
      );
    }
    return list;
  }

  function renderTabs() {
    tabBar.innerHTML = "";
    const mkBtn = (key: "cases" | "perf", label: string) =>
      h(
        `button.btn.sm${activeTab === key ? ".primary" : ""}`,
        {
          onclick: () => {
            activeTab = key;
            renderTabs();
          },
        },
        label,
      );
    tabBar.appendChild(mkBtn("cases", `TEST CASES (${report.total_tests})`));
    if (hasPerf) {
      tabBar.appendChild(mkBtn("perf", `PERFORMANCE (${report.performance_results.length})`));
    }
    tabContent.innerHTML = "";
    tabContent.appendChild(activeTab === "cases" ? renderCasesList() : renderPerfList());
  }
  renderTabs();

  const summary = h(
    ".grid",
    { style: { marginBottom: "var(--s-3)" } },
    h(".stat", h(".k", "Started"), h(".v", report.started_at?.slice(0, 19).replace("T", " ") || "—")),
    h(".stat.pass", h(".k", "Passed"), h(".v", String(report.passed_tests))),
    h(".stat.fail", h(".k", "Failed"), h(".v", String(report.failed_tests))),
    h(".stat.err", h(".k", "Errors"), h(".v", String(report.error_tests))),
    h(".stat.accent", h(".k", "Pass rate"), h(".v", `${report.pass_rate.toFixed(0)}%`)),
    h(".stat", h(".k", "Duration"), h(".v", `${report.duration_seconds.toFixed(1)}s`)),
  );

  const driftBadge = driftLikely
    ? h(
        ".field",
        { style: { marginBottom: "var(--s-3)" } },
        h(
          "span.badge.failed",
          { style: { marginRight: "var(--s-2)" } },
          "SPEC DRIFTED",
        ),
        h(
          "span.muted",
          { style: { fontSize: "12px" } },
          `This run was executed against "${report.spec_title}" — current spec is "${currentSpec?.title || "unknown"}".`,
        ),
      )
    : (null as unknown as HTMLElement);

  const specRow = h(
    "p.muted",
    { style: { fontSize: "12px", margin: "0 0 var(--s-3) 0" } },
    "Spec used: ",
    h("span.mono", report.spec_title || "—"),
    "  ·  Base URL: ",
    h("span.mono", report.base_url || "—"),
  );

  const body = h("div", specRow, driftBadge, summary, tabBar, tabContent);
  openModal({ title: `Run — ${report.plan_name}`, body, wide: true });
}

function openResultDetail(r: TestResult): void {
  const preStyle = {
    maxHeight: "220px",
    overflow: "auto",
    background: "var(--bg-muted)",
    padding: "var(--s-3)",
    borderRadius: "var(--r-2)",
    fontSize: "12px",
    whiteSpace: "pre-wrap",
    wordBreak: "break-all",
  };
  const sections: (HTMLElement | null)[] = [
    h(
      ".field",
      h("label.label", "Status"),
      h(
        ".inline",
        h(`span.badge.${r.status}`, r.status.toUpperCase()),
        h(
          "span.mono",
          { style: { marginLeft: "var(--s-3)" } },
          `${r.status_code ?? "-"} · ${Math.round(r.response_time_ms)}ms`,
        ),
      ),
    ),
    r.error_message
      ? h(
          ".field",
          h("label.label", "Error"),
          h("pre.mono", { style: preStyle }, r.error_message),
        )
      : null,
    r.response_body !== undefined && r.response_body !== null
      ? h(
          ".field",
          h("label.label", "Response Body"),
          h(
            "pre.mono",
            { style: preStyle },
            typeof r.response_body === "string"
              ? r.response_body
              : JSON.stringify(r.response_body, null, 2),
          ),
        )
      : null,
  ];
  openModal({
    title: r.test_case_name,
    body: h("div", ...(sections.filter(Boolean) as HTMLElement[])),
    wide: true,
  });
}
