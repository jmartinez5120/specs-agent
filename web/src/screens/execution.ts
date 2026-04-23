// Execution screen — live WebSocket stream of functional + perf events.
// anime.js drives the progress bar, counter, and result reveal animations.

import { ExecutionSocket } from "../api";
import { h } from "../dom";
import { numberTo, progressTo, pulseGlow, revealUp, staggerIn } from "../motion";
import { navigate } from "../router";
import { store } from "../state";
import { toast } from "../toast";
import type { ExecEvent, TestResult } from "../types";

export function mountExecution(container: HTMLElement): () => void {
  const state = store.state;
  if (!state.plan) {
    navigate("welcome");
    return () => {};
  }
  const plan = state.plan;
  // Base URL always comes from the spec's servers — the single source of truth
  const specBaseUrl = state.spec?.servers?.[0]?.url || plan.base_url || "";
  const config = { ...state.runConfig, base_url: specBaseUrl };
  const perfEnabled = config.performance?.enabled ?? false;
  const perfDuration = config.performance?.duration_seconds ?? 30;

  // --- UI elements ---
  const progressFill = h(".fill") as HTMLElement;
  const progressWrap = h(".progress", progressFill);

  const phaseTag = h("span.tag", "CONNECTING");
  const completedEl = h(".v", "0");
  const totalEl = h(".v", "0");
  const passEl = h(".v", "0");
  const failEl = h(".v", "0");
  const errEl = h(".v", "0");

  // Performance stats panel (hidden until perf phase starts)
  const tpsEl = h(".v", "—");
  const p95El = h(".v", "—");
  const p50El = h(".v", "—");
  const p99El = h(".v", "—");
  const perfReqsEl = h(".v", "0");
  const perfErrsEl = h(".v", "0");
  const perfElapsedEl = h(".v", "0s");
  const perfTargetEl = h(".v", `${perfDuration}s`);

  const perfPanel = h(
    ".panel",
    { style: { display: "none" } },
    h(".panel-h",
      h("h2", "Performance Testing"),
      h("span.flex-1"),
      h("span.tag.primary", "RUNNING"),
    ),
    h(".progress", { style: { marginBottom: "var(--s-4)" } },
      h(".fill", { id: "perf-progress-fill" }),
    ),
    h(".grid",
      h(".stat.accent", h(".k", "TPS (current)"), tpsEl),
      h(".stat.accent", h(".k", "p50 ms"), p50El),
      h(".stat.accent", h(".k", "p95 ms"), p95El),
      h(".stat.accent", h(".k", "p99 ms"), p99El),
    ),
    h(".grid.mt-4",
      h(".stat", h(".k", "Total Requests"), perfReqsEl),
      h(".stat.err", h(".k", "Errors"), perfErrsEl),
      h(".stat", h(".k", "Elapsed"), perfElapsedEl),
      h(".stat", h(".k", "Target"), perfTargetEl),
    ),
  );

  const resultList = h(".list.bare", { style: { maxHeight: "400px", overflow: "auto" } });

  const cancelBtn = h(
    "button.btn.danger",
    { onclick: () => socket.cancel() },
    "CANCEL",
  ) as HTMLButtonElement;

  const done = () => {
    cancelBtn.textContent = "← RESULTS";
    cancelBtn.classList.remove("danger");
    cancelBtn.classList.add("primary");
    cancelBtn.onclick = () => navigate("results");
    // Stop perf progress animation
    if (perfTimer) clearInterval(perfTimer);
    const perfPhaseTag = perfPanel.querySelector(".tag");
    if (perfPhaseTag) {
      perfPhaseTag.textContent = "COMPLETE";
      perfPhaseTag.className = "tag success";
    }
  };

  const header = h(
    ".panel-h",
    h("h2", "Executing"),
    h("span.muted.mono", { style: { marginLeft: "var(--s-3)" } }, plan.name),
    h("span.flex-1"),
    phaseTag,
  );

  const functionalPanel = h(
    ".panel",
    header,
    progressWrap,
    h(".grid", { style: { marginTop: "var(--s-4)" } },
      h(".stat", h(".k", "Completed"), completedEl),
      h(".stat", h(".k", "Total"), totalEl),
      h(".stat.pass", h(".k", "Passed"), passEl),
      h(".stat.fail", h(".k", "Failed"), failEl),
      h(".stat.err", h(".k", "Errors"), errEl),
    ),
  );

  const layout = h(
    ".stack",
    functionalPanel,
    perfPanel,
    h(".panel",
      h(".panel-h", h("h2", "Live Results"), h("span.flex-1"), cancelBtn),
      resultList,
    ),
  );
  container.appendChild(layout);
  revealUp([...layout.children] as Element[]);

  // --- State ---
  let completed = 0;
  let total = 0;
  let pass = 0;
  let fail = 0;
  let err = 0;
  let perfStartTime = 0;
  let perfTimer: ReturnType<typeof setInterval> | null = null;

  const socket = new ExecutionSocket(handleEvent, () => {});

  function handleEvent(ev: ExecEvent) {
    switch (ev.event) {
      case "phase":
        phaseTag.textContent = ev.phase.toUpperCase();
        if (ev.phase === "functional") {
          phaseTag.className = "tag primary";
        }
        if (ev.phase === "performance") {
          phaseTag.textContent = "PERFORMANCE";
          phaseTag.className = "tag";
          // Show perf panel with animation
          perfPanel.style.display = "";
          revealUp([perfPanel]);
          progressTo(progressFill, 100); // functional done
          // Start elapsed timer
          perfStartTime = Date.now();
          perfTimer = setInterval(() => {
            const elapsed = Math.round((Date.now() - perfStartTime) / 1000);
            perfElapsedEl.textContent = `${elapsed}s`;
            // Update perf progress bar
            const perfFill = document.getElementById("perf-progress-fill");
            if (perfFill) {
              const pct = Math.min(100, (elapsed / perfDuration) * 100);
              perfFill.style.width = `${pct}%`;
              perfFill.style.transition = "width 1s linear";
              perfFill.style.background = "var(--primary)";
            }
          }, 1000);
        }
        if (ev.phase === "complete") done();
        break;

      case "progress":
        completed = ev.completed;
        total = ev.total;
        numberTo(completedEl, parseInt(completedEl.textContent || "0"), completed);
        if (total && totalEl.textContent !== String(total)) totalEl.textContent = String(total);
        progressTo(progressFill, total ? (completed / total) * 100 : 0);
        break;

      case "result":
        addResult(ev.result);
        if (ev.result.status === "passed") {
          pass++;
          numberTo(passEl, pass - 1, pass);
        } else if (ev.result.status === "failed") {
          fail++;
          numberTo(failEl, fail - 1, fail);
        } else if (ev.result.status === "error") {
          err++;
          numberTo(errEl, err - 1, err);
        }
        break;

      case "perf":
        {
          const s = ev.stats as Record<string, number>;
          if (s.window_tps !== undefined) {
            numberTo(tpsEl, parseInt(tpsEl.textContent || "0") || 0, Math.round(s.window_tps));
          }
          if (s.p50_latency !== undefined) {
            numberTo(p50El, parseInt(p50El.textContent || "0") || 0, Math.round(s.p50_latency));
          }
          if (s.p95_latency !== undefined) {
            numberTo(p95El, parseInt(p95El.textContent || "0") || 0, Math.round(s.p95_latency));
          }
          if (s.p99_latency !== undefined) {
            numberTo(p99El, parseInt(p99El.textContent || "0") || 0, Math.round(s.p99_latency));
          }
          if (s.total_requests !== undefined) {
            numberTo(perfReqsEl, parseInt(perfReqsEl.textContent || "0") || 0, s.total_requests);
          }
          if (s.total_errors !== undefined) {
            perfErrsEl.textContent = String(Math.round(s.total_errors));
            if (s.total_errors > 0) {
              (perfErrsEl.closest(".stat") as HTMLElement)?.classList.add("err");
            }
          }
        }
        break;

      case "complete":
        store.set({ lastReport: ev.report });
        progressTo(progressFill, 100);
        phaseTag.textContent = "COMPLETE";
        phaseTag.className = "tag success";
        done();
        toast(
          "RUN COMPLETE",
          `${ev.report.passed_tests}/${ev.report.total_tests} passed · ${ev.report.pass_rate.toFixed(0)}%` +
            (ev.report.performance_results?.length
              ? ` · ${ev.report.performance_results.reduce((a: number, p: { total_requests: number }) => a + p.total_requests, 0)} perf requests`
              : ""),
          "success",
        );
        setTimeout(() => navigate("results"), 1200);
        break;

      case "error":
        toast("EXECUTION ERROR", ev.message, "error");
        break;
    }
  }

  function addResult(r: TestResult) {
    const row = h(
      ".row",
      h(`span.method.${r.method}`, r.method),
      h(
        "div",
        h(".path", r.test_case_name),
        h(".sub", `${r.status_code ?? "-"} · ${Math.round(r.response_time_ms)}ms`),
      ),
      h(`span.badge.${r.status}`, r.status.toUpperCase()),
    );
    resultList.prepend(row);
    staggerIn([row]);
  }

  // Kick off
  socket.start(plan, config);

  return () => {
    socket.close();
    if (perfTimer) clearInterval(perfTimer);
  };
}
