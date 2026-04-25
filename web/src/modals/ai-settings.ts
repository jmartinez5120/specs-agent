// AI Settings panel — multi-provider configuration.
//
// Providers: local_gguf | anthropic | openai | openai_compatible.
// API keys are sensitive: the server returns them masked (e.g.
// "sk-ant-***1234") on GET /config. We track per-field "dirty" state so that
// re-saving a masked value does NOT echo the mask back to the server. On
// PUT /config, an empty string for an *_api_key means "leave unchanged".

import { aiIcon } from "../ai-icon";
import {
  clearAICache,
  getAIPresets,
  getAIStatus,
  getConfig,
  listAIModels,
  putConfig,
} from "../api";
import { h } from "../dom";
import { toast } from "../toast";
import type { AIProvider, AppConfig } from "../types";

type ProviderId = AIProvider;

interface ProviderMeta {
  id: ProviderId;
  label: string;
  blurb: string;
}

const PROVIDERS: ProviderMeta[] = [
  { id: "local_gguf", label: "Local (GGUF)", blurb: "Air-gapped Gemma via llama-cpp-python." },
  { id: "anthropic", label: "Anthropic", blurb: "Claude API — managed, fast, current." },
  { id: "openai", label: "OpenAI", blurb: "ChatGPT API — gpt-4o family." },
  { id: "openai_compatible", label: "OpenAI-compatible", blurb: "Ollama, vLLM, LM Studio, custom." },
];

function isProvider(v: unknown): v is ProviderId {
  return v === "local_gguf" || v === "anthropic" || v === "openai" || v === "openai_compatible";
}

/** Build a password input with a "show/hide" toggle. Tracks dirty state:
 *  the input is "dirty" once the user changes it from the initial (masked)
 *  value the server gave us. */
function passwordField(
  initial: string,
  placeholder: string,
): { wrap: HTMLElement; input: HTMLInputElement; isDirty: () => boolean } {
  const input = h("input.input.mono", {
    type: "password",
    value: initial,
    placeholder,
    style: { flex: "1 1 0", minWidth: "0" },
  }) as HTMLInputElement;

  const showBtn = h("button.btn.sm.ghost", {
    type: "button",
    onclick: () => {
      input.type = input.type === "password" ? "text" : "password";
      showBtn.textContent = input.type === "password" ? "Show" : "Hide";
    },
  }, "Show") as HTMLButtonElement;

  const wrap = h(".inline", { style: { gap: "var(--s-2)", alignItems: "stretch" } }, input, showBtn);
  return { wrap, input, isDirty: () => input.value !== initial };
}

export function buildAISettingsPanel(): HTMLElement {
  const container = h("div");

  // ---------- status header ----------
  const statusEl = h(".stat", h(".k", "Status"), h(".v", "Loading..."));
  const providerEl = h(".stat", h(".k", "Provider"), h(".v", "—"));
  const modelEl = h(".stat", h(".k", "Model"), h(".v", "—"));
  const cacheEl = h(".stat", h(".k", "Cache"), h(".v", "—"));

  // ---------- provider tab bar ----------
  const tabBar = h(".inline", { style: { gap: "var(--s-2)", marginBottom: "var(--s-3)", flexWrap: "wrap" } });
  const providerBlurb = h(".muted.mono", { style: { fontSize: "11px", marginBottom: "var(--s-4)" } });

  // Active provider state — initialised from config on load.
  let activeProvider: ProviderId = "local_gguf";

  function renderTabBar() {
    tabBar.innerHTML = "";
    for (const p of PROVIDERS) {
      const isActive = p.id === activeProvider;
      tabBar.appendChild(
        h(`button.btn.sm${isActive ? ".primary" : ""}`, {
          type: "button",
          onclick: () => {
            activeProvider = p.id;
            renderTabBar();
            renderProviderPanel();
          },
        }, p.label),
      );
    }
    const meta = PROVIDERS.find((p) => p.id === activeProvider);
    providerBlurb.textContent = meta ? meta.blurb : "";
  }

  // ---------- panels per provider ----------
  const providerPanel = h("div");
  const enableToggle = h("input", { type: "checkbox" }) as HTMLInputElement;

  // Local fields ------------------------------------------------------
  const sizeSelect = h(
    "select.select",
    h("option", { value: "small" }, "Small — Gemma 4 E4B-it (~3 GB)"),
    h("option", { value: "medium", selected: true }, "Medium — Gemma 4 26B-A4B-it (~10 GB)"),
  ) as HTMLSelectElement;
  const nCtxInput = h("input.input.mono", { type: "number", min: "512", step: "512" }) as HTMLInputElement;
  const nGpuLayersInput = h("input.input.mono", { type: "number", min: "0", step: "1" }) as HTMLInputElement;
  const modelPathInput = h("input.input.mono", { type: "text", placeholder: "(optional override) /path/to/model.gguf" }) as HTMLInputElement;

  // Anthropic fields --------------------------------------------------
  let anthropicKey = passwordField("", "sk-ant-...");
  const anthropicModelSelect = h("select.select") as HTMLSelectElement;
  const anthropicModelHint = h(".muted.mono", { style: { fontSize: "11px" } }, "");

  // OpenAI fields -----------------------------------------------------
  let openaiKey = passwordField("", "sk-...");
  const openaiModelSelect = h("select.select") as HTMLSelectElement;
  const openaiModelHint = h(".muted.mono", { style: { fontSize: "11px" } }, "");
  const openaiBaseUrlInput = h("input.input.mono", {
    type: "text",
    placeholder: "https://api.openai.com (leave blank for default)",
  }) as HTMLInputElement;

  // OpenAI-compatible fields ------------------------------------------
  let httpKey = passwordField("", "(optional) bearer token");
  const httpBaseUrlInput = h("input.input.mono", {
    type: "text",
    placeholder: "http://localhost:11434/v1",
  }) as HTMLInputElement;
  const httpModelInput = h("input.input.mono", {
    type: "text",
    placeholder: "llama3.1:8b",
  }) as HTMLInputElement;

  // Test-connection helper — points at /ai/status which reflects the SAVED
  // config. If the user is editing fields without saving, the result reflects
  // the old state, not the form. Detect that and tell them clearly.
  const testBtn = (): HTMLButtonElement => h("button.btn.sm.ghost", {
    type: "button",
    onclick: async () => {
      try {
        const [status, savedConfig] = await Promise.all([getAIStatus(), getConfig()]);
        const savedProvider = (savedConfig.ai_provider as string | undefined)
          || (savedConfig.ai_backend as string | undefined)
          || "local_gguf";
        const formChanged = activeProvider !== savedProvider
          || anthropicKey.isDirty()
          || openaiKey.isDirty()
          || httpKey.isDirty();

        if (formChanged) {
          toast(
            "UNSAVED CHANGES",
            `Form is set to "${activeProvider}" but the saved provider is "${savedProvider}". Click "Save AI settings" first, then re-test.`,
            "default",
          );
          return;
        }

        const ok = !!status.available;
        const provider = (status.provider as string | undefined) || activeProvider;
        toast(
          ok ? "OK" : "UNAVAILABLE",
          ok
            ? `Provider "${provider}" reachable.`
            : `Provider "${provider}" is configured but not reachable. Check the API key and model name.`,
          ok ? "success" : "error",
        );
      } catch (e) {
        toast("ERROR", String((e as Error).message), "error");
      }
    },
  }, "Test connection") as HTMLButtonElement;

  function field(label: string, ...kids: (HTMLElement | string)[]): HTMLElement {
    return h(".field", h("label.label", label), ...kids);
  }

  /** Make sure `select` has an <option> with the given value, preserving the
   *  current selection when refreshing the list. If the saved id isn't in the
   *  options yet, prepend it as "(saved) <id>" so the user always sees what
   *  the server has stored. */
  function ensureSavedOption(select: HTMLSelectElement, savedId: string): void {
    if (!savedId) return;
    const has = Array.from(select.options).some((o) => o.value === savedId);
    if (!has) {
      const opt = h("option", { value: savedId }, `(saved) ${savedId}`) as HTMLOptionElement;
      select.insertBefore(opt, select.firstChild);
    }
    select.value = savedId;
  }

  /** Replace the dropdown's options with a fresh list, preserving selection. */
  function setSelectOptions(
    select: HTMLSelectElement,
    models: { id: string; display_name: string }[],
    keepSelected: string,
  ): void {
    select.innerHTML = "";
    for (const m of models) {
      const label = m.display_name && m.display_name !== m.id ? `${m.display_name} (${m.id})` : m.id;
      select.appendChild(h("option", { value: m.id }, label));
    }
    if (keepSelected) ensureSavedOption(select, keepSelected);
  }

  /** Hit /ai/models for the given provider, using the *current form values*
   *  (so the user can preview a key before saving). Updates the matching
   *  dropdown + hint in place. */
  async function refreshModels(provider: "anthropic" | "openai" | "openai_compatible"): Promise<void> {
    const select = provider === "anthropic" ? anthropicModelSelect : openaiModelSelect;
    const hint = provider === "anthropic" ? anthropicModelHint : openaiModelHint;
    const keep = select.value;
    // Use the form's value if the user has typed/pasted a fresh key; the
    // backend falls back to the saved key when we send empty string.
    const apiKey =
      provider === "anthropic"
        ? (anthropicKey.isDirty() ? anthropicKey.input.value : "")
        : provider === "openai"
        ? (openaiKey.isDirty() ? openaiKey.input.value : "")
        : (httpKey.isDirty() ? httpKey.input.value : "");
    const baseUrl = provider === "openai" ? openaiBaseUrlInput.value : "";

    hint.textContent = "Fetching models…";
    try {
      const result = await listAIModels(provider, apiKey, baseUrl);
      setSelectOptions(select, result.models, keep);
      hint.textContent =
        result.source === "live"
          ? `${result.models.length} models from provider · refreshed`
          : result.source === "no_credentials"
          ? "Add an API key to fetch the live list. Showing well-known defaults."
          : result.source === "fallback"
          ? `Could not reach provider — showing defaults. (${result.error || ""})`.trim()
          : `Showing defaults (${result.source}).`;
    } catch (e) {
      hint.textContent = `Refresh failed: ${(e as Error).message}`;
    }
  }

  function refreshBtn(provider: "anthropic" | "openai"): HTMLButtonElement {
    return h("button.btn.sm.ghost", {
      type: "button",
      onclick: () => void refreshModels(provider),
      title: "Re-fetch from provider",
    }, "Refresh") as HTMLButtonElement;
  }

  function renderProviderPanel() {
    providerPanel.innerHTML = "";
    if (activeProvider === "local_gguf") {
      providerPanel.appendChild(
        h("div",
          field("Model size", sizeSelect),
          field("Context window (n_ctx)", nCtxInput),
          field("GPU layers (n_gpu_layers, 0 = CPU only)", nGpuLayersInput),
          field("Model path override", modelPathInput),
          h(".inline", { style: { marginTop: "var(--s-3)" } }, testBtn()),
        ),
      );
    } else if (activeProvider === "anthropic") {
      providerPanel.appendChild(
        h("div",
          field("API key", anthropicKey.wrap,
            h(".muted.mono", { style: { fontSize: "11px", marginTop: "var(--s-1)" } },
              "Stored server-side. Leave field as-is to keep the existing key."),
          ),
          field("Model",
            h(".inline", { style: { gap: "var(--s-2)" } },
              anthropicModelSelect,
              refreshBtn("anthropic"),
            ),
            anthropicModelHint,
          ),
          h(".inline", { style: { marginTop: "var(--s-3)" } }, testBtn()),
        ),
      );
    } else if (activeProvider === "openai") {
      providerPanel.appendChild(
        h("div",
          field("API key", openaiKey.wrap,
            h(".muted.mono", { style: { fontSize: "11px", marginTop: "var(--s-1)" } },
              "Stored server-side. Leave field as-is to keep the existing key."),
          ),
          field("Model",
            h(".inline", { style: { gap: "var(--s-2)" } },
              openaiModelSelect,
              refreshBtn("openai"),
            ),
            openaiModelHint,
          ),
          field("Base URL (optional)", openaiBaseUrlInput,
            h(".muted.mono", { style: { fontSize: "11px", marginTop: "var(--s-1)" } },
              "Leave blank to use api.openai.com."),
          ),
          h(".inline", { style: { marginTop: "var(--s-3)" } }, testBtn()),
        ),
      );
    } else {
      // openai_compatible
      providerPanel.appendChild(
        h("div",
          field("Base URL", httpBaseUrlInput,
            h(".muted.mono", { style: { fontSize: "11px", marginTop: "var(--s-1)" } },
              "Examples: http://localhost:11434/v1 (Ollama), http://localhost:8000/v1 (vLLM)."),
          ),
          field("Model", httpModelInput),
          field("API key (optional)", httpKey.wrap),
          h(".inline", { style: { marginTop: "var(--s-3)" } }, testBtn()),
        ),
      );
    }
  }

  // ---------- actions ----------
  const clearBtn = h("button.btn.sm.danger", { type: "button", onclick: () => doClear() }, "Clear cache");
  const saveBtn = h("button.btn.sm.primary", { type: "button", onclick: () => doSave() }, "Save AI settings");

  async function doClear() {
    try {
      const result = await clearAICache();
      toast("CACHE CLEARED", `${result.cleared} entries removed`, "success");
      loadStatus();
    } catch (e) {
      toast("ERROR", String((e as Error).message), "error");
    }
  }

  async function doSave() {
    try {
      const config = await getConfig();
      config.ai_enabled = enableToggle.checked;
      config.ai_provider = activeProvider;
      // Local fields
      config.ai_model_size = sizeSelect.value;
      const nCtx = parseInt(nCtxInput.value, 10);
      if (!Number.isNaN(nCtx)) config.ai_n_ctx = nCtx;
      const nGpu = parseInt(nGpuLayersInput.value, 10);
      if (!Number.isNaN(nGpu)) config.ai_n_gpu_layers = nGpu;
      config.ai_model_path = modelPathInput.value;
      // Anthropic
      config.ai_anthropic_model = anthropicModelSelect.value || "claude-haiku-4-5";
      config.ai_anthropic_api_key = anthropicKey.isDirty() ? anthropicKey.input.value : "";
      // OpenAI
      config.ai_openai_model = openaiModelSelect.value || "gpt-4o-mini";
      config.ai_openai_base_url = openaiBaseUrlInput.value;
      config.ai_openai_api_key = openaiKey.isDirty() ? openaiKey.input.value : "";
      // OpenAI-compatible
      config.ai_http_base_url = httpBaseUrlInput.value;
      config.ai_http_model = httpModelInput.value;
      config.ai_http_api_key = httpKey.isDirty() ? httpKey.input.value : "";

      await putConfig(config);
      toast("SAVED", "AI settings updated", "success");
      // Reload everything so the masked-key inputs reset to the new server
      // state and dirty-tracking starts fresh.
      loadStatus();
    } catch (e) {
      toast("ERROR", String((e as Error).message), "error");
    }
  }

  function rebuildPasswordField(
    holder: { wrap: HTMLElement; input: HTMLInputElement; isDirty: () => boolean },
    initial: string,
    placeholder: string,
  ): typeof holder {
    const fresh = passwordField(initial, placeholder);
    holder.wrap.replaceWith(fresh.wrap);
    holder.wrap = fresh.wrap;
    holder.input = fresh.input;
    holder.isDirty = fresh.isDirty;
    return holder;
  }

  async function loadStatus() {
    try {
      const [status, config] = await Promise.all([getAIStatus(), getConfig()]);

      const available = status.available as boolean;
      const enabled = status.enabled as boolean;
      const loaded = status.model_loaded as boolean;
      const modelPath = (status.model_path as string) || "";
      const cache = (status.cache || {}) as Record<string, unknown>;
      const provider = (status.provider as string | undefined)
        || (config.ai_provider as string | undefined)
        || (config.ai_backend as string | undefined)
        || "local_gguf";

      statusEl.querySelector(".v")!.textContent = enabled
        ? (available ? (loaded ? "Loaded" : "Available") : "Not configured")
        : "Disabled";

      providerEl.querySelector(".v")!.textContent = provider;

      modelEl.querySelector(".v")!.textContent = modelPath
        ? modelPath.split("/").pop() || modelPath
        : (config.ai_anthropic_model || config.ai_openai_model || config.ai_http_model || "—");

      cacheEl.querySelector(".v")!.textContent =
        `${cache.entries || 0} entries · ${Math.round(((cache.size_bytes as number) || 0) / 1024)} KB`;

      enableToggle.checked = enabled;
      sizeSelect.value = config.ai_model_size || "medium";
      nCtxInput.value = String(config.ai_n_ctx ?? 4096);
      nGpuLayersInput.value = String(config.ai_n_gpu_layers ?? 0);
      modelPathInput.value = config.ai_model_path || "";

      // Set the saved model into each dropdown (rendered options come from
      // refreshModels() — the saved value is preserved if present, else
      // selected as a one-off "(saved) <id>" option so it doesn't disappear
      // when the live list omits it.
      ensureSavedOption(anthropicModelSelect, config.ai_anthropic_model || "");
      ensureSavedOption(openaiModelSelect, config.ai_openai_model || "");
      openaiBaseUrlInput.value = config.ai_openai_base_url || "";
      httpBaseUrlInput.value = config.ai_http_base_url || "";
      httpModelInput.value = config.ai_http_model || "";

      // Kick off live model fetches in the background — these update the
      // dropdowns once the provider's API answers.
      void refreshModels("anthropic");
      void refreshModels("openai");

      // Rebuild password fields so their "initial" baseline is the masked
      // value just returned by the server — that's the value we treat as
      // "not dirty, send empty string".
      anthropicKey = rebuildPasswordField(anthropicKey, config.ai_anthropic_api_key || "", "sk-ant-...");
      openaiKey = rebuildPasswordField(openaiKey, config.ai_openai_api_key || "", "sk-...");
      httpKey = rebuildPasswordField(httpKey, config.ai_http_api_key || "", "(optional) bearer token");

      // Pick the active provider tab from config (only on first load — don't
      // override the user's tab choice on subsequent reloads).
      const cfgProvider = (config.ai_provider as ProviderId | undefined)
        || (isProvider(config.ai_backend) ? (config.ai_backend as ProviderId) : undefined);
      if (cfgProvider && !providerWasSetByUser) {
        activeProvider = cfgProvider;
      }
      renderTabBar();
      renderProviderPanel();
    } catch (e) {
      statusEl.querySelector(".v")!.textContent = "Error loading status";
    }
  }

  // Once the user clicks a tab, stop snapping back to config's provider on
  // re-loads (e.g. after Save).
  let providerWasSetByUser = false;
  const origRender = renderTabBar;
  // Wrap renderTabBar so any user click flips the flag — we re-assign tabBar
  // children there, so capturing onclick happens via a wrapping handler.
  tabBar.addEventListener("click", () => { providerWasSetByUser = true; }, true);
  void origRender;

  // Presets info (local_gguf only)
  const presetsEl = h(".list.bare", { style: { marginTop: "var(--s-4)" } });
  getAIPresets()
    .then((presets) => {
      for (const p of presets) {
        presetsEl.appendChild(
          h(".row", { style: { cursor: "default" } },
            h("span.badge.ai", aiIcon(14), p.name as string),
            h("div",
              h(".path", p.description as string),
              h(".sub.mono", p.download_command as string),
            ),
            h(".mono.muted", { style: { fontSize: "11px" } }, `~${p.size_gb} GB`),
          ),
        );
      }
    })
    .catch(() => {});

  const presetsBlock = h("div",
    h(".label.mt-5", "Local model presets"),
    presetsEl,
  );

  container.appendChild(
    h("div",
      h(".grid", statusEl, providerEl, modelEl, cacheEl),
      h(".mt-5",
        h("label.check", enableToggle, h("span", "Enable AI scenario generation")),
      ),
      h(".label.mt-4", "Provider"),
      tabBar,
      providerBlurb,
      providerPanel,
      h(".inline.mt-4", saveBtn, clearBtn),
      // Show presets always — they're informational and harmless if you're
      // on a remote provider; helps users understand what local needs.
      presetsBlock,
    ),
  );

  // First render — populated synchronously, then loadStatus() fills values.
  renderTabBar();
  renderProviderPanel();
  loadStatus();
  return container;
}

// Re-export so callers can narrow on AppConfig if needed.
export type { AppConfig };
