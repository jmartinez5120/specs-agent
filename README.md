# specs-agent

API Testing TUI that generates test plans from Swagger/OpenAPI specs. Parses your API spec, auto-generates functional and performance test cases, and lets you browse, configure, and run them from the terminal — with full mouse support.

No AI. Deterministic, rule-based test plan generation.

## Requirements

- Python 3.11+

## Install

The install script handles everything: finds the right Python, creates a venv, installs the package, sets up a CLI command, and creates a desktop shortcut.

```bash
git clone https://github.com/your-org/specs-agent.git
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

## Usage

1. **Welcome Screen** — Enter a file path or URL to your OpenAPI/Swagger spec, then click **Load Spec** (or press Enter).
2. **Spec Browser** — Browse endpoints grouped by tag in the tree panel. Click any endpoint to view its parameters, request body, and responses in the detail panel. Click **Generate Test Plan** when ready.
3. **Plan Editor** — Review auto-generated test cases in the table. Click a row to toggle it on/off. Use keyboard shortcuts or buttons:
   - `Space` — Toggle selected test case
   - `A` — Toggle all on/off
   - **Run Tests** — Execute the plan (MVP 2)

Navigate back at any time with `Escape` or the **Back** button. Press `F1` to return to the Welcome screen. Press `Q` to quit.

Mouse clicks work on all buttons, tree nodes, and table rows.

## Test Plan Generation Rules

The plan generator creates test cases from your spec without AI:

- One test case per endpoint + documented response status code
- **2xx responses**: enabled by default, assert status code + response schema (if defined)
- **4xx/5xx responses**: disabled by default, assert status code only
- **GET/DELETE/HEAD**: no request body; required path/query params populated from examples, defaults, or enum values
- **POST/PUT/PATCH**: minimal request body generated from the request body schema
- Test cases with required parameters that have no example/default are marked **needs input**

## Config

Configuration is stored at `~/.specs-agent/config.yaml`. It is created automatically on first run. You can edit it to set defaults:

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

## Run Tests

```bash
# Run the full test suite
python -m pytest tests/ -v

# Run a specific suite
python -m pytest tests/test_parsing/ -v
python -m pytest tests/test_models/ -v
python -m pytest tests/test_config/ -v
python -m pytest tests/test_integration/ -v
python -m pytest tests/test_screens/ -v
```

## Project Structure

```
src/specs_agent/
  app.py                  # Main Textual app, screen navigation, shared state
  config.py               # Config load/save (~/.specs-agent/config.yaml)
  models/
    spec.py               # ParsedSpec, Endpoint, Parameter, ResponseSpec
    plan.py               # TestPlan, TestCase, Assertion
  parsing/
    loader.py             # Load specs via prance (resolves $ref)
    extractor.py          # Normalize OpenAPI v2/v3 into ParsedSpec
    plan_generator.py     # Auto-generate TestPlan from ParsedSpec
  screens/
    welcome.py            # File/URL input, recent specs
    spec_browser.py       # Endpoint tree + detail panel
    plan_editor.py        # DataTable with enable/disable toggle
  widgets/
    endpoint_tree.py      # Tree widget grouped by tag
    method_badge.py       # Colored HTTP method labels
tests/
  test_models/            # Unit tests for data models
  test_config/            # Unit tests for config load/save/roundtrip
  test_parsing/           # Unit tests for loader, extractor, plan generator
  test_integration/       # End-to-end pipeline tests (load -> extract -> plan)
  test_screens/           # TUI screen tests via Textual pilot
  fixtures/               # Petstore v2/v3 and minimal spec fixtures
```

## Supported Spec Formats

- OpenAPI 3.x (JSON or YAML)
- Swagger 2.0 (JSON or YAML)
- Local files or remote URLs
- Specs with `$ref` pointers (resolved automatically)

## License

MIT
