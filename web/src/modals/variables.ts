// Variables modal — lists all faker-style template variables, click to
// copy. Triggered from the test-case detail modal.

import { h } from "../dom";
import { openModal } from "../modal";
import { toast } from "../toast";
import { VARIABLES, wrap } from "../variables";

export function openVariablesModal(): () => void {
  const search = h("input.input", {
    type: "text",
    placeholder: "Filter variables…",
    oninput: (e: Event) => renderList((e.target as HTMLInputElement).value),
  }) as HTMLInputElement;

  const listEl = h(".list", { style: { marginTop: "var(--s-3)", maxHeight: "58vh", overflow: "auto" } });

  function renderList(filter = "") {
    listEl.innerHTML = "";
    const q = filter.trim().toLowerCase();
    const filtered = VARIABLES.filter((v) =>
      !q || v.name.toLowerCase().includes(q) || v.description.toLowerCase().includes(q),
    );
    if (filtered.length === 0) {
      listEl.appendChild(
        h(".muted.center", { style: { padding: "var(--s-5)" } }, "No variables match"),
      );
      return;
    }
    for (const v of filtered) {
      const token = wrap(v.name);
      listEl.appendChild(
        h(".row", {
          onclick: async () => {
            try {
              await navigator.clipboard.writeText(token);
              toast("COPIED", token, "success", 1800);
            } catch {
              toast("COPY FAILED", "Clipboard unavailable", "error");
            }
          },
        },
          h("span.mono.accent", { style: { color: "var(--cyan)", minWidth: "180px" } }, token),
          h(
            "div",
            h(".path", v.description),
            h(".sub.mono", `→ ${v.example}`),
          ),
          h("span.muted.mono", { style: { fontSize: "10px" } }, "CLICK TO COPY"),
        ),
      );
    }
  }
  renderList();

  const body = h(
    "div",
    h("p.muted", { style: { marginTop: 0 } },
      "Template variables resolved at execution time. Use ",
      h("span.mono", "{{$guid}}"),
      " style tokens in any field."),
    search,
    listEl,
  );

  const close = openModal({
    title: "Template Variables",
    body,
    wide: true,
  });
  return close;
}
