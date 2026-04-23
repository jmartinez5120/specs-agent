// Test case detail modal — edits a single TestCase.
// Includes an assertion editor, a "VARS" button that opens the variables
// modal, and a "TRY IT" button that opens the retry editor.

import { aiBadge, aiFieldIndicator } from "../ai-icon";
import { copyCurl } from "../curl";
import { h } from "../dom";
import { openModal } from "../modal";
import { toast } from "../toast";
import type { Assertion, TestCase } from "../types";
import { openRetryEditor } from "./retry-editor";
import { openVariablesModal } from "./variables";

const ASSERTION_TYPES = [
  "status_code",
  "response_schema",
  "response_contains",
  "header_present",
  "header_value",
  "response_time_ms",
];

export function openTestCaseDetail(
  tc: TestCase,
  onSave: (updated: TestCase) => void,
  baseUrl: string,
  authType: string,
  authValue: string,
): () => void {
  // Deep-clone so Cancel reverts cleanly
  const working: TestCase = JSON.parse(JSON.stringify(tc));

  const nameInput = textInput(working.name, (v) => (working.name = v));
  const descInput = textareaInput(working.description || "", (v) => (working.description = v), 60);
  const pathInput = textareaInput(
    JSON.stringify(working.path_params, null, 2),
    () => {}, // parsed on save
    70,
  );
  const queryInput = textareaInput(
    JSON.stringify(working.query_params, null, 2),
    () => {},
    70,
  );
  const headersInput = textareaInput(
    JSON.stringify(working.headers, null, 2),
    () => {},
    70,
  );
  // Per-case user variables — merged with plan.global_variables at execution
  // time (local wins on key collision). Referenced in any field as {{name}}.
  const localVarsInput = textareaInput(
    JSON.stringify(working.local_variables || {}, null, 2),
    () => {},
    70,
  );
  const bodyInput = textareaInput(
    working.body ? JSON.stringify(working.body, null, 2) : "",
    () => {},
    180,
  );

  // --- Assertions editor ---
  const assertList = h(".list", { style: { marginTop: "var(--s-2)" } });
  function renderAssertions() {
    assertList.innerHTML = "";
    working.assertions.forEach((a, idx) => {
      assertList.appendChild(assertionRow(a, idx));
    });
    if (working.assertions.length === 0) {
      assertList.appendChild(
        h(".muted.mono", { style: { fontSize: "11px", padding: "var(--s-2)" } },
          "No assertions"),
      );
    }
  }

  function assertionRow(a: Assertion, idx: number): HTMLElement {
    const typeSel = h(
      "select.select",
      {
        style: { minWidth: "180px" },
        onchange: (e: Event) => {
          working.assertions[idx].type = (e.target as HTMLSelectElement).value;
        },
      },
      ...ASSERTION_TYPES.map((t) => h("option", { value: t, selected: a.type === t }, t)),
    );
    const expected = textInput(
      typeof a.expected === "object" ? JSON.stringify(a.expected) : String(a.expected ?? ""),
      (v) => {
        // Try to parse as JSON first (for schemas / numbers), fall back to string
        try {
          working.assertions[idx].expected = JSON.parse(v);
        } catch {
          working.assertions[idx].expected = v;
        }
      },
    );
    expected.style.minWidth = "200px";
    const del = h(
      "button.btn.sm.danger",
      {
        onclick: () => {
          working.assertions.splice(idx, 1);
          renderAssertions();
        },
      },
      "×",
    );
    return h(
      ".row",
      { style: { cursor: "default", gridTemplateColumns: "auto 1fr auto" } },
      typeSel,
      expected,
      del,
    );
  }

  const addAssertBtn = h(
    "button.btn.sm",
    {
      onclick: () => {
        working.assertions.push({
          type: "status_code",
          expected: 200,
          description: "",
        });
        renderAssertions();
      },
    },
    "+ ADD ASSERTION",
  );

  renderAssertions();

  // --- AI field indicators ---
  const aiIndicator = working.ai_fields?.length
    ? aiFieldIndicator(working.ai_fields)
    : null;

  // --- Layout ---
  const body = h("div",
    h(".inline", { style: { marginBottom: "var(--s-4)" } },
      h("span.method." + working.method, working.method),
      h("span.mono", working.endpoint_path),
      h("span.flex-1"),
      working.ai_fields?.length
        ? aiBadge(working.ai_fields.length)
        : null as unknown as HTMLElement,
      h("button.btn.sm", {
        onclick: () => {
          syncFromInputs();
          copyCurl(working, baseUrl, authType, authValue)
            .then(() => toast("COPIED", "cURL copied", "success", 1500));
        },
      }, "cURL"),
      h("button.btn.sm", { onclick: () => openVariablesModal() }, "VARS"),
      h("button.btn.sm.primary", {
        onclick: () => {
          // Pass the current in-progress edits through
          syncFromInputs();
          openRetryEditor(working, baseUrl, authType, authValue);
        },
      }, "TRY IT"),
    ),
    field("Name", nameInput),
    field("Description", descInput),
    field("Path params (JSON)", pathInput),
    field("Query params (JSON)", queryInput),
    field("Headers (JSON)", headersInput),
    field(
      "Local variables (JSON) — overrides plan global_variables at run time",
      localVarsInput,
    ),
    h(".field",
      h("div",
        h("label.label", { style: { display: "inline" } }, "Body (JSON)"),
        aiIndicator || document.createTextNode(""),
      ),
      bodyInput,
    ),
    h(".label.mt-4", "Assertions"),
    assertList,
    addAssertBtn,
  );

  function syncFromInputs(): boolean {
    try {
      working.name = nameInput.value;
      working.description = descInput.value;
      working.path_params = JSON.parse(pathInput.value || "{}");
      working.query_params = JSON.parse(queryInput.value || "{}");
      working.headers = JSON.parse(headersInput.value || "{}");
      working.local_variables = JSON.parse(localVarsInput.value || "{}");
      working.body = bodyInput.value.trim() ? JSON.parse(bodyInput.value) : null;
      return true;
    } catch (e) {
      toast("PARSE ERROR", String((e as Error).message), "error");
      return false;
    }
  }

  const saveBtn = h("button.btn.primary", {
    onclick: () => {
      if (!syncFromInputs()) return;
      Object.assign(tc, working);
      onSave(tc);
      toast("UPDATED", "Test case saved", "success");
      close();
    },
  }, "Save");

  const cancelBtn = h("button.btn.ghost", { onclick: () => close() }, "Cancel");

  const close = openModal({
    title: `Edit — ${working.name || working.endpoint_path}`,
    body,
    actions: [cancelBtn, saveBtn],
    wide: true,
  });

  return close;
}

// -- tiny form helpers ---

function textInput(value: string, oninput: (v: string) => void): HTMLInputElement {
  return h("input.input", {
    type: "text",
    value,
    oninput: (e: Event) => oninput((e.target as HTMLInputElement).value),
  }) as HTMLInputElement;
}

function textareaInput(
  value: string,
  oninput: (v: string) => void,
  minHeight: number,
): HTMLTextAreaElement {
  const el = h(
    "textarea.textarea",
    {
      style: { minHeight: `${minHeight}px` },
      oninput: (e: Event) => oninput((e.target as HTMLTextAreaElement).value),
    },
    value,
  ) as HTMLTextAreaElement;
  return el;
}

function field(label: string, input: HTMLElement): HTMLElement {
  return h(".field", h("label.label", label), input);
}
