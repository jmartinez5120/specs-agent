// Retry editor modal — send a live request with editable URL, headers,
// query params, and body. Mirrors the TUI retry editor. Faker variables
// in fields are left as-is (the backend's resolve_value() would handle
// them in a real run; the manual TRY IT here sends them literally).

import { proxyRequest } from "../api";
import { h } from "../dom";
import { openModal } from "../modal";
import { store } from "../state";
import { toast } from "../toast";
import type { TestCase } from "../types";
import { resolveString, resolveTemplates } from "../variables";

export function openRetryEditor(
  tc: TestCase,
  baseUrl: string,
  authType: string,
  authValue: string,
): () => void {
  const methodSel = h(
    "select.select",
    { style: { minWidth: "120px" } },
    ...["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"].map((m) =>
      h("option", { value: m, selected: m === tc.method }, m),
    ),
  ) as HTMLSelectElement;

  // Environment selector — populated from the spec's `servers` list. The
  // currently-active base URL is pre-selected. Switching env rewrites the
  // URL input to keep the same path + query string but swap the origin.
  const specServers = (store.state.spec?.servers || []) as { url: string; description?: string }[];
  const envOptions = specServers.length
    ? specServers
    : [{ url: baseUrl, description: "Active" }];
  const envSel = h("select.select",
    { style: { minWidth: "160px" } },
    ...envOptions.map((srv, i) =>
      h("option", {
        value: srv.url,
        selected: srv.url === baseUrl || (!specServers.length && i === 0),
      }, srv.description ? `${srv.description} — ${srv.url}` : srv.url),
    ),
  ) as HTMLSelectElement;

  const initialUrl = buildUrl(envSel.value || baseUrl, tc);
  const urlInput = h("input.input", {
    type: "text",
    value: initialUrl,
    style: { flex: "1" },
  }) as HTMLInputElement;

  // When the env changes, swap the origin on the URL input, preserving the
  // path + query that the user may have edited.
  let lastEnv = envSel.value;
  envSel.addEventListener("change", () => {
    const current = urlInput.value;
    const oldOrigin = lastEnv.replace(/\/$/, "");
    const newOrigin = envSel.value.replace(/\/$/, "");
    if (current.startsWith(oldOrigin)) {
      urlInput.value = newOrigin + current.slice(oldOrigin.length);
    } else {
      // Fallback: rebuild from the test case against the new env.
      urlInput.value = buildUrl(envSel.value, tc);
    }
    lastEnv = envSel.value;
  });

  const queryArea = h("textarea.textarea", {
    style: { minHeight: "64px" },
  }, JSON.stringify(tc.query_params || {}, null, 2)) as HTMLTextAreaElement;

  const headersArea = h("textarea.textarea", {
    style: { minHeight: "96px" },
  }, JSON.stringify(buildHeaders(tc, authType, authValue), null, 2)) as HTMLTextAreaElement;

  const bodyArea = h("textarea.textarea", {
    style: { minHeight: "180px" },
  }, tc.body ? JSON.stringify(tc.body, null, 2) : "") as HTMLTextAreaElement;

  // --- Response pane ---
  const statusEl = h("span.badge", "—");
  const statusTextEl = h("span.mono.muted", "");
  const timeEl = h("span.mono.muted", "—");
  const finalUrlEl = h("span.mono.muted", { style: { fontSize: "11px", wordBreak: "break-all" } }, "");

  const preStyle = {
    padding: "var(--s-3)",
    background: "var(--bg-2, var(--bg-muted))",
    borderRadius: "var(--r-2)",
    fontSize: "12px",
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
    overflow: "auto",
  } as const;

  const respHeadersEl = h("pre.mono", { style: { ...preStyle, maxHeight: "160px" } }, "—");
  const respBodyEl = h("pre.mono", { style: { ...preStyle, maxHeight: "320px" } }, "Press SEND to fire the request.");
  const errorEl = h("div", {
    style: {
      display: "none",
      padding: "var(--s-3)",
      border: "1px solid var(--danger, #c55)",
      borderRadius: "var(--r-2)",
      color: "var(--danger, #c55)",
      fontSize: "12px",
      marginTop: "var(--s-2)",
    },
  });

  const sendBtn = h("button.btn.primary", { onclick: () => send() }, "SEND ▶") as HTMLButtonElement;

  async function send() {
    sendBtn.disabled = true;
    sendBtn.textContent = "SENDING…";
    statusEl.textContent = "…";
    statusEl.className = "badge skipped";
    statusTextEl.textContent = "";
    errorEl.style.display = "none";

    const method = methodSel.value;
    let url = urlInput.value.trim();
    let query: Record<string, string> = {};
    let headers: Record<string, string> = {};
    let body: unknown = null;
    try {
      query = queryArea.value.trim() ? JSON.parse(queryArea.value) : {};
    } catch (e) {
      toast("QUERY PARSE", String((e as Error).message), "error");
      sendBtn.disabled = false;
      sendBtn.textContent = "SEND ▶";
      return;
    }
    try {
      headers = JSON.parse(headersArea.value || "{}");
    } catch (e) {
      toast("HEADERS PARSE", String((e as Error).message), "error");
      sendBtn.disabled = false;
      sendBtn.textContent = "SEND ▶";
      return;
    }
    try {
      body = bodyArea.value.trim() ? JSON.parse(bodyArea.value) : null;
    } catch (e) {
      toast("BODY PARSE", String((e as Error).message), "error");
      sendBtn.disabled = false;
      sendBtn.textContent = "SEND ▶";
      return;
    }

    // Resolve faker/template variables ({{$guid}}, {{$randomInt}}, …)
    // before firing so the request goes out with real values.
    url = resolveString(url);
    query = resolveTemplates(query);
    headers = resolveTemplates(headers);
    body = resolveTemplates(body);

    // Merge query params into URL if user typed some in the Query box.
    if (Object.keys(query).length) {
      const sep = url.includes("?") ? "&" : "?";
      url = url + sep + new URLSearchParams(query as Record<string, string>).toString();
    }
    finalUrlEl.textContent = `${method} ${url}`;

    try {
      const res = await proxyRequest({ method, url, headers, body });
      timeEl.textContent = `${res.elapsed_ms}ms`;
      if (res.ok && typeof res.status_code === "number") {
        const code = res.status_code;
        statusEl.textContent = String(code);
        statusEl.className = `badge ${code >= 200 && code < 300 ? "passed" : "failed"}`;
        statusTextEl.textContent = res.reason_phrase || "";
        const entries = Object.entries(res.headers || {}).sort(([a], [b]) => a.localeCompare(b));
        respHeadersEl.textContent = entries.length
          ? entries.map(([k, v]) => `${k}: ${v}`).join("\n")
          : "(none)";
        const bodyVal = res.body;
        if (bodyVal === null || bodyVal === undefined || bodyVal === "") {
          respBodyEl.textContent = "(empty body)";
        } else if (typeof bodyVal === "string") {
          respBodyEl.textContent = bodyVal || "(empty body)";
        } else {
          respBodyEl.textContent = JSON.stringify(bodyVal, null, 2);
        }
      } else {
        statusEl.textContent = "ERR";
        statusEl.className = "badge error";
        statusTextEl.textContent = "";
        respHeadersEl.textContent = "—";
        respBodyEl.textContent = "";
        errorEl.style.display = "";
        errorEl.textContent = res.error || "Request failed.";
      }
    } catch (e) {
      statusEl.textContent = "ERR";
      statusEl.className = "badge error";
      statusTextEl.textContent = "";
      timeEl.textContent = "—";
      respHeadersEl.textContent = "—";
      respBodyEl.textContent = "";
      errorEl.style.display = "";
      errorEl.textContent = `Proxy call failed: ${String((e as Error).message)}`;
    } finally {
      sendBtn.disabled = false;
      sendBtn.textContent = "SEND ▶";
    }
  }

  const sectionLabel = (txt: string) =>
    h("div", {
      style: {
        fontSize: "11px",
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.08em",
        color: "var(--muted)",
        margin: "var(--s-3) 0 var(--s-2)",
      },
    }, txt);

  // Two-column body: left = request editor, right = response viewer.
  const leftCol = h("div", {
    style: {
      display: "flex", flexDirection: "column",
      minHeight: "0", overflowY: "auto", paddingRight: "var(--s-2)",
    },
  },
    sectionLabel("Request"),
    h(".inline", { style: { gap: "var(--s-2)", marginBottom: "var(--s-2)" } },
      h("span.muted", { style: { fontSize: "11px", minWidth: "40px" } }, "Env"),
      envSel,
    ),
    h(".inline", { style: { gap: "var(--s-2)", marginBottom: "var(--s-2)" } }, methodSel, urlInput),
    sectionLabel("Query params (JSON)"),
    queryArea,
    sectionLabel("Headers (JSON)"),
    headersArea,
    sectionLabel("Body (JSON)"),
    bodyArea,
  );

  const rightCol = h("div", {
    style: {
      display: "flex", flexDirection: "column",
      minHeight: "0", overflowY: "auto", paddingLeft: "var(--s-2)",
      borderLeft: "1px solid var(--border)",
    },
  },
    h(".inline", { style: { gap: "var(--s-2)", flexWrap: "wrap", marginBottom: "var(--s-2)" } },
      h("span", { style: { fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--muted)" } }, "Response"),
      h("span.flex-1"),
      statusEl, statusTextEl, timeEl,
    ),
    finalUrlEl,
    errorEl,
    sectionLabel("Response headers"),
    respHeadersEl,
    sectionLabel("Response body"),
    respBodyEl,
  );

  const bodyEl = h("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: "var(--s-4)",
      height: "100%",
      minHeight: "0",
    },
  }, leftCol, rightCol);

  const saveToPlan = h("button.btn", {
    onclick: () => {
      try {
        tc.method = methodSel.value;
        tc.headers = JSON.parse(headersArea.value || "{}");
        tc.query_params = queryArea.value.trim() ? JSON.parse(queryArea.value) : {};
        tc.body = bodyArea.value.trim() ? JSON.parse(bodyArea.value) : null;
        toast("SAVED", "Back into the plan", "success");
      } catch (e) {
        toast("PARSE ERROR", String((e as Error).message), "error");
      }
    },
  }, "SAVE TO PLAN");

  const close = openModal({
    title: "Try It",
    body: bodyEl,
    actions: [sendBtn, saveToPlan],
    maxWidth: "min(96vw, 1500px)",
    fixedSize: true,
  });
  return close;
}

function buildUrl(baseUrl: string, tc: TestCase): string {
  let path = tc.endpoint_path;
  for (const [k, v] of Object.entries(tc.path_params)) {
    path = path.replaceAll(`{${k}}`, String(v));
  }
  return `${baseUrl.replace(/\/$/, "")}${path}`;
}

function buildHeaders(
  tc: TestCase,
  authType: string,
  authValue: string,
): Record<string, string> {
  const out: Record<string, string> = { ...tc.headers };
  if (authType === "bearer" && authValue) {
    out["Authorization"] = `Bearer ${authValue}`;
  } else if (authType === "api_key" && authValue) {
    out["X-API-Key"] = authValue;
  } else if (authType === "basic" && authValue) {
    out["Authorization"] = `Basic ${btoa(authValue)}`;
  }
  return out;
}
