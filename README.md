# Specs Invaders

API Testing TUI that generates test plans from Swagger/OpenAPI specs. Parses your API spec, auto-generates functional and performance test cases (happy + sad path), and lets you browse, configure, execute, and report on them from the terminal with full mouse support.

No AI. Deterministic, rule-based test plan generation.

## Requirements

- Python 3.11+

## Install

The install script handles everything: finds the right Python, creates a venv, installs the package, sets up a CLI command, and creates a desktop shortcut.

```bash
git clone https://github.com/jmartinez5120/specs-agent.git
cd specs-agent
./install.sh
```

What it does:
- Detects Python 3.11+ (tries python3.13, 3.12, 3.11, python3)
- Creates a venv at `~/.specs-agent/venv`
- Installs the package with all dependencies
- Writes default config to `~/.specs-agent/config.yaml`
- Symlinks `specs-agent` to `/usr/local/bin` (or `~/.local/bin`)
- Creates a Desktop launcher (macOS `.command` / Linux `.desktop`)
- Adds a shell alias to `.zshrc` or `.bashrc`
- Verifies all dependencies import correctly

To uninstall:
```bash
./install.sh --uninstall
```

### Manual install (for development)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run

```bash
# Launch the TUI
specs-agent

# Or run as a module
python -m specs_agent

# Pre-load a spec file
specs-agent --spec /path/to/openapi.yaml

# Load from a URL
specs-agent --spec https://petstore.swagger.io/v2/swagger.json
```

## Features

### Spec Parsing
- OpenAPI 3.x and Swagger 2.0 (JSON or YAML)
- Local files, remote URLs, or paste from clipboard
- Full `$ref` resolution via prance (3-tier fallback for broken refs)
- `x-performance` SLA parsing (p95, p99, throughput/tps)
- Tag inference for tagless specs (e.g. Stripe)

### Test Plan Generation
- One test case per endpoint + documented response status code
- **Happy path** (2xx): enabled, with request body and schema assertions
- **Sad path** (4xx/5xx): disabled by default, with trigger data (bad IDs, empty bodies, missing fields)
- Inferred negative cases when spec has no documented errors
- Faker template variables (`{{$randomWord}}`, `{{$guid}}`, `{{$randomEmail}}`, etc.)
- Smart placeholders based on field names and types

### Functional Testing
- Async HTTP execution via httpx
- 6 assertion validators: status code, JSON schema, headers, response time, body contains
- Auth injection (bearer, API key, basic)
- Full request/response capture (URL, headers, body)
- Failure explanations per status code

### Performance Testing
- Concurrent load generation with asyncio + httpx
- HDR histograms for accurate percentile tracking (p50, p95, p99)
- Token bucket rate limiting for precise TPS control
- Staged ramp-up: `5:10, 20:30, 50:60` (5 users for 10s, then 20 for 30s, etc.)
- Window TPS + peak TPS real-time tracking
- SLA compliance checking from `x-performance` spec extensions
- Per-endpoint latency distribution chart with SLA threshold markers

### TUI
- Space Invaders themed with starfield background
- Full mouse + keyboard navigation
- Vim-style keybindings throughout
- Scan preview with endpoint diff on load
- Side-by-side spec refresh diff (detects new/removed/modified endpoints)
- Battle Plan editor with search, toggle, inspect, cURL copy
- Retry editor: edit URL, headers, body with faker autocomplete, then send
- Live execution screen with real-time progress and perf stats
- Results drill-down with failure explanations and inline retry
- History panel with past run stats

### Reports & Persistence
- HTML reports via Jinja2 (Space Invaders themed, SLA compliance section)
- Test plans saved to `~/.specs-agent/plans/` (YAML, auto-save)
- Run history saved to `~/.specs-agent/history/` (JSON)
- Plan merging on spec refresh (preserves user intel, picks up new fields)
- Config at `~/.specs-agent/config.yaml`

## Keyboard Shortcuts

### Global
| Key | Action |
|-----|--------|
| `Q` | Quit (with confirmation) |
| `F1` | Return to Welcome screen |
| `Escape` | Back / Close modal |

### Spec Browser
| Key | Action |
|-----|--------|
| `G` | Generate test plan |
| `R` | Refresh spec from source |

### Battle Plan (Plan Editor)
| Key | Action |
|-----|--------|
| `Space/E` | Toggle armed/disarmed |
| `A` | Toggle all |
| `D` | Inspect test case detail |
| `C` | Copy cURL to clipboard |
| `S` | Save plan |
| `R` | Regenerate plan from spec |
| `/` | Search/filter test cases |
| `V` | Show template variables |
| `H` | Show history panel |
| `F` | Fire (run tests) |

### Mission Detail (Test Case Editor)
| Key | Action |
|-----|--------|
| `T` | Try it (open retry editor) |
| `C` | Copy cURL |
| `Ctrl+S` | Save to plan |

### Retry Editor
| Key | Action |
|-----|--------|
| `Ctrl+S` | Send request |
| `S` | Save edits to plan |
| `{{$` | Trigger faker autocomplete in body |
| `Tab/Enter` | Accept autocomplete suggestion |

### Results
| Key | Action |
|-----|--------|
| `D` | Inspect selected result |
| `X` | Export report |

## Config

Configuration is stored at `~/.specs-agent/config.yaml`:

```yaml
version: 1
defaults:
  timeout_seconds: 30
  follow_redirects: true
  verify_ssl: true
performance:
  concurrent_users: 10
  duration_seconds: 30
  latency_p95_threshold_ms: 2000
auth_presets:
  - name: "Bearer Token"
    type: bearer
    value: ""
recent_specs: []
reports:
  output_dir: "~/.specs-agent/reports"
  format: "html"
theme: "dark"
```

## Tests

```bash
# Full suite (229 tests)
python -m pytest tests/ -v

# By category
python -m pytest tests/test_parsing/ -v       # Spec parsing
python -m pytest tests/test_models/ -v        # Data models
python -m pytest tests/test_config/ -v        # Config persistence
python -m pytest tests/test_execution/ -v     # Functional executor + validators
python -m pytest tests/test_integration/ -v   # End-to-end pipeline
python -m pytest tests/test_screens/ -v       # TUI screens (Textual pilot)
python -m pytest tests/test_reporting/ -v     # HTML report generation
python -m pytest tests/test_e2e_live.py -v    # Live API tests (needs server at localhost:8080)
```

## Documentation

The repo ships full architecture, infrastructure, and deployment docs under
[`docs/`](docs/):

- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — system design, data
  flow, components, AI provider abstraction, multi-tenancy posture
- **[docs/INFRASTRUCTURE.md](docs/INFRASTRUCTURE.md)** — K3s cluster
  topology, registry, DNS, storage, NetworkPolicy notes
- **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** — build images, push,
  apply manifests, verify, troubleshoot
- **[docs/SECURITY.md](docs/SECURITY.md)** — secret hygiene, what's in
  git and what isn't, threat model, gaps
- **[k8s/specs-agent/README.md](k8s/specs-agent/README.md)** — manifest-by-manifest reference
- **[CLAUDE.md](CLAUDE.md)** — implementation notes for code agents

## Deployment surfaces

```
local TUI ──── pip install -e . ────────────────── runs against ~/.specs-agent/
docker        docker compose up ───────────────── single host, full stack
K3s           kubectl apply -f k8s/specs-agent/ ── 6 pods across 5 nodes
```

The K3s deploy runs as a multi-replica web + API + Mongo (rs0) +
Elasticsearch stack with HPA, NetworkPolicy, and Traefik Ingress. See
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) to roll one out.

## Dependencies

- `textual` >= 1.0 — TUI framework with mouse support
- `prance` >= 23.6 — OpenAPI spec parsing + $ref resolution
- `httpx` >= 0.27 — Async HTTP client
- `hdrhistogram` >= 0.10 — HDR histograms for accurate percentiles
- `faker` >= 30.0 — Template variable generation
- `jsonschema` >= 4.20 — Response schema validation
- `jinja2` >= 3.1 — HTML report templates
- `pyyaml` >= 6.0 — Config and plan persistence
- `click` >= 8.1 — CLI entry point

## License

MIT
