// AI Settings tab — shows model status, cache stats, enable toggle,
// model size selector, and a cache clear button. Integrated as a tab
// in the Test Config modal.

import { aiIcon } from "../ai-icon";
import { clearAICache, getAIPresets, getAIStatus, getConfig, putConfig } from "../api";
import { h } from "../dom";
import { toast } from "../toast";

export function buildAISettingsPanel(): HTMLElement {
  const container = h("div");

  const statusEl = h(".stat", h(".k", "Status"), h(".v", "Loading..."));
  const modelEl = h(".stat", h(".k", "Model"), h(".v", "—"));
  const cacheEl = h(".stat", h(".k", "Cache"), h(".v", "—"));

  const enableToggle = h("input", { type: "checkbox" }) as HTMLInputElement;
  const sizeSelect = h(
    "select.select",
    h("option", { value: "small" }, "Small — Gemma 4 E4B-it (~3 GB)"),
    h("option", { value: "medium", selected: true }, "Medium — Gemma 4 26B-A4B-it (~10 GB)"),
  ) as HTMLSelectElement;

  const clearBtn = h(
    "button.btn.sm.danger",
    { onclick: () => doClear() },
    "Clear cache",
  );

  const saveBtn = h(
    "button.btn.sm.primary",
    { onclick: () => doSave() },
    "Save AI settings",
  );

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
      config.ai_model_size = sizeSelect.value;
      await putConfig(config);
      toast("SAVED", "AI settings updated", "success");
      loadStatus();
    } catch (e) {
      toast("ERROR", String((e as Error).message), "error");
    }
  }

  async function loadStatus() {
    try {
      const status = await getAIStatus();
      const available = status.available as boolean;
      const enabled = status.enabled as boolean;
      const loaded = status.model_loaded as boolean;
      const modelPath = (status.model_path as string) || "none";
      const cache = (status.cache || {}) as Record<string, unknown>;

      statusEl.querySelector(".v")!.textContent = enabled
        ? (available ? (loaded ? "🟢 Loaded" : "🟡 Available") : "🔴 Model not found")
        : "⚪ Disabled";

      modelEl.querySelector(".v")!.textContent = modelPath
        ? modelPath.split("/").pop() || modelPath
        : "Not configured";

      cacheEl.querySelector(".v")!.textContent =
        `${cache.entries || 0} entries · ${Math.round(((cache.size_bytes as number) || 0) / 1024)} KB`;

      enableToggle.checked = enabled;

      // Load config to get current model size
      const config = await getConfig();
      sizeSelect.value = config.ai_model_size || "medium";
    } catch (e) {
      statusEl.querySelector(".v")!.textContent = "⚠ Error loading status";
    }
  }

  // Presets info
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

  container.appendChild(
    h("div",
      h(".grid", statusEl, modelEl, cacheEl),
      h(".mt-5",
        h("label.check", enableToggle, h("span", "Enable AI scenario generation")),
      ),
      h(".field.mt-4",
        h("label.label", "Model size"),
        sizeSelect,
      ),
      h(".inline.mt-4", saveBtn, clearBtn),
      h(".label.mt-5", "Available presets"),
      presetsEl,
    ),
  );

  loadStatus();
  return container;
}
