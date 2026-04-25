// Modal helper — builds the backdrop, animates in/out via motion helpers.

import { h } from "./dom";
import { modalIn } from "./motion";

export interface ModalOptions {
  title: string;
  body: HTMLElement | string;
  actions?: HTMLElement[];
  onClose?: () => void;
  wide?: boolean;
  maxWidth?: string;
  // When true, the modal itself does not scroll — the caller is expected to
  // manage internal scrolling. Useful for fixed-size layouts with nested panes.
  fixedSize?: boolean;
  // When false, clicking the backdrop does NOT close the modal — user must
  // press ESC or click an explicit action (e.g. Cancel). Defaults to true.
  dismissOnBackdrop?: boolean;
}

export function openModal(opts: ModalOptions): () => void {
  const closeBtn = h(
    "button.close",
    { "aria-label": "close", onclick: () => close() },
    "✕",
  );
  const head = h(
    ".modal-h",
    h("span.accent", { style: { width: "3px", height: "14px", background: "linear-gradient(180deg,var(--accent),var(--accent-2))", borderRadius: "2px" } }),
    h("h3", opts.title),
    closeBtn,
  );

  const bodyEl =
    typeof opts.body === "string"
      ? h("div", { html: opts.body })
      : opts.body;

  const actionsEl = opts.actions?.length
    ? h(".modal-actions", ...opts.actions)
    : null;

  const modal = h(
    ".modal",
    head,
    bodyEl,
    actionsEl || document.createTextNode(""),
  );
  // Default: wide + fixed size so every popup has consistent dimensions and
  // no internal scrolling. Callers can override via maxWidth / fixedSize:false.
  const defaultWidth = "min(96vw, 1400px)";
  modal.style.maxWidth = opts.maxWidth || (opts.wide ? "min(92vw, 1100px)" : defaultWidth);
  const fixed = opts.fixedSize !== false;
  if (fixed) {
    modal.style.overflow = "hidden";
    modal.style.display = "flex";
    modal.style.flexDirection = "column";
    modal.style.height = "min(88vh, 900px)";
    modal.style.width = modal.style.maxWidth;
    (bodyEl as HTMLElement).style.flex = "1 1 0";
    (bodyEl as HTMLElement).style.minHeight = "0";
    (bodyEl as HTMLElement).style.overflow = "hidden";
  }

  const backdrop = h(".modal-backdrop", modal);
  const dismissOnBackdrop = opts.dismissOnBackdrop !== false;
  if (dismissOnBackdrop) {
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) close();
    });
  }

  const keyHandler = (e: KeyboardEvent) => {
    if (e.key === "Escape") close();
  };
  document.addEventListener("keydown", keyHandler);

  document.body.appendChild(backdrop);
  modalIn(backdrop, modal);

  let closed = false;
  function close() {
    if (closed) return;
    closed = true;
    document.removeEventListener("keydown", keyHandler);
    // Tiny CSS fade so the disappearance isn't jarring, but not dependent on
    // anime.js's complete callback (which has been unreliable here).
    backdrop.style.transition = "opacity 140ms ease";
    backdrop.style.opacity = "0";
    window.setTimeout(() => {
      backdrop.remove();
      opts.onClose?.();
    }, 160);
  }

  return close;
}
