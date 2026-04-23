# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (editable with dev deps)
pip install -e ".[dev]"

# Run the TUI
specs-agent
python -m specs_agent
specs-agent --spec path/to/openapi.yaml

# Tests
python -m pytest tests/ -v                    # Full suite (229 tests)
python -m pytest tests/test_parsing/ -v       # Parsing unit tests
python -m pytest tests/test_models/ -v        # Data model tests
python -m pytest tests/test_config/ -v        # Config persistence tests
python -m pytest tests/test_integration/ -v   # End-to-end pipeline tests
python -m pytest tests/test_screens/ -v       # TUI screen tests (Textual pilot)
python -m pytest tests/test_e2e_live.py -v    # Live API tests (needs localhost:8080)
python -m pytest tests/path/to/test_file.py::TestClass::test_method -v  # Single test
```

No linter or formatter is configured.

## Architecture

### Data Flow

```
File/URL
  → parsing/loader.py          load_spec() via prance.ResolvingParser (resolves $ref)
                                _clear_prance_cache() before URL loads (prance caches in mutable defaults)
  → parsing/extractor.py       extract_spec() normalizes Swagger 2.0 / OpenAPI 3.x → ParsedSpec
                                Parses x-performance SLA (string/dict, tps/rps/throughput aliases)
  → parsing/plan_generator.py  generate_plan() deterministic rules → TestPlan
                                Happy path (2xx) + sad path (4xx/5xx) with trigger data
                                PUT/POST/PATCH always get request body (even non-2xx)
```

Models (`models/spec.py`, `models/plan.py`) are pure dataclasses with zero dependencies on other modules. Parsing depends on models. Screens depend on both. Nothing depends on screens.

### Search (Elasticsearch, real-time indexing)

Server-side search replaces the old client-side Fuse.js approach. The API never writes to Elasticsearch directly — all writes go through MongoDB, and a change-stream tailer mirrors them into ES as denormalized documents.

```
client  →  POST /specs/load        (writes to Mongo)
                     ↓
          Mongo change stream  →  Indexer.tail()  →  ES bulk upsert
                                                         ↓
client  →  POST /search       →   service.search()  →  ES _search + highlights
```

Package layout (`src/specs_agent/search/`):
- `client.py` — lazy singleton `AsyncElasticsearch`, reads `ELASTICSEARCH_URL`.
- `schema.py` — single index `specs_agent` with one mapping; standard analyzer plus a title-only `autocomplete_analyzer` (edge_ngram as search analyzer so "pet" matches "petstore" without ngram-bloating the index).
- `converters.py` — pure functions: `spec_to_docs`, `plan_to_test_case_docs`, `run_to_doc`. Every user-supplied string is HTML-escaped before indexing so ES highlight output (only `<mark>` tags around already-escaped content) is safe to render as innerHTML on the frontend.
- `indexer.py` — `Indexer.backfill()` scans all Mongo collections on startup if the index is empty; `Indexer.tail()` watches `specs`, `plans`, `history` change streams and mirrors each insert/update/replace/delete into ES. Cascading deletes use `{spec_id, kind}` filters (ES forbids `prefix` queries on `_id`).
- `service.py` — `search(q, kinds, limit)`: multi_match across `title^3 / subtitle^1.5 / haystack^1` with `fuzziness: AUTO`, `operator: AND`, `minimum_should_match: 75%`, highlights on title + subtitle. Empty query returns empty (never dump the full index).

Lifecycle (`api/app.py` FastAPI lifespan):
- On startup **in mongo-storage mode only**: ping ES (fail fast if unreachable), ensure the index exists, backfill if empty, launch `Indexer.tail()` as a background task.
- On shutdown: cancel tailer, close ES + Motor clients.
- File-storage mode: `POST /search` returns 503 — there are no change streams to drive the index.

Mongo requirement: change streams need a replica set, which is why `docker-compose.yml` runs Mongo with `--replSet rs0` and a `mongo-init` sidecar that calls `rs.initiate()` once.

### TUI Screen Navigation

Textual app uses a push/pop screen stack. Screens communicate upward via custom `Message` subclasses; the `App` class catches them with `@on(ScreenType.MessageType)` decorators and orchestrates transitions.

```
WelcomeScreen  --SpecSelected-->  App._load_spec() [@work thread]
                                    --> App._on_spec_loaded()
                                        --> push ScanPreviewModal
                                            --> push SpecBrowserScreen

SpecBrowserScreen  --GeneratePlanRequested-->  App.on_generate_plan()
                                                --> merge with saved plan
                                                --> push PlanEditorScreen

PlanEditorScreen  --RunTestsRequested-->  App.on_run_tests()
                                           --> push TestConfigModal
                                               --> push ExecutionScreen
                                                   --> push ResultsScreen
```

Shared state lives on the App as `reactive` attributes (`parsed_spec`, `test_plan`, `run_config`, `last_report`). Screens read from these; they don't mutate them directly.

### Key Patterns

- **Background spec loading**: `@work(thread=True, exclusive=True)` on `_load_spec()` prevents UI blocking. Returns to main thread via `self.call_from_thread()`.
- **Spec refresh**: `_refresh_spec_worker()` uses separate `group="refresh_spec"` to avoid conflicts with `_load_spec`. Clears prance's module-level URL cache before each fetch to get live data.
- **Plan merge on refresh**: `_merge_plans()` matches by test case name (not ID, since IDs are random UUIDs). `_merge_body()` starts with fresh body (new required fields) and overlays saved user edits. Plan auto-saved after refresh.
- **OpenAPI v2 vs v3 detection**: `extractor.py` checks for `"swagger"` key (v2) vs `"openapi"` key (v3). Handles differences in server URLs, body parameters, and response schema locations.
- **Plan generation rules**: One TestCase per endpoint+response code. 2xx enabled, 4xx/5xx disabled. Sad path triggers generated for 400/404/401/403/409 etc. Path params populated from example → default → enum[0] → faker placeholder. Request bodies generated recursively from JSON schema for ALL PUT/POST/PATCH (including non-2xx).
- **Faker template variables**: `{{$randomWord}}`, `{{$guid}}`, etc. stored in test case fields. Resolved at execution time via `resolve_value()`. Detail modal strips braces for display, re-wraps on save (case-insensitive match against `_GENERATORS`).
- **Performance executor**: HDR histograms (hdrhistogram) for percentiles, token bucket rate limiter for TPS control, staged ramp-up support, window/peak TPS tracking. Results deduplicated by method+endpoint.
- **Config persistence**: `AppConfig` dataclass round-trips through `~/.specs-agent/config.yaml` via `pyyaml`. Recent specs tracked with deduplication (max 10).
- **History storage**: Per-spec history at `~/.specs-agent/history/<spec_hash>/`. Auto-saved after each run.
- **Plan persistence**: Saved to `~/.specs-agent/plans/` as YAML. Auto-saved after intel edits, plan merges, and retry editor saves.

### Refresh Flow

```
[r] pressed → refresh_spec()
  → _refresh_spec_worker() [@work thread, group="refresh_spec"]
      → _clear_prance_cache()  # Critical: prance caches URLs in mutable default args
      → load_spec() + extract_spec()
  → _on_refresh_complete()
      → RefreshDiffModal (side-by-side old vs new)
          → [enter] APPLY: update parsed_spec, auto-regenerate plan, push fresh browser
          → [esc] CANCEL: discard, stay on current screen
```

### Retry Editor Flow

```
[t] TRY IT (from DetailModal or ResultDetailModal)
  → RetryEditorModal (editable URL, headers, query params, body)
      → Body TextArea with {{$ autocomplete (arrow/tab to accept)
      → [ctrl+s] SEND: resolve_value() templates, fire httpx request, show response
      → [s] SAVE TO PLAN: parse fields back to test case, save plan to disk
      → On close: DetailModal refreshes its Input fields from updated tc
```

### TUI Screen Testing

Screen tests use Textual's async pilot: `async with app.run_test(size=(120, 40)) as pilot`. Push screens with `await app.push_screen(screen)`, then query widgets via `app.screen.query_one()`. Always `await pilot.pause()` after push/pop to let the screen mount.

## Important Implementation Notes

- **Prance URL caching**: `prance.util.url.fetch_url` and `fetch_url_text` use mutable default `cache={}` which persists for the process lifetime. MUST call `_clear_prance_cache()` before URL loads to get fresh data.
- **Test case IDs are random UUIDs**: Generated fresh on each plan creation. Use `tc.name` for stable matching across plan regenerations.
- **_GENERATORS keys are lowercase**: `_apply_edits()` must use case-insensitive matching when re-wrapping faker function names.
- **TextArea vs Input**: TextArea (body editor) doesn't have built-in suggestions. Autocomplete is implemented manually with `TextArea.Changed` events and a Static overlay.
- **`@work(thread=False)`**: Used for async execution (httpx) — runs in the event loop, no `call_from_thread` needed. `@work(thread=True)` used for blocking I/O (prance/file loads).

## MVP Status

- **MVP 1** (done): Parse specs, browse endpoints in TUI, generate test plans, Space Invaders theme, starfield background, template variables (Faker), detail/variables popup modals, vim-style keybindings
- **MVP 2** (done): Functional test execution (httpx), performance load testing (HDR histograms, token bucket rate limiting, staged ramp-up, TPS tracking), test config modal (auth, SSL, timeouts, perf settings, stages), live execution screen with progress bar, results screen with drill-down, validators (status code, JSON schema, headers, response time, body contains)
- **MVP 3** (done): HTML reports (Jinja2, Space Invaders themed), report export modal, save/load plans to YAML, cURL copy (clipboard), relative URL resolution, path-based tag inference for tagless specs, spec refresh with side-by-side diff, retry editor modal with autocomplete, plan auto-save
- **MVP 4** (done): AI-powered scenario generator — two-tier data gen (Faker + Gemma 4 via llama-cpp-python/GGUF), hash-based caching, offline/air-gapped, domain-specific test scenarios. Model presets: small (E4B-it, 3GB) and medium (26B-A4B-it, 10GB). Batch prompting per endpoint, content-addressed disk cache. See `AI_MODELS.md` for setup.
- **MVP 5** (planned): Auth & token management — OAuth2 (client_credentials + auth_code/PKCE), API key, basic auth, custom HTTP request chains, auto-refresh, env var secrets, in-memory-only tokens
- **MVP 6** (partially done): History storage works, auto-save after runs, history panel in plan editor. Regression detection, trend tracking, diff between runs not yet implemented.
- **MVP 7** (planned): Server mode — headless daemon, scheduled test execution (cron-style), webhook/Slack/email alerts on regression, REST API for status/results, Docker image
- **MVP 8** (in progress): Dockerized + Web UI + MongoDB engine
  - `docker-compose.yml` stack: `specs-agent` service + `mongodb` service
  - Backend/UI split: extract a **core engine** (parsing, plan generation, execution, history, templating) behind a Python API layer. TUI and Web UI are both thin clients over the same engine — no business logic in either UI.
  - Engine API: in-process Python interface (for TUI) + HTTP/WebSocket layer (for Web UI). Same DTOs, same validators, same contract.
  - **Web UI**: browser-rendered client with **full feature parity** to the TUI — spec browser, plan editor, detail/retry modals, execution screen with live progress, results with drill-down, HTML reports, refresh diff, history panel. Every flow the TUI has must exist in the web version. **Visual style is futuristic, NOT retro/TUI** — drop the Space Invaders aesthetic in the web client. Uses **[anime.js](https://animejs.com)** for motion: staggered list reveals, morphing SVG transitions between screens, animated progress/HDR histograms, timeline-driven execution playback, and micro-interactions on hover/focus.
  - **MongoDB storage**: replaces file-based persistence (`~/.specs-agent/`) when running in Docker. Collections: `specs`, `plans`, `configs`, `history`, `reports`. Local file mode remains the default outside Docker.
  - Storage abstraction: introduce a `Storage` interface with `FileStorage` (current) and `MongoStorage` implementations — engine picks one based on env/config.
  - Docker image builds the engine + both UIs; `docker compose up` launches MongoDB + the app with web UI exposed on a port.
  - **Search: Elasticsearch + real-time indexing**. `docker-compose.yml` also runs ES 8.x (single-node, security disabled for dev) and Mongo is a single-node replica set (`rs0`) with a one-shot `mongo-init` sidecar. All writes land in Mongo; a change-stream tailer mirrors them into ES. See the "Search" subsection above for the package layout. The `POST /search` route only activates in mongo-storage mode — file storage returns 503.
- **MVP 9** (planned): External MongoDB support — connection string config, auth, TLS, ability to point the dockerized engine at an existing MongoDB cluster instead of the bundled one.

## File Map (key files)

```
src/specs_agent/
  app.py                         # Main App: screen nav, refresh_spec, merge_plans, _specs_differ
  parsing/loader.py              # _clear_prance_cache(), 3-tier fallback (Resolving→Base→raw)
  parsing/plan_generator.py      # generate_plan(), _generate_negative_cases(), _infer_error_responses()
  execution/performance.py       # HDR histograms, _TokenBucket, staged ramp-up, PerformanceExecutor
  models/config.py               # RampStage, PerformanceConfig (target_tps, stages), TestRunConfig
  screens/retry_editor_modal.py  # Editable request editor with body autocomplete
  screens/refresh_diff_modal.py  # Side-by-side spec diff on refresh
  screens/detail_modal.py        # Test case editor with faker autocomplete, _apply_edits, _strip_braces
  screens/result_detail_modal.py # Result drill-down, _find_test_case (ID + name fallback)
  screens/scan_preview.py        # Initial scan preview + _diff_endpoint()
  templating/variables.py        # _GENERATORS dict (lowercase keys), resolve_value(), list_variables()
  search/client.py               # AsyncElasticsearch singleton, ELASTICSEARCH_URL
  search/schema.py               # INDEX_NAME, mapping, ensure_index/reset_index
  search/converters.py           # spec_to_docs, plan_to_test_case_docs, run_to_doc (HTML-escape)
  search/indexer.py              # Indexer: backfill + Mongo change-stream tailer
  search/service.py              # search(q, kinds, limit): multi_match + highlights
```
