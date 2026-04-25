// Results screen — summary cards + drill-down modal for each result.

import { copyCurl } from "../curl";
import { renderReportHtml } from "../api";
import { h } from "../dom";
import { openModal } from "../modal";
import { revealUp, staggerIn } from "../motion";
import { navigate } from "../router";
import { store } from "../state";
import { toast } from "../toast";
import type { TestResult } from "../types";

export function mountResults(container: HTMLElement): () => void {
  const state = store.state;
  if (!state.lastReport) {
    navigate("welcome");
    return () => {};
  }
  const report = state.lastReport;

  const header = h(
    ".panel-h",
    h("span.accent"),
    h("h2", "Results"),
    h("span.muted.mono", { style: { marginLeft: "var(--s-3)" } }, report.plan_name),
    h("span.flex-1"),
    h("button.btn", { onclick: () => navigate("spec") }, "HISTORY"),
    h("button.btn", { onclick: () => openReport() }, "REPORT"),
    h("button.btn.primary", { onclick: () => navigate("spec") }, "← BACK"),
  );

  const funcStats = h(
    ".grid",
    h(".stat", h(".k", "Total"), h(".v", String(report.total_tests))),
    h(".stat.pass", h(".k", "Passed"), h(".v", String(report.passed_tests))),
    h(".stat.fail", h(".k", "Failed"), h(".v", String(report.failed_tests))),
    h(".stat.err", h(".k", "Errors"), h(".v", String(report.error_tests))),
    h(".stat.accent", h(".k", "Pass rate"), h(".v", `${report.pass_rate.toFixed(0)}%`)),
    h(".stat", h(".k", "Duration"), h(".v", `${report.duration_seconds.toFixed(1)}s`)),
  );

  const funcOverview = h(
    ".panel",
    h(".panel-h", h("span.accent"), h("h2", "Quality overview")),
    funcStats,
  );

  let perfOverview: HTMLElement | null = null;
  if (report.performance_results.length) {
    const pr = report.performance_results;
    const totalReqs = pr.reduce((s, pm) => s + pm.total_requests, 0);
    const totalErrs = pr.reduce((s, pm) => s + Math.round(pm.total_requests * pm.error_rate_pct / 100), 0);
    const avgTps = pr.reduce((s, pm) => s + pm.requests_per_second, 0);
    const peakTps = pr.reduce((m, pm) => Math.max(m, pm.peak_tps || pm.requests_per_second), 0);
    const avgP95 = pr.reduce((s, pm) => s + pm.p95_latency_ms, 0) / pr.length;
    const avgP99 = pr.reduce((s, pm) => s + pm.p99_latency_ms, 0) / pr.length;
    const slaEndpoints = pr.filter((pm) => pm.sla_p95_ms != null || pm.sla_p99_ms != null);
    const slaBreaches = slaEndpoints.filter((pm) =>
      (pm.sla_p95_ms != null && pm.p95_latency_ms > pm.sla_p95_ms) ||
      (pm.sla_p99_ms != null && pm.p99_latency_ms > pm.sla_p99_ms),
    );

    const perfStats = h(
      ".grid",
      h(".stat", h(".k", "Endpoints"), h(".v", String(pr.length))),
      h(".stat", h(".k", "Requests"), h(".v", String(totalReqs))),
      h(".stat" + (totalErrs > 0 ? ".fail" : ""), h(".k", "Errors"), h(".v", String(totalErrs))),
      h(".stat.accent", h(".k", "Avg TPS"), h(".v", avgTps.toFixed(1))),
      h(".stat", h(".k", "Peak TPS"), h(".v", peakTps.toFixed(1))),
      h(".stat", h(".k", "Avg p95"), h(".v", `${avgP95.toFixed(0)}ms`)),
      h(".stat", h(".k", "Avg p99"), h(".v", `${avgP99.toFixed(0)}ms`)),
      slaEndpoints.length
        ? h(
            ".stat" + (slaBreaches.length ? ".fail" : ".pass"),
            h(".k", "SLA"),
            h(".v", slaBreaches.length ? `${slaBreaches.length} BREACH` : "OK"),
          )
        : (null as unknown as HTMLElement),
    );

    perfOverview = h(
      ".panel",
      h(".panel-h", h("span.accent"), h("h2", "Performance overview")),
      perfStats,
    );
  }

  const listEl = h(".list");
  for (const r of report.functional_results) {
    listEl.appendChild(resultRow(r));
  }

  let perfDetailsList: HTMLElement | null = null;
  if (report.performance_results.length) {
    const perfList = h(".list");
    for (const pm of report.performance_results) {
      // Bar chart: p50/p95/p99 as horizontal bars relative to max
      const maxMs = Math.max(pm.p99_latency_ms, pm.sla_p95_ms || 0, pm.sla_p99_ms || 0, 1);
      const bar = (label: string, ms: number, color: string, sla?: number | null) => {
        const pct = Math.min(100, (ms / maxMs) * 100);
        const breach = sla != null && ms > sla;
        return h("div", { style: { display: "flex", alignItems: "center", gap: "8px", marginBottom: "4px" } },
          h("span.mono.muted", { style: { width: "32px", fontSize: "11px" } }, label),
          h("div", { style: { flex: 1, height: "14px", background: "var(--bg-muted)", borderRadius: "4px", position: "relative", overflow: "hidden" } },
            h("div", { style: { width: `${pct}%`, height: "100%", background: breach ? "var(--danger)" : color, borderRadius: "4px", transition: "width 0.3s" } }),
            sla != null ? h("div", { style: { position: "absolute", left: `${Math.min(100, (sla / maxMs) * 100)}%`, top: 0, bottom: 0, width: "2px", background: "var(--warning)" } }) : null as unknown as HTMLElement,
          ),
          h("span.mono", { style: { width: "60px", fontSize: "11px", textAlign: "right", color: breach ? "var(--danger)" : "var(--text)" } }, `${ms.toFixed(0)}ms`),
        );
      };

      perfList.appendChild(
        h(".row", { style: { cursor: "default", display: "block", padding: "var(--s-4)" } },
          h(".inline", { style: { marginBottom: "var(--s-3)" } },
            h(`span.method.${pm.method}`, pm.method),
            h("span.mono", { style: { marginLeft: "var(--s-2)" } }, pm.endpoint),
            h("span.flex-1"),
            h("span.mono.muted", { style: { fontSize: "11px" } },
              `${pm.total_requests} req · ${pm.requests_per_second.toFixed(1)} tps · ${pm.error_rate_pct.toFixed(1)}% err`,
            ),
            pm.sla_p95_ms != null
              ? h("span.badge." + (pm.p95_latency_ms <= pm.sla_p95_ms ? "passed" : "failed"),
                  { style: { marginLeft: "var(--s-2)" } },
                  pm.p95_latency_ms <= pm.sla_p95_ms ? "SLA OK" : "SLA BREACH")
              : null as unknown as HTMLElement,
          ),
          bar("p50", pm.p50_latency_ms, "var(--primary)", null),
          bar("p95", pm.p95_latency_ms, "var(--info)", pm.sla_p95_ms),
          bar("p99", pm.p99_latency_ms, "#a78bfa", pm.sla_p99_ms),
        ),
      );
    }
    perfDetailsList = perfList;
  }

  function resultRow(r: TestResult): HTMLElement {
    return h(
      ".row",
      { onclick: () => openResultDetail(r) },
      h(`span.method.${r.method}`, r.method),
      h(
        "div",
        h(".path", r.test_case_name),
        h(".sub",
          `${r.status_code ?? "-"} · ${Math.round(r.response_time_ms)}ms`,
          r.error_message ? ` · ${r.error_message.slice(0, 80)}` : "",
        ),
      ),
      h(`span.badge.${r.status}`, r.status.toUpperCase()),
    );
  }

  function openResultDetail(r: TestResult) {
    const explanation = getStatusExplanation(r.status_code, r.error_message);

    // Compact summary row: status badge, code, timing — all on one line.
    const summary = h(".field",
      h(".inline", { style: { gap: "var(--s-3)", flexWrap: "wrap", alignItems: "center" } },
        h(`span.badge.${r.status}`, r.status.toUpperCase()),
        h("span.mono", `${r.status_code ?? "-"} · ${Math.round(r.response_time_ms)}ms`),
        explanation
          ? h("span.sub", { style: { flex: "1 1 200px" } }, explanation)
          : null as unknown as HTMLElement,
      ),
    );

    const errorField = r.error_message
      ? h(".field", h("label.label", "Error"), h(".mono", { style: { color: "var(--danger)" } }, r.error_message))
      : null;

    const assertions = r.assertion_results.length
      ? h(".field",
          h("label.label", `Assertions (${r.assertion_results.length})`),
          ...r.assertion_results.map((a) =>
            h(".row", { style: { cursor: "default" } },
              h(`span.badge.${a.passed ? "passed" : "failed"}`, a.passed ? "OK" : "FAIL"),
              h("div",
                h(".path", a.assertion_type),
                h(".sub", `expected ${JSON.stringify(a.expected)} · actual ${JSON.stringify(a.actual)}`),
              ),
              h(".sub", a.message || ""),
            ),
          ),
        )
      : null;

    // Two-column layout: request on left, response on right.
    const reqCol = h(".stack", { style: { gap: "var(--s-3)", minWidth: "0" } },
      h("h4", { style: { margin: "0", color: "var(--accent)", fontSize: "12px", letterSpacing: "0.08em" } }, "REQUEST"),
      r.request_url
        ? h(".field", h("label.label", "URL"), h("pre.mono", { style: preStyle }, r.request_url))
        : null,
      r.request_headers && Object.keys(r.request_headers).length
        ? h(".field", h("label.label", "Headers"),
            h("pre.mono", { style: preStyle },
              Object.entries(r.request_headers)
                .map(([k, v]) => `${k}: ${k.toLowerCase() === "authorization" ? maskAuth(v) : v}`)
                .join("\n"),
            ),
          )
        : null,
      r.request_body != null
        ? h(".field", h("label.label", "Body"),
            h("pre.mono", { style: preStyle },
              typeof r.request_body === "object" ? JSON.stringify(r.request_body, null, 2) : String(r.request_body),
            ),
          )
        : null,
    );

    const resCol = h(".stack", { style: { gap: "var(--s-3)", minWidth: "0" } },
      h("h4", { style: { margin: "0", color: "var(--accent-2)", fontSize: "12px", letterSpacing: "0.08em" } }, "RESPONSE"),
      r.response_headers && Object.keys(r.response_headers).length
        ? h(".field", h("label.label", "Headers"),
            h("pre.mono", { style: preStyle },
              Object.entries(r.response_headers).map(([k, v]) => `${k}: ${v}`).join("\n"),
            ),
          )
        : null,
      r.response_body !== undefined && r.response_body !== null
        ? h(".field", h("label.label", "Body"),
            h("pre.mono", { style: preStyle },
              typeof r.response_body === "string" ? r.response_body : JSON.stringify(r.response_body, null, 2),
            ),
          )
        : null,
    );

    const grid = h("div", {
      style: {
        display: "grid",
        gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)",
        gap: "var(--s-4)",
        minHeight: "0",
        flex: "1 1 0",
      },
    }, reqCol, resCol);

    const top = h("div", { style: { flex: "0 0 auto" } },
      ...[summary, errorField, assertions].filter(Boolean) as HTMLElement[],
    );

    const body = h("div", {
      style: { display: "flex", flexDirection: "column", gap: "var(--s-3)", height: "100%", minHeight: "0" },
    }, top, grid);

    openModal({ title: r.test_case_name, body, wide: true });
  }

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

  function maskAuth(v: string): string {
    if (v.length <= 12) return "***";
    return v.slice(0, 10) + "***" + v.slice(-4);
  }

  async function openReport() {
    try {
      const html = await renderReportHtml(report);
      const win = window.open("", "_blank");
      if (win) {
        win.document.open();
        win.document.write(html);
        win.document.close();
      } else {
        toast("POPUP BLOCKED", "Allow popups to view the report", "error");
      }
    } catch (e) {
      toast("REPORT FAILED", String((e as Error).message), "error");
    }
  }

  // --- Details tabs (Functional / Performance) ---
  type DetailTab = "Functional" | "Performance";
  const availableTabs: DetailTab[] = ["Functional"];
  if (perfDetailsList) availableTabs.push("Performance");
  let activeTab: DetailTab = "Functional";

  const tabBar = h(".inline", { style: { gap: "var(--s-2)", marginBottom: "var(--s-3)" } });
  const tabContent = h("div");

  function renderTabs() {
    tabBar.innerHTML = "";
    for (const t of availableTabs) {
      const label =
        t === "Functional"
          ? `FUNCTIONAL (${report.total_tests})`
          : `PERFORMANCE (${report.performance_results.length})`;
      tabBar.appendChild(
        h(
          `button.btn.sm${activeTab === t ? ".primary" : ""}`,
          { onclick: () => { activeTab = t; renderTabs(); } },
          label,
        ),
      );
    }
    tabContent.innerHTML = "";
    tabContent.appendChild(activeTab === "Functional" ? listEl : (perfDetailsList as HTMLElement));
  }
  renderTabs();

  const detailsPanel = h(
    ".panel",
    h(".panel-h", h("span.accent"), h("h2", "Details")),
    tabBar,
    tabContent,
  );

  const layout = h(
    ".stack",
    h(".panel", header),
    funcOverview,
    perfOverview as HTMLElement | null,
    detailsPanel,
  );
  container.appendChild(layout);
  revealUp([...layout.children].filter(Boolean) as Element[]);
  staggerIn(listEl.querySelectorAll(".row"));

  return () => {};
}

function getStatusExplanation(code: number | null | undefined, errorMsg?: string): string | null {
  if (!code && errorMsg) {
    if (errorMsg.includes("timed out")) return "The server did not respond within the configured timeout. Check if the service is running and responsive.";
    if (errorMsg.includes("Connection")) return "Could not connect to the server. Verify the base URL and that the service is reachable.";
    return null;
  }
  switch (code) {
    case 400: return "Bad Request — the server rejected the request body or parameters. Check required fields, data types, and validation rules.";
    case 401: return "Unauthorized — authentication is required. Configure auth credentials in the Test Config modal.";
    case 403: return "Forbidden — the authenticated user doesn't have permission for this operation.";
    case 404: return "Not Found — the resource doesn't exist. Check path parameters (IDs) are valid.";
    case 405: return "Method Not Allowed — this HTTP method isn't supported on this endpoint.";
    case 409: return "Conflict — the request conflicts with existing data (e.g., duplicate creation).";
    case 415: return "Unsupported Media Type — send Content-Type: application/json header.";
    case 422: return "Unprocessable Entity — the request body is syntactically valid but semantically wrong.";
    case 429: return "Too Many Requests — rate limited. Add a delay between requests in Test Config.";
    case 500: return "Internal Server Error — the server crashed processing this request. This is a server-side bug.";
    case 502: return "Bad Gateway — the server's upstream dependency is down.";
    case 503: return "Service Unavailable — the server is overloaded or in maintenance.";
    default: return null;
  }
}
