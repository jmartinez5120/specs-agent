// Full-screen progress overlay for long-running operations like plan generation.

import { h } from "./dom";

export interface ProgressOverlay {
  update(step: string, progress: number, detail?: string, model?: string): void;
  done(): void;
  error(msg: string): void;
  el: HTMLElement;
  onCancel: (() => void) | null;
}

export function createProgressOverlay(title: string): ProgressOverlay {
  const stepEl = h("div", { style: { color: "var(--text)", fontSize: "14px", fontWeight: "500" } }, "Starting...");
  const detailEl = h("div", { style: { color: "var(--text-muted)", fontSize: "12px", marginTop: "4px" } });
  const pctEl = h("div", {
    style: {
      fontFamily: "var(--font-mono)", fontSize: "32px", fontWeight: "700",
      color: "var(--primary)", marginBottom: "var(--s-4)",
    },
  }, "0%");
  const fill = h("div", {
    style: {
      height: "100%", width: "0%", background: "var(--primary)",
      borderRadius: "999px", transition: "width 300ms ease",
    },
  });
  const bar = h("div", {
    style: {
      width: "100%", height: "8px", background: "var(--bg-muted)",
      borderRadius: "999px", overflow: "hidden", marginBottom: "var(--s-5)",
      border: "1px solid var(--border)",
    },
  }, fill);

  const modelEl = h("div", {
    style: {
      display: "none", padding: "6px 12px", marginBottom: "var(--s-4)",
      background: "rgba(139, 92, 246, 0.1)", borderRadius: "var(--r-2)",
      border: "1px solid rgba(139, 92, 246, 0.25)",
      fontSize: "12px", color: "#a78bfa",
      fontFamily: "var(--font-mono)",
    },
  });

  const logEl = h("div", {
    style: {
      maxHeight: "260px", overflow: "auto", fontFamily: "var(--font-mono)",
      fontSize: "12px", lineHeight: "1.7", color: "var(--text-dim)",
      marginTop: "var(--s-5)", background: "var(--bg-muted)",
      borderRadius: "var(--r-2)", padding: "var(--s-4)",
      whiteSpace: "pre-wrap", wordBreak: "break-word",
    },
  });

  const cancelBtn = h("button", {
    style: {
      display: "inline-flex", alignItems: "center", justifyContent: "center",
      gap: "6px", padding: "8px 20px", borderRadius: "var(--r-2)",
      border: "1px solid var(--danger)", background: "transparent",
      color: "var(--danger)", fontSize: "13px", fontWeight: "500",
      cursor: "pointer", marginTop: "var(--s-5)",
    },
    onclick: () => {
      if (result.onCancel) result.onCancel();
    },
  }, "Cancel");

  const card = h("div", {
    style: {
      background: "var(--bg-subtle)", border: "1px solid var(--border)",
      borderRadius: "var(--r-3)", padding: "var(--s-7)",
      maxWidth: "760px", width: "90vw", boxShadow: "var(--shadow-lg)",
    },
  },
    h("div", { style: { fontSize: "12px", color: "var(--text-muted)", fontWeight: "600", marginBottom: "var(--s-4)", textTransform: "uppercase" } }, title),
    pctEl,
    bar,
    modelEl,
    stepEl,
    detailEl,
    logEl,
    cancelBtn,
  );

  const el = h("div", {
    style: {
      position: "fixed", inset: "0", zIndex: "150",
      background: "rgba(10, 15, 25, 0.8)", backdropFilter: "blur(4px)",
      display: "grid", placeItems: "center",
    },
  }, card);

  const logs: string[] = [];

  const result: ProgressOverlay = {
    el,
    onCancel: null,
    update(step: string, progress: number, detail?: string, model?: string) {
      stepEl.textContent = step;
      pctEl.textContent = `${Math.round(progress)}%`;
      fill.style.width = `${Math.min(100, progress)}%`;
      if (detail) detailEl.textContent = detail;
      if (model) {
        modelEl.textContent = `🤖 Model: ${model}`;
        modelEl.style.display = "";
      }
      logs.push(`[${Math.round(progress)}%] ${step}`);
      logEl.textContent = logs.slice(-15).join("\n");
      logEl.scrollTop = logEl.scrollHeight;
    },
    done() {
      fill.style.width = "100%";
      fill.style.background = "var(--success)";
      pctEl.textContent = "100%";
      pctEl.style.color = "var(--success)";
      stepEl.textContent = "Done!";
      setTimeout(() => el.remove(), 400);
    },
    error(msg: string) {
      fill.style.background = "var(--danger)";
      pctEl.style.color = "var(--danger)";
      stepEl.textContent = `Error: ${msg}`;
      stepEl.style.color = "var(--danger)";
      cancelBtn.style.display = "none";
      setTimeout(() => el.remove(), 3000);
    },
  };
  return result;
}
