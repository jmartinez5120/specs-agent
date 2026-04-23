// Shared endpoint-detail renderer. Used by the scan-preview modal and the
// spec browser so both views show identical information.

import { h } from "./dom";
import type { Endpoint } from "./types";

export function renderEndpointDetail(ep: Endpoint): HTMLElement {
  return h("div",
    h(".inline", { style: { marginBottom: "var(--s-3)", alignItems: "center" } },
      h(`span.method.${ep.method}`, ep.method),
      h("span.mono", { style: { marginLeft: "var(--s-2)", fontSize: "14px" } }, ep.path),
    ),
    ep.operation_id
      ? h(".sub", { style: { marginBottom: "var(--s-3)" } },
          h("span.muted", "operationId: "),
          h("span.mono", ep.operation_id),
        )
      : (null as unknown as HTMLElement),
    ep.summary
      ? h("div", { style: { marginBottom: "var(--s-3)", fontWeight: 600 } }, ep.summary)
      : (null as unknown as HTMLElement),
    ep.description
      ? h(".sub", { style: { marginBottom: "var(--s-4)", whiteSpace: "pre-wrap" } }, ep.description)
      : (null as unknown as HTMLElement),

    renderParamsSection(ep),
    renderRequestBodySection(ep),
    renderResponsesSection(ep),
    renderSecuritySection(ep),
    renderPerfSlaSection(ep),
  );
}

function sectionHeader(label: string): HTMLElement {
  return h("div", {
    style: {
      fontSize: "11px",
      fontWeight: 600,
      textTransform: "uppercase",
      letterSpacing: "0.08em",
      color: "var(--muted)",
      marginTop: "var(--s-3)",
      marginBottom: "var(--s-2)",
    },
  }, label);
}

function renderParamsSection(ep: Endpoint): HTMLElement | null {
  const params = (ep.parameters || []) as Array<{
    name: string; location: string; required: boolean; schema_type?: string;
    description?: string; default?: unknown; example?: unknown; enum_values?: string[];
  }>;
  if (!params.length) return null;

  const byLoc: Record<string, typeof params> = {};
  for (const p of params) (byLoc[p.location] ||= []).push(p);

  return h("div",
    sectionHeader(`Parameters (${params.length})`),
    ...Object.entries(byLoc).map(([loc, ps]) =>
      h("div", { style: { marginBottom: "var(--s-2)" } },
        h(".sub", { style: { marginBottom: "2px" } }, `${loc.toUpperCase()}`),
        h("div", { style: { display: "grid", gap: "2px" } },
          ...ps.map((p) =>
            h(".mono", { style: { fontSize: "12px" } },
              h("span", { style: { color: p.required ? "var(--warning)" : "var(--text)" } },
                `${p.name}${p.required ? "*" : ""}`),
              h("span.muted", `  : ${p.schema_type || "string"}`),
              p.description ? h("span.muted", `  — ${p.description}`) : (null as unknown as HTMLElement),
              p.enum_values?.length ? h("span.muted", `  [${p.enum_values.join(", ")}]`) : (null as unknown as HTMLElement),
              p.example !== undefined && p.example !== null
                ? h("span.muted", `  e.g. ${JSON.stringify(p.example)}`) : (null as unknown as HTMLElement),
            ),
          ),
        ),
      ),
    ),
  );
}

function renderRequestBodySection(ep: Endpoint): HTMLElement | null {
  const schema = ep.request_body_schema as Record<string, unknown> | undefined;
  if (!schema) return null;
  return h("div",
    sectionHeader("Request body"),
    h("pre.mono", {
      style: {
        fontSize: "11px",
        background: "var(--bg, #0f1220)",
        padding: "var(--s-3)",
        borderRadius: "var(--r-2)",
        maxHeight: "220px",
        overflow: "auto",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
      },
    }, JSON.stringify(schema, null, 2)),
  );
}

function renderResponsesSection(ep: Endpoint): HTMLElement | null {
  const responses = (ep.responses || []) as Array<{ status_code: number; description?: string; schema?: unknown }>;
  if (!responses.length) return null;
  // 2xx first (success is what the caller cares about most), then the rest
  // ascending. Within each bucket, ascending status code.
  const sorted = [...responses].sort((a, b) => {
    const aSuccess = a.status_code >= 200 && a.status_code < 300 ? 0 : 1;
    const bSuccess = b.status_code >= 200 && b.status_code < 300 ? 0 : 1;
    if (aSuccess !== bSuccess) return aSuccess - bSuccess;
    return a.status_code - b.status_code;
  });
  return h("div",
    sectionHeader(`Responses (${responses.length})`),
    h("div", { style: { display: "grid", gap: "var(--s-2)" } },
      ...sorted.map((r) => {
        const code = r.status_code;
        const color = code < 300 ? "var(--success, #5c5)" : code < 400 ? "var(--info, #5ac)" : "var(--danger, #c55)";
        return h("div",
          h(".inline", { style: { gap: "var(--s-2)" } },
            h("span.mono", { style: { color, fontWeight: 600 } }, String(code)),
            h("span.sub", r.description || ""),
          ),
          r.schema
            ? h("pre.mono", {
                style: {
                  fontSize: "11px", background: "var(--bg, #0f1220)",
                  padding: "var(--s-2)", borderRadius: "var(--r-2)",
                  maxHeight: "140px", overflow: "auto",
                  whiteSpace: "pre-wrap", wordBreak: "break-word",
                  marginTop: "2px",
                },
              }, JSON.stringify(r.schema, null, 2))
            : (null as unknown as HTMLElement),
        );
      }),
    ),
  );
}

function renderSecuritySection(ep: Endpoint): HTMLElement | null {
  const sec = (ep.security || []) as Record<string, unknown>[];
  if (!sec.length) return null;
  const schemes = sec.flatMap((s) => Object.keys(s));
  return h("div",
    sectionHeader("Security"),
    h(".inline", { style: { flexWrap: "wrap", gap: "4px" } },
      ...schemes.map((s) => h("span.tag", s)),
    ),
  );
}

function renderPerfSlaSection(ep: Endpoint): HTMLElement | null {
  const sla = ep.performance_sla as {
    latency_p95_ms?: number | null; latency_p99_ms?: number | null;
    throughput_rps?: number | null; timeout_ms?: number | null;
  } | undefined;
  if (!sla) return null;
  const parts: string[] = [];
  if (sla.latency_p95_ms != null) parts.push(`p95 < ${sla.latency_p95_ms}ms`);
  if (sla.latency_p99_ms != null) parts.push(`p99 < ${sla.latency_p99_ms}ms`);
  if (sla.throughput_rps != null) parts.push(`≥ ${sla.throughput_rps} tps`);
  if (sla.timeout_ms != null) parts.push(`timeout ${sla.timeout_ms}ms`);
  if (!parts.length) return null;
  return h("div",
    sectionHeader("Expected performance (x-performance)"),
    h(".mono", { style: { fontSize: "12px" } }, parts.join("   ·   ")),
  );
}
