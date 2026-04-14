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
python -m pytest tests/ -v                    # Full suite (122 tests)
python -m pytest tests/test_parsing/ -v       # Parsing unit tests
python -m pytest tests/test_models/ -v        # Data model tests
python -m pytest tests/test_config/ -v        # Config persistence tests
python -m pytest tests/test_integration/ -v   # End-to-end pipeline tests
python -m pytest tests/test_screens/ -v       # TUI screen tests (Textual pilot)
python -m pytest tests/path/to/test_file.py::TestClass::test_method -v  # Single test
```

No linter or formatter is configured.

## Architecture

### Data Flow

```
File/URL
  → parsing/loader.py        load_spec() via prance.ResolvingParser (resolves $ref)
  → parsing/extractor.py     extract_spec() normalizes Swagger 2.0 / OpenAPI 3.x → ParsedSpec
  → parsing/plan_generator.py  generate_plan() deterministic rules → TestPlan
```

Models (`models/spec.py`, `models/plan.py`) are pure dataclasses with zero dependencies on other modules. Parsing depends on models. Screens depend on both. Nothing depends on screens.

### TUI Screen Navigation

Textual app uses a push/pop screen stack. Screens communicate upward via custom `Message` subclasses; the `App` class catches them with `@on(ScreenType.MessageType)` decorators and orchestrates transitions.

```
WelcomeScreen  --SpecSelected-->  App._load_spec() [@work thread]
                                    --> App._on_spec_loaded()
                                        --> push SpecBrowserScreen

SpecBrowserScreen  --GeneratePlanRequested-->  App.on_generate_plan()
                                                --> push PlanEditorScreen

PlanEditorScreen  --RunTestsRequested-->  App.on_run_tests() [MVP 2]
```

Shared state lives on the App as `reactive` attributes (`parsed_spec`, `test_plan`). Screens read from these; they don't mutate them directly.

### Key Patterns

- **Background spec loading**: `@work(thread=True, exclusive=True)` on `_load_spec()` prevents UI blocking. Returns to main thread via `self.call_from_thread()`.
- **OpenAPI v2 vs v3 detection**: `extractor.py` checks for `"swagger"` key (v2) vs `"openapi"` key (v3). Handles differences in server URLs, body parameters, and response schema locations.
- **Plan generation rules**: One TestCase per endpoint+response code. 2xx enabled, 4xx/5xx disabled. Path params populated from example → default → enum[0] → placeholder. Request bodies generated recursively from JSON schema. `needs_input=True` when placeholders remain.
- **Config persistence**: `AppConfig` dataclass round-trips through `~/.specs-agent/config.yaml` via `pyyaml`. Recent specs tracked with deduplication (max 10).

### TUI Screen Testing

Screen tests use Textual's async pilot: `async with app.run_test(size=(120, 40)) as pilot`. Push screens with `await app.push_screen(screen)`, then query widgets via `app.screen.query_one()`. Always `await pilot.pause()` after push/pop to let the screen mount.

## MVP Status

- **MVP 1** (done): Parse specs, browse endpoints in TUI, generate test plans, Space Invaders theme, starfield background, template variables (Faker), detail/variables popup modals, vim-style keybindings
- **MVP 2** (done): Functional test execution (httpx), performance load testing (concurrent async), test config modal (auth, SSL, timeouts, perf settings), live execution screen with progress bar, results screen with drill-down, validators (status code, JSON schema, headers, response time, body contains)
- **MVP 3** (done): HTML reports (Jinja2, Space Invaders themed), report export modal, save/load plans to YAML, cURL copy (clipboard), relative URL resolution, path-based tag inference for tagless specs (e.g. Stripe)
- **MVP 4** (planned): AI-powered scenario generator — two-tier data gen (Faker + local LLM via llama-cpp-python/GGUF), hash-based caching, offline/air-gapped, domain-specific test scenarios
- **MVP 5** (planned): Auth & token management — OAuth2 (client_credentials + auth_code/PKCE), API key, basic auth, custom HTTP request chains, auto-refresh, env var secrets, in-memory-only tokens
- **MVP 6** (planned): Test run history — per-API result history stored to disk, trend tracking (pass rate, latency over time), diff between runs, regression detection, history browser TUI screen
- **MVP 7** (planned): Server mode — headless daemon that runs continuously, scheduled test execution (cron-style), webhook/Slack/email alerts on regression, REST API for status/results, Docker image, health dashboard endpoint
