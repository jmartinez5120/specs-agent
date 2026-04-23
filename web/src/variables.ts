// Faker-style template variables. Mirrors the Python backend's
// templating/variables.py so autocomplete and the Variables modal
// always show the same list.

export interface VariableDef {
  name: string;
  description: string;
  example: string;
}

export const VARIABLES: VariableDef[] = [
  { name: "$guid", description: "UUID v4", example: "a1b2c3d4-..." },
  { name: "$randomUuid", description: "UUID v4 (alias)", example: "a1b2c3d4-..." },
  { name: "$randomInt", description: "Random integer 0–999", example: "42" },
  { name: "$randomWord", description: "Random word", example: "apple" },
  { name: "$randomWords", description: "Random words (3)", example: "apple bread" },
  { name: "$randomFirstName", description: "First name", example: "Alice" },
  { name: "$randomLastName", description: "Last name", example: "Smith" },
  { name: "$randomFullName", description: "Full name", example: "Alice Smith" },
  { name: "$randomEmail", description: "Email address", example: "a@example.com" },
  { name: "$randomUserName", description: "Username", example: "alice42" },
  { name: "$randomPassword", description: "Password", example: "X9kq!…" },
  { name: "$randomCompanyName", description: "Company name", example: "Acme Inc" },
  { name: "$randomJobTitle", description: "Job title", example: "Engineer" },
  { name: "$randomPhoneNumber", description: "Phone number", example: "555-1234" },
  { name: "$randomCity", description: "City", example: "Portland" },
  { name: "$randomCountry", description: "Country", example: "France" },
  { name: "$randomStreetAddress", description: "Street address", example: "123 Main St" },
  { name: "$randomZipCode", description: "Postal code", example: "94103" },
  { name: "$randomUrl", description: "URL", example: "https://ex.com" },
  { name: "$randomDomain", description: "Domain name", example: "example.com" },
  { name: "$randomIp", description: "IPv4 address", example: "10.0.0.1" },
  { name: "$randomUserAgent", description: "Browser UA", example: "Mozilla/..." },
  { name: "$randomDate", description: "ISO date", example: "2026-04-15" },
  { name: "$randomDateTime", description: "ISO datetime", example: "2026-04-15T..." },
  { name: "$timestamp", description: "Unix seconds", example: "1760000000" },
  { name: "$timestampMs", description: "Unix millis", example: "1760000000000" },
  { name: "$isoTimestamp", description: "ISO timestamp", example: "2026-04-15T..." },
  { name: "$randomBoolean", description: "true | false", example: "true" },
  { name: "$randomFloat", description: "Random float", example: "3.14" },
  { name: "$randomLoremSentence", description: "Lorem sentence", example: "Lorem..." },
];

export function wrap(name: string): string {
  return `{{${name}}}`;
}

// --- Client-side resolver ---------------------------------------------------
// Mirrors a handful of the backend generators in templating/variables.py so
// the Try It modal can fire a live request without the backend runner.
// Not comprehensive — the backend is still the source of truth for real runs.

const WORDS = ["apple", "bread", "cloud", "delta", "echo", "falcon", "grape", "horizon", "ion", "jade"];
const FIRST = ["Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Heidi"];
const LAST = ["Smith", "Jones", "Brown", "Garcia", "Miller", "Davis", "Martinez"];
const CITIES = ["Portland", "Austin", "Lisbon", "Tokyo", "Madrid", "Berlin"];
const COUNTRIES = ["France", "Japan", "Portugal", "Spain", "Germany", "Chile"];
const COMPANIES = ["Acme Inc", "Globex", "Initech", "Umbrella", "Stark Industries"];
const JOBS = ["Engineer", "Designer", "Analyst", "Manager", "Researcher"];

function rand<T>(arr: T[]): T { return arr[Math.floor(Math.random() * arr.length)]; }
function randInt(max: number): number { return Math.floor(Math.random() * max); }
function pad(n: number, w: number): string { return String(n).padStart(w, "0"); }
function uuidv4(): string {
  const b = new Uint8Array(16);
  crypto.getRandomValues(b);
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const hex = [...b].map((x) => x.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10, 16).join("")}`;
}

const GENERATORS: Record<string, () => string> = {
  $guid: uuidv4,
  $randomuuid: uuidv4,
  $randomint: () => String(randInt(1000)),
  $randomword: () => rand(WORDS),
  $randomwords: () => `${rand(WORDS)} ${rand(WORDS)} ${rand(WORDS)}`,
  $randomfirstname: () => rand(FIRST),
  $randomlastname: () => rand(LAST),
  $randomfullname: () => `${rand(FIRST)} ${rand(LAST)}`,
  $randomemail: () => `${rand(FIRST).toLowerCase()}.${rand(LAST).toLowerCase()}@example.com`,
  $randomusername: () => `${rand(FIRST).toLowerCase()}${randInt(1000)}`,
  $randompassword: () => Math.random().toString(36).slice(2, 12) + "!A9",
  $randomcompanyname: () => rand(COMPANIES),
  $randomjobtitle: () => rand(JOBS),
  $randomphonenumber: () => `555-${pad(randInt(10000), 4)}`,
  $randomcity: () => rand(CITIES),
  $randomcountry: () => rand(COUNTRIES),
  $randomstreetaddress: () => `${randInt(9999)} Main St`,
  $randomzipcode: () => pad(randInt(100000), 5),
  $randomurl: () => `https://example.com/${rand(WORDS)}`,
  $randomdomain: () => `${rand(WORDS)}.example.com`,
  $randomip: () => `${randInt(255)}.${randInt(255)}.${randInt(255)}.${randInt(255)}`,
  $randomuseragent: () => "Mozilla/5.0 (compatible; specs-agent/0.1)",
  $randomdate: () => new Date().toISOString().slice(0, 10),
  $randomdatetime: () => new Date().toISOString(),
  $timestamp: () => String(Math.floor(Date.now() / 1000)),
  $timestampms: () => String(Date.now()),
  $isotimestamp: () => new Date().toISOString(),
  $randomboolean: () => (Math.random() < 0.5 ? "true" : "false"),
  $randomfloat: () => (Math.random() * 100).toFixed(4),
  $randomloremsentence: () => "Lorem ipsum dolor sit amet.",
};

const TEMPLATE_RE = /\{\{\s*(\$[a-zA-Z0-9_]+)\s*\}\}/g;

export function resolveString(s: string): string {
  return s.replace(TEMPLATE_RE, (_m, name: string) => {
    const gen = GENERATORS[name.toLowerCase()];
    return gen ? gen() : _m;
  });
}

export function resolveTemplates<T>(value: T): T {
  if (typeof value === "string") return resolveString(value) as T;
  if (Array.isArray(value)) return value.map((v) => resolveTemplates(v)) as T;
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[resolveString(k)] = resolveTemplates(v);
    }
    return out as T;
  }
  return value;
}
