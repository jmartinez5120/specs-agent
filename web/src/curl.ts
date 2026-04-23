// cURL command builder — generates a copy-ready cURL from a TestCase.

import type { TestCase } from "./types";

export function buildCurl(
  tc: TestCase,
  baseUrl: string,
  authType = "none",
  authValue = "",
): string {
  let path = tc.endpoint_path;
  for (const [k, v] of Object.entries(tc.path_params || {})) {
    path = path.replaceAll(`{${k}}`, String(v));
  }

  let url = `${baseUrl.replace(/\/$/, "")}${path}`;
  const qp = tc.query_params || {};
  const qs = Object.entries(qp).map(([k, v]) => `${k}=${v}`).join("&");
  if (qs) url += `?${qs}`;

  const parts: string[] = ["curl"];

  if (tc.method !== "GET") parts.push(`-X ${tc.method}`);
  parts.push(shellQuote(url));

  if (authType === "bearer" && authValue)
    parts.push(`-H ${shellQuote(`Authorization: Bearer ${authValue}`)}`);
  else if (authType === "api_key" && authValue)
    parts.push(`-H ${shellQuote(`Authorization: ${authValue}`)}`);
  else if (authType === "basic" && authValue)
    parts.push(`-u ${shellQuote(authValue)}`);

  for (const [k, v] of Object.entries(tc.headers || {})) {
    parts.push(`-H ${shellQuote(`${k}: ${v}`)}`);
  }

  if (tc.body != null) {
    if (typeof tc.body === "object") {
      parts.push(`-H ${shellQuote("Content-Type: application/json")}`);
      parts.push(`-d ${shellQuote(JSON.stringify(tc.body))}`);
    } else {
      parts.push(`-d ${shellQuote(String(tc.body))}`);
    }
  }

  return parts.join(" \\\n  ");
}

export async function copyCurl(
  tc: TestCase,
  baseUrl: string,
  authType = "none",
  authValue = "",
): Promise<string> {
  const cmd = buildCurl(tc, baseUrl, authType, authValue);
  try {
    await navigator.clipboard.writeText(cmd);
  } catch {
    // Fallback: select a hidden textarea
    const ta = document.createElement("textarea");
    ta.value = cmd;
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
  return cmd;
}

function shellQuote(s: string): string {
  if (/^[a-zA-Z0-9_./:@=&?%-]+$/.test(s)) return s;
  return `'${s.replace(/'/g, "'\\''")}'`;
}
