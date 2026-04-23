// Test Config modal — edits the TestRunConfig in state (auth, SSL,
// timeouts, performance, staged ramp-up). Used between Plan → Execution.

import { getConfig, putConfig } from "../api";
import { h } from "../dom";
import { openModal } from "../modal";
import { store } from "../state";
import { toast } from "../toast";
import type { RampStage, TestRunConfig, TokenFetchConfig } from "../types";

const DEFAULT_TOKEN_FETCH: TokenFetchConfig = {
  token_url: "",
  method: "POST",
  headers: "",
  integration_id_field: "client_id",
  integration_id_value: "",
  scope: "",
  extra_body: "",
  token_response_path: "access_token",
  response_has_bearer_prefix: false,
};

export async function openTestConfigModal(
  onSave: (config: TestRunConfig) => void,
): Promise<() => void> {
  // Work on a deep clone so Cancel reverts cleanly
  const config: TestRunConfig = JSON.parse(JSON.stringify(store.state.runConfig));
  // Base URL always comes from the spec — single source of truth
  config.base_url = store.state.spec?.servers?.[0]?.url
    || store.state.plan?.base_url
    || config.base_url;

  // Pre-fill Auth + token_fetch from persisted AppConfig.saved_* when the
  // current run config hasn't set them yet. This makes auth values reusable
  // across sessions and specs.
  let appConfig: Awaited<ReturnType<typeof getConfig>> | null = null;
  try {
    appConfig = await getConfig();
    const noStaticAuth = !config.auth_value && (!config.auth_type || config.auth_type === "none");
    if (noStaticAuth && appConfig.saved_auth_type) {
      config.auth_type = appConfig.saved_auth_type;
      config.auth_value = appConfig.saved_auth_value ?? "";
      config.auth_header = appConfig.saved_auth_header || "Authorization";
    }
    const tfEmpty = !config.token_fetch || !config.token_fetch.token_url;
    if (tfEmpty && appConfig.saved_token_fetch && appConfig.saved_token_fetch.token_url) {
      config.token_fetch = { ...DEFAULT_TOKEN_FETCH, ...appConfig.saved_token_fetch } as TokenFetchConfig;
      if (!config.auth_value) config.auth_type = "bearer_fetch";
    }
  } catch {
    // Fall back silently — the modal still works without persistence.
  }

  // --- Request section ---
  const servers = (store.state.spec?.servers || []) as { url: string; description?: string }[];
  const baseUrlInput = input("text", config.base_url, (v) => (config.base_url = v)) as HTMLInputElement;

  const envBlock = servers.length > 1
    ? (() => {
        const sel = h(
          "select.select",
          { style: { width: "100%" } },
          ...servers.map((s, i) =>
            h("option", {
              value: s.url,
              selected: s.url === config.base_url || (i === 0 && !servers.some((x) => x.url === config.base_url)),
            }, s.description ? `${s.description} — ${s.url}` : s.url),
          ),
        ) as HTMLSelectElement;
        sel.addEventListener("change", () => {
          config.base_url = sel.value;
          baseUrlInput.value = sel.value;
        });
        return field("Environment", sel);
      })()
    : null;

  const reqBody = h("div",
    envBlock || (null as unknown as HTMLElement),
    field("Base URL",
      baseUrlInput,
    ),
    h(".grid",
      field("Timeout (s)",
        input("number", String(config.timeout_seconds), (v) => (config.timeout_seconds = +v || 30)),
      ),
      field("Delay between (ms)",
        input("number", String(config.delay_between_ms), (v) => (config.delay_between_ms = +v || 0)),
      ),
      field("Retry count",
        input("number", String(config.retry_count), (v) => (config.retry_count = +v || 0)),
      ),
    ),
    h(".inline.mt-4",
      checkbox("Follow redirects", config.follow_redirects, (v) => (config.follow_redirects = v)),
      checkbox("Verify SSL", config.verify_ssl, (v) => (config.verify_ssl = v)),
    ),
  );

  // --- Auth section ---
  if (!config.token_fetch) config.token_fetch = { ...DEFAULT_TOKEN_FETCH };
  const tf = config.token_fetch;

  const authValueInput = input("text", config.auth_value, (v) => (config.auth_value = v));
  const authHeaderInput = input("text", config.auth_header, (v) => (config.auth_header = v));

  const fetchSection = h("div");
  const fetchStatus = h(".muted.mono", { style: { fontSize: "11px", marginTop: "var(--s-2)" } }, "");

  function renderFetchSection() {
    fetchSection.innerHTML = "";
    if (config.auth_type !== "bearer_fetch") return;

    const headersArea = h("textarea.input", {
      rows: 3,
      placeholder: '{\n  "X-API-Key": "..."\n}',
      style: { fontFamily: "var(--mono)", fontSize: "12px" },
      oninput: (e: Event) => (tf.headers = (e.target as HTMLTextAreaElement).value),
    }) as HTMLTextAreaElement;
    headersArea.value = tf.headers;

    const bodyArea = h("textarea.input", {
      rows: 3,
      placeholder: '{\n  "grant_type": "client_credentials"\n}',
      style: { fontFamily: "var(--mono)", fontSize: "12px" },
      oninput: (e: Event) => (tf.extra_body = (e.target as HTMLTextAreaElement).value),
    }) as HTMLTextAreaElement;
    bodyArea.value = tf.extra_body;

    const bearerCheckbox = checkbox(
      "Response already includes 'Bearer ' prefix (strip before saving)",
      tf.response_has_bearer_prefix,
      (v) => (tf.response_has_bearer_prefix = v),
    );

    const fetchBtn = h("button.btn.sm.primary", {
      onclick: async () => {
        fetchStatus.textContent = "Fetching...";
        fetchStatus.style.color = "var(--muted)";
        try {
          const token = await fetchAuthToken(tf);
          config.auth_value = token;
          authValueInput.value = token;
          fetchStatus.textContent = `✓ Token fetched (${token.length} chars)`;
          fetchStatus.style.color = "var(--green, #55cc55)";
          toast("TOKEN FETCHED", "Bearer token saved to Value", "success");
        } catch (e) {
          fetchStatus.textContent = `✗ ${(e as Error).message}`;
          fetchStatus.style.color = "var(--red, #cc4444)";
        }
      },
    }, "FETCH TOKEN");

    fetchSection.appendChild(
      h("div", { style: { marginTop: "var(--s-4)", paddingTop: "var(--s-4)", borderTop: "1px solid var(--border)" } },
        h(".label", "Token endpoint"),
        h(".muted.mono", { style: { fontSize: "11px", marginBottom: "var(--s-2)" } },
          "Fetched before every request at runtime. If the response includes `expires_in`, the token is cached and reused until it's about to expire."),
        h(".grid",
          field("Token URL",
            input("text", tf.token_url, (v) => (tf.token_url = v)),
          ),
          field("Method",
            select(tf.method, ["POST", "GET"], (v) => (tf.method = v)),
          ),
        ),
        h(".grid",
          field("Integration ID field name",
            input("text", tf.integration_id_field, (v) => (tf.integration_id_field = v)),
          ),
          field("Integration ID value",
            input("text", tf.integration_id_value, (v) => (tf.integration_id_value = v)),
          ),
        ),
        field("Scope (space-separated endpoints)",
          input("text", tf.scope, (v) => (tf.scope = v)),
        ),
        field("Request headers (JSON)", headersArea),
        field("Extra request body (JSON, merged with integration_id + scope)", bodyArea),
        field("Token response field (dotted path, e.g. access_token, data.token)",
          input("text", tf.token_response_path, (v) => (tf.token_response_path = v)),
        ),
        h(".mt-2", bearerCheckbox),
        h(".inline", { style: { gap: "var(--s-3)", alignItems: "center", marginTop: "var(--s-2)" } },
          fetchBtn,
          fetchStatus,
        ),
      ),
    );
  }

  const authTypeSelect = select(
    config.auth_type,
    ["none", "bearer", "bearer_fetch", "api_key", "basic"],
    (v) => {
      config.auth_type = v;
      if (v === "bearer" || v === "basic" || v === "bearer_fetch") {
        config.auth_header = "Authorization";
        authHeaderInput.value = "Authorization";
      }
      renderFetchSection();
    },
  );

  const clearBtn = h("button.btn.sm.danger", {
    onclick: async () => {
      // Reset in-memory config and wipe persisted saved_* fields so the next
      // modal open starts blank.
      config.auth_type = "none";
      config.auth_value = "";
      config.auth_header = "Authorization";
      config.token_fetch = { ...DEFAULT_TOKEN_FETCH };
      authValueInput.value = "";
      authHeaderInput.value = "Authorization";
      (authTypeSelect as HTMLSelectElement).value = "none";
      renderFetchSection();
      try {
        if (appConfig) {
          const wiped = {
            ...appConfig,
            saved_auth_type: "none",
            saved_auth_value: "",
            saved_auth_header: "Authorization",
            saved_token_fetch: {},
          };
          await putConfig(wiped);
          appConfig = wiped;
          toast("AUTH CLEARED", "Saved auth + token fetch wiped from DB", "success");
        }
      } catch (e) {
        toast("CLEAR FAILED", String((e as Error).message), "error");
      }
    },
  }, "CLEAR SAVED AUTH");

  const authBody = h("div",
    field("Auth type", authTypeSelect),
    h(".grid",
      field("Header", authHeaderInput),
      field("Value (token / api key / user:pass)", authValueInput),
    ),
    fetchSection,
    h(".mt-4", clearBtn),
  );
  renderFetchSection();

  // --- Performance section ---
  const perf = config.performance;

  const stagesList = h(".list", { style: { marginTop: "var(--s-3)" } });

  function renderStages() {
    stagesList.innerHTML = "";
    if (perf.stages.length === 0) {
      stagesList.appendChild(
        h(".muted.mono", { style: { fontSize: "11px", padding: "var(--s-2)" } },
          "No stages — using concurrent_users + duration fields above"),
      );
      return;
    }
    perf.stages.forEach((s, idx) => {
      const users = input("number", String(s.users), (v) => (perf.stages[idx].users = +v || 1));
      const dur = input("number", String(s.duration_seconds), (v) => (perf.stages[idx].duration_seconds = +v || 1));
      stagesList.appendChild(
        h(".row", { style: { cursor: "default" } },
          h("span.mono.muted", { style: { fontSize: "11px" } }, `#${idx + 1}`),
          h(".inline",
            h(".field", { style: { marginBottom: 0 } }, h("label.label", "Users"), users),
            h(".field", { style: { marginBottom: 0 } }, h("label.label", "Duration (s)"), dur),
          ),
          h("button.btn.sm.danger", {
            onclick: () => {
              perf.stages.splice(idx, 1);
              renderStages();
            },
          }, "REMOVE"),
        ),
      );
    });
  }

  const perfToggle = checkbox(
    "Enable performance testing",
    perf.enabled,
    (v) => {
      perf.enabled = v;
      perfFields.style.opacity = v ? "1" : "0.35";
      perfFields.style.pointerEvents = v ? "auto" : "none";
    },
  );

  const perfFields = h("div",
    h(".grid",
      field("Concurrent users",
        input("number", String(perf.concurrent_users), (v) => (perf.concurrent_users = +v || 1)),
      ),
      field("Duration (s)",
        input("number", String(perf.duration_seconds), (v) => (perf.duration_seconds = +v || 1)),
      ),
      field("Ramp-up (s)",
        input("number", String(perf.ramp_up_seconds), (v) => (perf.ramp_up_seconds = +v || 0)),
      ),
      field("Target TPS (0 = unlimited)",
        input("number", String(perf.target_tps), (v) => (perf.target_tps = +v || 0)),
      ),
    ),
    h(".label.mt-4", "Latency thresholds (ms)"),
    h(".grid",
      field("p50",
        input("number", String(perf.latency_p50_threshold_ms), (v) => (perf.latency_p50_threshold_ms = +v || 0)),
      ),
      field("p95",
        input("number", String(perf.latency_p95_threshold_ms), (v) => (perf.latency_p95_threshold_ms = +v || 0)),
      ),
      field("p99",
        input("number", String(perf.latency_p99_threshold_ms), (v) => (perf.latency_p99_threshold_ms = +v || 0)),
      ),
      field("Error rate %",
        input("number", String(perf.error_rate_threshold_pct), (v) => (perf.error_rate_threshold_pct = +v || 0)),
      ),
    ),
    h(".label.mt-5", "Staged ramp-up"),
    h(".muted.mono", { style: { fontSize: "11px" } },
      "If set, overrides concurrent_users + duration. Each stage holds at `users` concurrency for `duration_seconds`."),
    stagesList,
    h("button.btn.sm.mt-4", {
      onclick: () => {
        perf.stages.push({ users: 10, duration_seconds: 30 });
        renderStages();
      },
    }, "+ ADD STAGE"),
  );
  if (!perf.enabled) {
    perfFields.style.opacity = "0.35";
    perfFields.style.pointerEvents = "none";
  }

  renderStages();

  const perfBody = h("div", perfToggle, perfFields);

  // --- Tabs ---
  // AI settings live on the plan editor (where generation happens),
  // not here — this modal is the pre-run config.
  const tabs = ["Request", "Auth", "Performance"] as const;
  type Tab = typeof tabs[number];
  const panels: Record<Tab, HTMLElement> = {
    Request: reqBody,
    Auth: authBody,
    Performance: perfBody,
  };
  let active: Tab = "Request";

  const tabBar = h(".inline", { style: { gap: "var(--s-2)", marginBottom: "var(--s-4)" } });
  // Fixed viewport so the modal stays the same size across tabs —
  // tallest panel (Performance) drives the min-height; others scroll if needed.
  const content = h("div", {
    style: {
      minHeight: "620px",
      maxHeight: "70vh",
      overflowY: "auto",
      paddingRight: "var(--s-2)",
      width: "min(86vw, 900px)",
    },
  });

  function renderTabs() {
    tabBar.innerHTML = "";
    for (const t of tabs) {
      tabBar.appendChild(
        h(
          `button.btn.sm${active === t ? ".primary" : ""}`,
          { onclick: () => { active = t; renderTabs(); } },
          t.toUpperCase(),
        ),
      );
    }
    content.innerHTML = "";
    content.appendChild(panels[active]);
  }
  renderTabs();

  const body = h("div", tabBar, content);

  const save = h("button.btn.primary", {
    onclick: async () => {
      // bearer_fetch becomes "bearer" for the executor; the backend uses
      // token_fetch config to obtain a fresh token before every request.
      const persistTf = config.auth_type === "bearer_fetch" ? { ...config.token_fetch } : {};
      if (config.auth_type === "bearer_fetch") {
        if (!config.token_fetch?.token_url) {
          toast("NO TOKEN URL", "Set the Token URL so the runner can fetch before each request", "error");
          return;
        }
        config.auth_type = "bearer";
      } else {
        // If user switched away from bearer_fetch, drop the stored fetch config
        // so stale settings don't follow them into a static auth run.
        if (config.token_fetch) config.token_fetch = undefined;
      }
      store.set({ runConfig: config });

      // Persist auth + token fetch to AppConfig so it survives reloads.
      try {
        if (appConfig) {
          await putConfig({
            ...appConfig,
            saved_auth_type: config.auth_type,
            saved_auth_value: config.auth_value,
            saved_auth_header: config.auth_header,
            saved_token_fetch: persistTf,
          });
        }
      } catch {
        // Non-fatal: the run still proceeds with in-memory config.
      }

      toast("CONFIG SAVED", "Run settings updated", "success");
      close();
      onSave(config);
    },
  }, "SAVE & RUN →");

  const cancel = h("button.btn.ghost", { onclick: () => close() }, "Cancel");

  const close = openModal({
    title: "Test Configuration",
    body,
    actions: [cancel, save],
    wide: true,
    // Auth values and tokens can be sensitive; don't let a misclick outside
    // discard changes. Only ESC or Cancel dismisses.
    dismissOnBackdrop: false,
  });

  return close;
}

// ---------- helpers ----------

function field(label: string, input: HTMLElement): HTMLElement {
  return h(".field", h("label.label", label), input);
}

function input(type: string, value: string, oninput: (v: string) => void): HTMLInputElement {
  const el = h("input.input", {
    type,
    value,
    oninput: (e: Event) => oninput((e.target as HTMLInputElement).value),
  }) as HTMLInputElement;
  return el;
}

function checkbox(label: string, checked: boolean, onchange: (v: boolean) => void): HTMLElement {
  const cb = h("input", {
    type: "checkbox",
    checked,
    onchange: (e: Event) => onchange((e.target as HTMLInputElement).checked),
  }) as HTMLInputElement;
  return h("label.inline", { style: { cursor: "pointer", marginRight: "var(--s-4)" } }, cb, h("span", label));
}

function select(value: string, options: string[], onchange: (v: string) => void): HTMLSelectElement {
  const el = h(
    "select.select",
    { onchange: (e: Event) => onchange((e.target as HTMLSelectElement).value) },
    ...options.map((o) => h("option", { value: o, selected: o === value }, o)),
  ) as HTMLSelectElement;
  return el;
}

// Walk a dotted path inside a JSON object (e.g. "data.token.access_token").
function pickPath(obj: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((acc, key) => {
    if (acc && typeof acc === "object" && key in (acc as Record<string, unknown>)) {
      return (acc as Record<string, unknown>)[key];
    }
    return undefined;
  }, obj);
}

async function fetchAuthToken(tf: TokenFetchConfig): Promise<string> {
  if (!tf.token_url) throw new Error("Token URL is required");

  let body: Record<string, unknown> = {};
  if (tf.extra_body.trim()) {
    try {
      body = JSON.parse(tf.extra_body);
    } catch (e) {
      throw new Error(`Invalid extra body JSON: ${(e as Error).message}`);
    }
  }
  if (tf.integration_id_field && tf.integration_id_value) {
    body[tf.integration_id_field] = tf.integration_id_value;
  }
  if (tf.scope) body.scope = tf.scope;

  const headers: Record<string, string> = {
    "content-type": "application/json",
    accept: "application/json",
  };
  if (tf.headers && tf.headers.trim()) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(tf.headers);
    } catch (e) {
      throw new Error(`Invalid headers JSON: ${(e as Error).message}`);
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("Headers must be a JSON object");
    }
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      headers[k] = String(v);
    }
  }

  const init: RequestInit = { method: tf.method || "POST", headers };
  if (init.method !== "GET") init.body = JSON.stringify(body);

  const res = await fetch(tf.token_url, init);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);

  const ct = res.headers.get("content-type") || "";
  const payload = ct.includes("json") ? await res.json() : await res.text();
  const path = tf.token_response_path || "access_token";
  const raw = typeof payload === "string" ? payload : pickPath(payload, path);
  if (typeof raw !== "string" || !raw) {
    throw new Error(`Token not found at "${path}"`);
  }
  // The backend prepends "Bearer " at request time, so strip it here if the
  // response already carries the prefix to avoid "Bearer Bearer ...".
  const stripped = tf.response_has_bearer_prefix
    ? raw.replace(/^\s*Bearer\s+/i, "")
    : raw;
  return stripped.trim();
}
