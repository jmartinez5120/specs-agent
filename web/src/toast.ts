// Toasts — notification strip in the bottom-right corner.

import { h } from "./dom";
import { toastIn, toastOut } from "./motion";

let container: HTMLElement;

export function initToasts(): void {
  container = h(".toasts");
  document.body.appendChild(container);
}

export function toast(
  title: string,
  msg: string,
  kind: "default" | "success" | "error" = "default",
  timeout = 4200,
): void {
  if (!container) initToasts();
  const el = h(
    `.toast${kind === "default" ? "" : "." + kind}`,
    h(".title", title),
    h(".msg", msg),
  );
  container.appendChild(el);
  toastIn(el);
  setTimeout(() => {
    toastOut(el, () => el.remove());
  }, timeout);
}
