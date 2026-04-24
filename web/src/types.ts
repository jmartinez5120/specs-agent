// Types mirroring the backend API DTOs. Kept loose (index-signature friendly)
// so we can hand plan/config dicts back to the backend untouched.

export interface Assertion {
  type: string;
  expected: unknown;
  description?: string;
}

export interface TestCase {
  id: string;
  endpoint_path: string;
  method: string;
  name: string;
  description?: string;
  enabled: boolean;
  path_params: Record<string, string>;
  query_params: Record<string, string>;
  headers: Record<string, string>;
  body: unknown;
  assertions: Assertion[];
  depends_on: string | null;
  needs_input: boolean;
  test_type: string;
  ai_fields: string[];
  ai_generated: boolean;
  ai_category: string;
  // Per-test-case user variables (merged with plan.global_variables at
  // execution time; local wins on key collision).
  local_variables?: Record<string, unknown>;
}

export interface TestPlan {
  name: string;
  spec_title: string;
  base_url: string;
  created_at?: string;
  test_cases: TestCase[];
  global_headers: Record<string, string>;
  auth_type: string;
  auth_value: string;
  performance_slas: Record<string, Record<string, unknown>>;
  // Plan-wide user variables — available to every test case in templating.
  global_variables?: Record<string, unknown>;
}

export interface Endpoint {
  path: string;
  method: string;
  operation_id?: string | null;
  summary?: string;
  description?: string;
  tags: string[];
  parameters: unknown[];
  request_body_schema?: unknown;
  responses: unknown[];
  security: unknown[];
  performance_sla?: unknown;
}

export interface ParsedSpec {
  title: string;
  version: string;
  description?: string;
  spec_version?: string;
  servers: { url: string; description?: string }[];
  endpoints: Endpoint[];
  tags: string[];
  raw_spec: Record<string, unknown>;
}

export interface LoadSpecResponse {
  spec: ParsedSpec;
  source: string;
  source_type: string;
  warnings: string[];
}

export interface AssertionResult {
  assertion_type: string;
  expected: unknown;
  actual: unknown;
  passed: boolean;
  message?: string;
}

export interface TestResult {
  test_case_id: string;
  test_case_name: string;
  endpoint: string;
  method: string;
  status: "passed" | "failed" | "error" | "skipped";
  status_code?: number | null;
  response_time_ms: number;
  response_body?: unknown;
  assertion_results: AssertionResult[];
  error_message?: string;
  test_type?: string;
  request_url?: string;
  request_headers?: Record<string, string>;
  request_body?: unknown;
  response_headers?: Record<string, string>;
}

export interface PerformanceMetrics {
  endpoint: string;
  method: string;
  total_requests: number;
  successful_requests: number;
  failed_requests: number;
  avg_latency_ms: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  p99_latency_ms: number;
  min_latency_ms: number;
  max_latency_ms: number;
  requests_per_second: number;
  peak_tps?: number;
  error_rate_pct: number;
  sla_p95_ms?: number | null;
  sla_p99_ms?: number | null;
  sla_throughput_rps?: number | null;
  sla_timeout_ms?: number | null;
}

export interface Report {
  plan_name: string;
  base_url: string;
  spec_title: string;
  started_at: string;
  finished_at: string;
  duration_seconds: number;
  functional_results: TestResult[];
  performance_results: PerformanceMetrics[];
  total_tests: number;
  passed_tests: number;
  failed_tests: number;
  error_tests: number;
  pass_rate: number;
}

export interface RampStage {
  users: number;
  duration_seconds: number;
}

export interface PerformanceConfig {
  enabled: boolean;
  concurrent_users: number;
  duration_seconds: number;
  ramp_up_seconds: number;
  requests_per_second: number;
  target_tps: number;
  latency_p50_threshold_ms: number;
  latency_p95_threshold_ms: number;
  latency_p99_threshold_ms: number;
  error_rate_threshold_pct: number;
  target_endpoints: string[];
  stages: RampStage[];
}

export interface TokenFetchConfig {
  token_url: string;
  method: string; // "POST" | "GET"
  headers: string; // JSON object of extra request headers
  integration_id_field: string; // e.g. "client_id", "integration_id"
  integration_id_value: string;
  scope: string; // space-separated endpoints/permissions, OAuth2 style
  extra_body: string; // raw JSON blob merged into the request body
  token_response_path: string; // dotted path, default "access_token"
  response_has_bearer_prefix: boolean; // strip "Bearer " from extracted token
}

export interface TestRunConfig {
  base_url: string;
  timeout_seconds: number;
  follow_redirects: boolean;
  verify_ssl: boolean;
  retry_count: number;
  delay_between_ms: number;
  auth_type: string;
  auth_value: string;
  auth_header: string;
  performance: PerformanceConfig;
  // Optional: configuration for fetching a bearer token from an auth endpoint.
  // Kept client-side only (backend ignores unknown fields). Used by the Auth tab
  // FETCH TOKEN button to populate auth_value with a live token.
  token_fetch?: TokenFetchConfig;
}

export interface AuthPreset {
  name: string;
  type: string;
  header: string;
  value: string;
}

export interface RecentSpec {
  path: string;
  url: string;
  title: string;
  last_opened: string;
}

export interface AppConfig {
  version: number;
  base_url: string;
  timeout_seconds: number;
  follow_redirects: boolean;
  verify_ssl: boolean;
  perf_concurrent_users: number;
  perf_duration_seconds: number;
  perf_ramp_up_seconds: number;
  perf_latency_p95_threshold_ms: number;
  auth_presets: AuthPreset[];
  saved_auth_type?: string;
  saved_auth_value?: string;
  saved_auth_header?: string;
  saved_token_fetch?: Partial<TokenFetchConfig>;
  recent_specs: RecentSpec[];
  reports_output_dir: string;
  reports_format: string;
  reports_open_after: boolean;
  theme: string;
  ai_enabled: boolean;
  ai_model_size: string;
  ai_model_path: string;
  ai_n_ctx: number;
  ai_n_gpu_layers: number;
  ai_cache_dir: string;
  // Multi-provider AI config. The backend is moving from a single "ai_backend"
  // value to a discrete provider selector. Old `ai_backend` is preserved for
  // backward compat reads — the UI writes/reads `ai_provider`.
  ai_provider?: AIProvider;
  /** @deprecated kept for backward compat with older configs */
  ai_backend?: string;
  // Anthropic (Claude API) provider
  ai_anthropic_api_key?: string;
  ai_anthropic_model?: string;
  // OpenAI (ChatGPT) provider
  ai_openai_api_key?: string;
  ai_openai_model?: string;
  ai_openai_base_url?: string;
  // OpenAI-compatible (Ollama, vLLM, etc.) — existing fields, surfaced when
  // ai_provider === "openai_compatible"
  ai_http_base_url?: string;
  ai_http_model?: string;
  ai_http_api_key?: string;
}

export type AIProvider =
  | "local_gguf"
  | "anthropic"
  | "openai"
  | "openai_compatible";

// WebSocket execution events
export type ExecEvent =
  | { event: "phase"; phase: "functional" | "performance" | "complete" }
  | { event: "progress"; completed: number; total: number }
  | { event: "result"; result: TestResult }
  | { event: "perf"; stats: Record<string, unknown> }
  | { event: "complete"; report: Report }
  | { event: "error"; message: string };
