// In-app confirmation dialog — replaces native confirm() with a styled modal.

import { h } from "./dom";
import { modalIn, modalOut } from "./motion";

export function confirmDialog(opts: {
  title: string;
  message: string;
  detail?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
}): Promise<boolean> {
  return new Promise((resolve) => {
    const msgEl = h("div", { style: { color: "var(--text)", fontSize: "14px", lineHeight: "1.6" } }, opts.message);
    const detailEl = opts.detail
      ? h("div", { style: { color: "var(--text-muted)", fontSize: "13px", marginTop: "var(--s-3)" } }, opts.detail)
      : null;

    const cancelBtn = h("button.btn.ghost", {
      onclick: () => close(false),
    }, opts.cancelLabel || "Cancel");

    const confirmBtn = h(
      `button.btn${opts.danger ? ".danger" : ".primary"}`,
      { onclick: () => close(true) },
      opts.confirmLabel || "Confirm",
    );

    const modal = h("div", {
      style: {
        background: "var(--bg-subtle)", border: "1px solid var(--border)",
        borderRadius: "var(--r-3)", padding: "var(--s-6)",
        maxWidth: "480px", width: "90vw", boxShadow: "var(--shadow-lg)",
        transform: "scale(0.96)",
      },
    },
      h("h3", { style: { margin: "0 0 var(--s-4)", fontSize: "16px", fontWeight: "600" } }, opts.title),
      msgEl,
      detailEl || document.createTextNode(""),
      h("div", {
        style: {
          display: "flex", gap: "var(--s-3)", justifyContent: "flex-end",
          marginTop: "var(--s-6)", paddingTop: "var(--s-4)",
          borderTop: "1px solid var(--border)",
        },
      }, cancelBtn, confirmBtn),
    );

    const backdrop = h("div", {
      style: {
        position: "fixed", inset: "0", background: "rgba(10, 15, 25, 0.72)",
        backdropFilter: "blur(4px)", zIndex: "200",
        display: "grid", placeItems: "center", opacity: "0",
      },
      onclick: (e: Event) => { if (e.target === backdrop) close(false); },
    }, modal);

    const keyHandler = (e: KeyboardEvent) => {
      if (e.key === "Escape") close(false);
      if (e.key === "Enter") close(true);
    };
    document.addEventListener("keydown", keyHandler);

    document.body.appendChild(backdrop);
    modalIn(backdrop, modal);

    function close(result: boolean) {
      document.removeEventListener("keydown", keyHandler);
      modalOut(backdrop, modal, () => {
        backdrop.remove();
        resolve(result);
      });
    }
  });
}
