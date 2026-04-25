// API client — every backend route wrapped in a typed function.
// In dev, Vite proxies /api/* to http://localhost:8765. In Docker, nginx does.

import type {
  AppConfig,
  ExecEvent,
  LoadSpecResponse,
  Report,
  TestPlan,
  TestRunConfig,
} from "./types";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) || "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "content-type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ------------------------------------------------------------------ //
// Health
// ------------------------------------------------------------------ //

export async function health(): Promise<{ status: string; service: string }> {
  return req("/health");
}

// ------------------------------------------------------------------ //
// Specs
// ------------------------------------------------------------------ //

export async function loadSpec(
  source: string,
  opts: { save?: boolean } = {},
): Promise<LoadSpecResponse> {
  return req("/specs/load", {
    method: "POST",
    body: JSON.stringify({ source, save: opts.save ?? true }),
  });
}

export async function listSavedSpecs(limit = 20): Promise<{
  id: string;
  title: string;
  source: string;
  source_type: string;
  saved_at: string;
}[]> {
  return req(`/specs/saved?limit=${limit}`);
}

export async function loadSavedSpec(specId: string): Promise<Record<string, unknown>> {
  return req(`/specs/saved/${encodeURIComponent(specId)}`);
}

export async function deleteSavedSpec(specId: string): Promise<void> {
  await req(`/specs/saved/${encodeURIComponent(specId)}`, { method: "DELETE" });
}

// ------------------------------------------------------------------ //
// Search — backed by Elasticsearch on the server. See
// `src/specs_agent/search/service.py` for the server-side contract.
// ------------------------------------------------------------------ //

export type SearchKind = "spec" | "endpoint" | "test_case" | "run";

/** One hit returned by the backend. `title` / `subtitle` may contain
 *  `<mark>...</mark>` tags from the ES highlighter. They are safe to
 *  render via `innerHTML` because the server HTML-escapes every
 *  user-supplied string BEFORE indexing — the only unescaped markup ES
 *  can introduce is the `<mark>` wrapper itself. */
export interface SearchHit {
  kind: SearchKind;
  id: string;
  spec_id: string;
  title: string;
  subtitle: string;
  score: number;
  meta: Record<string, unknown>;
}

export interface SearchResult {
  /** Keyed by kind. Missing keys = that kind was filtered out. Empty
   *  arrays = that kind had zero hits. */
  groups: Partial<Record<SearchKind, SearchHit[]>>;
  total: number;
}

export async function searchSpecs(
  q: string,
  kinds?: SearchKind[],
  limit = 30,
): Promise<SearchResult> {
  return req<SearchResult>("/search", {
    method: "POST",
    body: JSON.stringify({ q, kinds: kinds ?? null, limit }),
  });
}

/** Drop and rebuild the ES index from Mongo. Returns the number of docs
 *  upserted. Destructive — search is briefly unavailable mid-rebuild. */
export async function reindexSearch(): Promise<{ reindexed: number }> {
  return req<{ reindexed: number }>("/search/reindex", { method: "POST" });
}

// ------------------------------------------------------------------ //
// Plans
// ------------------------------------------------------------------ //

export async function generatePlan(
  rawSpec: Record<string, unknown>,
  source = "",
): Promise<TestPlan> {
  return req("/plans/generate", {
    method: "POST",
    body: JSON.stringify({ spec: { raw_spec: rawSpec, source } }),
  });
}

export async function generateOrMergePlan(
  rawSpec: Record<string, unknown>,
  source = "",
): Promise<{
  plan: TestPlan;
  merge: { kept: number; new: number; removed: number } | null;
}> {
  return req("/plans/generate-or-merge", {
    method: "POST",
    body: JSON.stringify({ spec: { raw_spec: rawSpec, source } }),
  });
}

export async function savePlan(plan: TestPlan): Promise<{ path: string }> {
  return req("/plans/save", {
    method: "POST",
    body: JSON.stringify({ plan }),
  });
}

export async function loadSavedPlan(specTitle: string): Promise<TestPlan> {
  return req(`/plans/${encodeURIComponent(specTitle)}`);
}

export async function archivePlan(plan: TestPlan): Promise<{ path: string }> {
  return req("/plans/archive", {
    method: "POST",
    body: JSON.stringify({ plan }),
  });
}

// ------------------------------------------------------------------ //
// Config
// ------------------------------------------------------------------ //

export async function getConfig(): Promise<AppConfig> {
  return req("/config");
}

export async function putConfig(config: AppConfig): Promise<void> {
  await req("/config", { method: "PUT", body: JSON.stringify(config) });
}

// ------------------------------------------------------------------ //
// History
// ------------------------------------------------------------------ //

export interface HistoryRun {
  filename: string;
  timestamp: string;
  total: number;
  passed: number;
  failed: number;
  errors: number;
  pass_rate: number;
  duration: number;
  perf_requests: number;
  perf_avg_ms: number;
  perf_p95_ms: number;
  perf_p99_ms: number;
  perf_rps: number;
  perf_err_pct: number;
}

export async function listHistory(
  specTitle: string,
  baseUrl: string,
  limit = 20,
): Promise<HistoryRun[]> {
  const params = new URLSearchParams({
    spec_title: specTitle,
    base_url: baseUrl,
    limit: String(limit),
  });
  return req(`/history?${params}`);
}

export async function loadHistoryRun(
  specTitle: string,
  baseUrl: string,
  filename: string,
): Promise<Report> {
  const params = new URLSearchParams({
    spec_title: specTitle,
    base_url: baseUrl,
    filename,
  });
  return req(`/history/run?${params}`);
}

// ------------------------------------------------------------------ //
// Reports
// ------------------------------------------------------------------ //

export async function renderReportHtml(report: Report): Promise<string> {
  const res = await fetch(`${API_BASE}/reports/html`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ report }),
  });
  if (!res.ok) throw new Error(`Report render failed: ${res.statusText}`);
  return res.text();
}

// ------------------------------------------------------------------ //
// Streaming plan generation (WebSocket)
// ------------------------------------------------------------------ //

export interface GenProgress {
  event: "step" | "complete" | "error";
  step?: string;
  progress?: number;
  detail?: string;
  model?: string;
  plan?: import("./types").TestPlan;
  merge?: { kept: number; new: number; removed: number } | null;
  message?: string;
}

export interface GenerateOptions {
  include_happy?: boolean;
  include_sad?: boolean;
  include_ai?: boolean;
}

export function generatePlanStreaming(
  rawSpec: Record<string, unknown>,
  source: string,
  onProgress: (ev: GenProgress) => void,
  options: GenerateOptions = {},
): { cancel: () => void } {
  const url = wsUrlFor("/ws/generate");
  const ws = new WebSocket(url);

  ws.addEventListener("open", () => {
    ws.send(JSON.stringify({
      raw_spec: rawSpec,
      source,
      include_happy: options.include_happy ?? true,
      include_sad: options.include_sad ?? true,
      include_ai: options.include_ai ?? false,
    }));
  });

  ws.addEventListener("message", (ev) => {
    try {
      onProgress(JSON.parse(ev.data) as GenProgress);
    } catch {
      // ignore parse errors
    }
  });

  ws.addEventListener("error", () => {
    onProgress({ event: "error", message: "WebSocket connection failed" });
  });

  ws.addEventListener("close", () => {
    // If we never got a "complete", treat as error
  });

  return {
    cancel: () => {
      try { ws.close(); } catch { /* ignore */ }
    },
  };
}

function wsUrlFor(path: string): string {
  const origin = API_BASE.startsWith("http")
    ? API_BASE
    : `${location.protocol}//${location.host}${API_BASE}`;
  const full = `${origin.replace(/\/$/, "")}${path}`;
  return full.replace(/^http/, "ws");
}

// ------------------------------------------------------------------ //
// AI
// ------------------------------------------------------------------ //

export interface ProxyRequestPayload {
  method: string;
  url: string;
  headers?: Record<string, string>;
  body?: unknown;
  timeout_seconds?: number;
  verify_ssl?: boolean;
}

export interface ProxyResponse {
  ok: boolean;
  status_code?: number;
  reason_phrase?: string;
  elapsed_ms: number;
  headers?: Record<string, string>;
  body?: unknown;
  body_text?: string;
  final_url?: string;
  error?: string;
}

export async function proxyRequest(payload: ProxyRequestPayload): Promise<ProxyResponse> {
  return req<ProxyResponse>("/proxy-request", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getAIStatus(): Promise<Record<string, unknown>> {
  return req("/ai/status");
}

export async function clearAICache(): Promise<{ cleared: number }> {
  return req("/ai/cache/clear", { method: "POST" });
}

export async function getAIPresets(): Promise<Record<string, unknown>[]> {
  return req("/ai/presets");
}

export interface AIModel {
  id: string;
  display_name: string;
}

export interface AIModelsResponse {
  models: AIModel[];
  /** "live" | "fallback" | "fallback_empty" | "presets" | "no_credentials" | "no_base_url" */
  source: string;
  error?: string;
}

/** Ask the backend to fetch a provider's model catalog. The backend proxies
 *  the call so the user's API key never crosses origins. */
export async function listAIModels(
  provider: string,
  apiKey?: string,
  baseUrl?: string,
): Promise<AIModelsResponse> {
  return req<AIModelsResponse>("/ai/models", {
    method: "POST",
    body: JSON.stringify({
      provider,
      api_key: apiKey || "",
      base_url: baseUrl || "",
    }),
  });
}

// ------------------------------------------------------------------ //
// WebSocket execution
// ------------------------------------------------------------------ //

export class ExecutionSocket {
  private ws: WebSocket;
  private onEvent: (e: ExecEvent) => void;
  private onClose: () => void;

  constructor(onEvent: (e: ExecEvent) => void, onClose: () => void = () => {}) {
    this.onEvent = onEvent;
    this.onClose = onClose;
    const url = wsUrlFor("/ws/execute");
    this.ws = new WebSocket(url);
    this.ws.addEventListener("message", this.handleMessage);
    this.ws.addEventListener("close", this.handleClose);
    this.ws.addEventListener("error", () => {
      // bubble through as an error event so the UI shows something
      this.onEvent({ event: "error", message: "WebSocket connection error" });
    });
  }

  start(plan: TestPlan, config: TestRunConfig): void {
    const send = () => this.ws.send(JSON.stringify({ plan, config }));
    if (this.ws.readyState === WebSocket.OPEN) {
      send();
    } else {
      this.ws.addEventListener("open", send, { once: true });
    }
  }

  cancel(): void {
    if (this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action: "cancel" }));
    }
  }

  close(): void {
    try {
      this.ws.close();
    } catch {
      /* ignore */
    }
  }

  private handleMessage = (ev: MessageEvent) => {
    try {
      this.onEvent(JSON.parse(ev.data) as ExecEvent);
    } catch (e) {
      this.onEvent({ event: "error", message: `Invalid event: ${e}` });
    }
  };

  private handleClose = () => {
    this.onClose();
  };
}

// wsUrlFor is defined above (shared between ExecutionSocket and generatePlanStreaming)
