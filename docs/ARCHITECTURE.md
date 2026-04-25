# Architecture

specs-agent is an OpenAPI-driven test platform: parse a spec → generate a
plan → execute (functional + perf) → store results → search history.
It runs three places: as a TUI on a developer's laptop, as a containerised
web app on a single host (`docker compose`), and as a multi-pod deployment
on Kubernetes (the K3s rollout in `k8s/specs-agent/`).

## High-level flow

```
┌──────────┐   spec URL/file    ┌────────────────────────┐
│   User   │ ─────────────────▶ │ Web UI / TUI           │
└──────────┘                    │ (browser, terminal)    │
                                └─────────┬──────────────┘
                                          │ REST / WebSocket
                                          ▼
                          ┌──────────────────────────────────┐
                          │  FastAPI engine (specs-agent-api)│
                          │  • parsing  → ParsedSpec         │
                          │  • plan_gen → TestPlan           │
                          │  • execution (functional + perf) │
                          │  • AI scenario gen (multi-prov.) │
                          └─┬──────────────┬─────────────┬──┘
                            │              │             │
                  ┌─────────▼─┐      ┌─────▼────┐   ┌────▼─────────┐
                  │  Mongo    │      │   ES     │   │ AI provider  │
                  │  (rs0)    │ ────▶│ search   │   │ (anthropic / │
                  │ specs,    │ chg- │ index    │   │  openai /    │
                  │ plans,    │ strm │          │   │  local GGUF) │
                  │ history   │      │          │   └──────────────┘
                  └───────────┘      └──────────┘
```

## Components

### Engine (`src/specs_agent/`)

Pure-Python core. Three layers, strictly one-way dependency:

```
models/  (dataclasses, no deps)
   ↑
parsing/ + execution/ + templating/ + ai/
   ↑
api/ (FastAPI thin shell) + screens/ (Textual TUI)
```

Notable modules:
- `parsing/loader.py` — `prance.ResolvingParser`, with a fix for prance's
  module-level URL cache (mutable default arg in `fetch_url`).
- `parsing/extractor.py` — normalises Swagger 2.0 + OpenAPI 3.x into
  `ParsedSpec`. Parses `x-performance` SLA hints.
- `parsing/plan_generator.py` — deterministic happy-path + sad-path rules.
  Optional AI augmentation per endpoint.
- `execution/functional.py` — assertion runner (status, schema, headers,
  body contains, response time).
- `execution/performance.py` — HDR histograms + token-bucket TPS limiter
  + staged ramp-up. Counts non-2xx responses as errors in the live
  "Errors" tile.
- `ai/generator.py` — provider-dispatching scenario generator. Providers
  are pluggable: `local_gguf` (llama-cpp-python), `anthropic`, `openai`,
  `openai_compatible` (Ollama / vLLM / DMR).

### API (`src/specs_agent/api/`)

FastAPI app. Stateless routes, persistent state lives in the injected
`Storage` layer.

Key surfaces:
- `GET/PUT /config` — app config. API keys masked on GET; empty string
  on PUT means "leave unchanged."
- `POST /specs/load`, `/plans/generate`, `/plans/save`, `GET /plans/{title}`
- `WS /ws/execute` — live execution event stream
- `WS /ws/generate` — streaming plan generation w/ AI progress
- `GET /ai/status` — backend availability, configured provider
- `POST /search` — Elasticsearch-backed (mongo storage mode only)
- `GET /history`, `/history/run`, `POST /reports/html`

### Storage (`src/specs_agent/engine/`)

Two implementations behind a common interface:

| Implementation | Used in              | State location                   |
|----------------|----------------------|----------------------------------|
| `FileStorage`  | TUI, local dev       | `~/.specs-agent/`                |
| `MongoStorage` | docker-compose / K8s | Mongo collections + ES index     |

Mongo is required for the change-stream → ES indexer that powers
`/search`. File mode 503s on `/search` and tells the user why.

### Search (`src/specs_agent/search/`)

API never writes to Elasticsearch. All writes land in Mongo; an
`Indexer` tails change streams on `specs`, `plans`, `history` and
mirrors them into a single `specs_agent` ES index. Documents are HTML-
escaped before indexing so highlight `<mark>` tags can be rendered as
innerHTML on the frontend.

### AI providers (`src/specs_agent/ai/`)

| Provider          | Backend module       | Use when                               |
|-------------------|----------------------|----------------------------------------|
| `local_gguf`      | `generator.py`       | Air-gapped, GPU-poor, privacy concerns |
| `anthropic`       | `anthropic_backend`  | Claude Messages API                    |
| `openai`          | `openai_backend`     | ChatGPT (gpt-4o, etc.)                 |
| `openai_compat.`  | `http_backend`       | Ollama, vLLM, Docker Model Runner      |

All four implement the same interface: `is_available()`, `chat_completion(...)`.
`AIGenerator._resolve_provider()` picks the active one; `_active_remote_backend()`
returns the matching client. Falls back to Faker for any field/scenario
that fails.

API keys are env-driven (`SPECS_AGENT_AI_*`) AND user-configurable via
`PUT /config`. Empty-string PUT preserves the stored key — see
`merge_config_preserving_secrets` in `api/converters.py`.

### Web UI (`web/`)

Vanilla TypeScript + Vite, no framework. Hand-rolled DOM helpers in
`web/src/dom.ts` (`h(tag, props, ...children)`). State store, router,
modal helper. Animations via anime.js for staggered list reveals,
progress bars, and screen transitions.

Routes:
- `/home` — recent specs + global search
- `/spec` — spec browser, plan editor, results, history (tabs)
- `/execution` — live run with WebSocket-driven progress
- `/results` — drill-down with 2-column REQUEST/RESPONSE layout

Modals: AI Settings (multi-provider with masked key handling),
Test Config (auth, perf), Detail (test case editor), Retry Editor
(fire ad-hoc requests), Refresh Diff, Regenerate Options.

## Data model

```
ParsedSpec
├── title, version, base_url
├── endpoints: list[Endpoint]
│      ├── method, path, parameters, request_body_schema
│      ├── responses: list[Response]
│      └── performance_sla?
└── raw_spec (the original JSON)

TestPlan
├── name, spec_title, base_url, created_at
├── test_cases: list[TestCase]
│      ├── method, endpoint_path, name, description
│      ├── path_params, query_params, headers, body
│      ├── assertions: list[Assertion]
│      └── ai_generated, ai_category, ai_fields
├── global_headers, auth_type, auth_value
└── performance_slas: dict[str, dict]

Report
├── total_tests, passed_tests, failed_tests, error_tests
├── pass_rate, total_duration_ms
├── results: list[TestResult]
│      ├── status_code, response_time_ms, status
│      ├── request_url, request_headers, request_body
│      ├── response_headers, response_body
│      ├── assertion_results: list[AssertionResult]
│      └── error_message
└── performance_results: list[PerformanceMetrics]
```

## Multi-tenancy posture (current → target)

**Today (shared mode):**
- One AppConfig (server-wide defaults), one Mongo, one set of API keys.
- All requests share state. The `X-User-Id` plumbing is present but
  resolves to `"local"` (or `SPECS_AGENT_DEFAULT_USER_ID`) on every
  request.

**Target (true multi-tenant, MVP-9):**
- OIDC proxy (oauth2-proxy → IdP) sets `X-User-Id` from a verified token.
- New `user_configs` Mongo collection: per-user overrides on a whitelisted
  set of fields (their own AI keys, model, theme).
- `GET /config` returns merged: `user_override ?? server_default`, masked.
- `PUT /config` writes to the user's overrides only.
- `GET/PUT /admin/config` writes server defaults (admin auth gate).
- Per-tenant namespaces in K8s, parameterised via Kustomize/Helm.

## See also

- [INFRASTRUCTURE.md](INFRASTRUCTURE.md) — K3s cluster, registry, network
- [DEPLOYMENT.md](DEPLOYMENT.md) — build, push, apply, verify
- [SECURITY.md](SECURITY.md) — secret handling, NetworkPolicy, what's not in git
- [../CLAUDE.md](../CLAUDE.md) — implementation-level notes for code agents
