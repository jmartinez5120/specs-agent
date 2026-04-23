// History panel — list of past runs for the current plan/spec.

import { listHistory, loadHistoryRun } from "../api";
import { h } from "../dom";
import { revealUp, staggerIn } from "../motion";
import { navigate } from "../router";
import { store } from "../state";
import { toast } from "../toast";

export function mountHistory(container: HTMLElement): () => void {
  const state = store.state;
  if (!state.plan) {
    navigate("welcome");
    return () => {};
  }
  const plan = state.plan;

  const listEl = h(".list");
  const header = h(
    ".panel-h",
    h("span.accent"),
    h("h2", "History"),
    h("span.muted.mono", { style: { marginLeft: "var(--s-3)" } }, plan.spec_title),
    h("span.flex-1"),
    h("button.btn", { onclick: () => navigate("spec") }, "← BACK"),
    state.lastReport ? h("button.btn.primary", { onclick: () => navigate("spec") }, "CURRENT RUN") : null as unknown as HTMLElement,
  );

  const panel = h(".panel", header, listEl);
  container.appendChild(panel);
  revealUp([panel]);

  listHistory(plan.spec_title, plan.base_url, 50)
    .then((runs) => {
      if (runs.length === 0) {
        listEl.appendChild(
          h(".muted.center", { style: { padding: "var(--s-6)" } }, "No past runs for this plan"),
        );
        return;
      }
      for (const r of runs) {
        const row = h(
          ".row",
          { onclick: async () => {
            try {
              const report = await loadHistoryRun(plan.spec_title, plan.base_url, r.filename);
              store.set({ lastReport: report });
              navigate("results");
            } catch (e) {
              toast("LOAD FAILED", String((e as Error).message), "error");
            }
          }},
          h(".mono.muted", { style: { fontSize: "11px" } }, r.timestamp.slice(0, 19).replace("T", " ")),
          h(
            "div",
            h(".path", `${r.passed}/${r.total} passed · ${r.pass_rate.toFixed(0)}%`),
            h(".sub",
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
    })
    .catch((e) => toast("HISTORY FAILED", String(e.message), "error"));

  return () => {};
}
