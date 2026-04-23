// Simple pub/sub app state. Keeps the running spec, plan, run config,
// and last report. Screens subscribe to changes they care about.

import type { ParsedSpec, Report, TestPlan, TestRunConfig } from "./types";

export type PendingSpecTab = "spec" | "cases" | "history";

export interface PendingSelection {
  tab: PendingSpecTab;
  // Endpoint selection target (for tab "spec"): match by method+path.
  endpointKey?: string; // "GET /pet/{id}"
  // Test case selection target (for tab "cases"): match by id or name.
  testCaseId?: string;
  testCaseName?: string;
  // Run drill-down target (for tab "history"): open the run with this filename.
  runFilename?: string;
}

export interface AppState {
  specSource: string;
  spec: ParsedSpec | null;
  plan: TestPlan | null;
  runConfig: TestRunConfig;
  lastReport: Report | null;
  backendOnline: boolean;
  // Pending navigation request fulfilled by the Spec Browser shell on mount.
  pendingSelection: PendingSelection | null;
}

type Listener = (state: AppState) => void;

function defaultRunConfig(): TestRunConfig {
  return {
    base_url: "",
    timeout_seconds: 30,
    follow_redirects: true,
    verify_ssl: true,
    retry_count: 0,
    delay_between_ms: 0,
    auth_type: "none",
    auth_value: "",
    auth_header: "Authorization",
    performance: {
      enabled: false,
      concurrent_users: 10,
      duration_seconds: 30,
      ramp_up_seconds: 0,
      requests_per_second: 0,
      target_tps: 0,
      latency_p50_threshold_ms: 500,
      latency_p95_threshold_ms: 2000,
      latency_p99_threshold_ms: 5000,
      error_rate_threshold_pct: 1,
      target_endpoints: [],
      stages: [],
    },
  };
}

class Store {
  private _state: AppState = {
    specSource: "",
    spec: null,
    plan: null,
    runConfig: defaultRunConfig(),
    lastReport: null,
    backendOnline: false,
    pendingSelection: null,
  };
  private listeners = new Set<Listener>();

  get state(): AppState {
    return this._state;
  }

  set(patch: Partial<AppState>): void {
    this._state = { ...this._state, ...patch };
    this.listeners.forEach((l) => l(this._state));
  }

  subscribe(l: Listener): () => void {
    this.listeners.add(l);
    return () => this.listeners.delete(l);
  }
}

export const store = new Store();
