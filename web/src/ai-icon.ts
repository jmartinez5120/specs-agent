// Reusable AI robot icon — used in plan rows, detail modal, AI settings.
// Renders an <img> pointing at the SVG in /public.

import { h } from "./dom";

export function aiIcon(size = 16): HTMLElement {
  return h("img", {
    src: "/ai-robot.svg",
    alt: "AI",
    style: {
      width: `${size}px`,
      height: `${size}px`,
      verticalAlign: "middle",
      flexShrink: "0",
    },
  });
}

export function aiBadge(count: number): HTMLElement {
  return h(
    "span.badge.ai",
    aiIcon(14),
    String(count),
  );
}

export function aiFieldIndicator(fields: string[]): HTMLElement {
  return h(
    "span.ai-indicator",
    aiIcon(14),
    `AI: ${fields.join(", ")}`,
  );
}
