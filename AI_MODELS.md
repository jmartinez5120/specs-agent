# AI Scenario Generation — Model Setup

specs-agent can use a local LLM (Google's Gemma 4 via llama-cpp-python) to generate contextually relevant test data for complex API fields. This is fully optional — without a model, everything falls back to Faker templates.

## Quick start

### Docker (model baked into the image)

```bash
# Just build and run — the model downloads during `docker build`
docker compose up --build
```

The Dockerfile automatically downloads the Gemma 4 medium model (~10 GB) during build. AI is enabled by default. To use the smaller model:

```bash
SPECS_AGENT_AI_MODEL_SIZE=small docker compose build
docker compose up
```

### Local install (auto-download on first use)

```bash
pip install -e ".[ai]"

# Enable AI in config
cat >> ~/.specs-agent/config.yaml << 'EOF'
ai:
  enabled: true
  model_size: medium
EOF

# The model downloads automatically when you first generate a plan.
# Or download explicitly:
python -m specs_agent.ai.download --size medium
```

## Model presets

| Preset | Model | GGUF file | Size | RAM needed | Speed (M1) |
|---|---|---|---|---|---|
| **small** | Gemma 4 E4B-it | `gemma-4-E4B-it-Q4_K_M.gguf` | ~3 GB | 8 GB+ | ~100 tok/s |
| **medium** (default) | Gemma 4 26B-A4B-it | `gemma-4-26B-A4B-it-UD-Q4_K_M.gguf` | ~10 GB | 16 GB+ | ~30 tok/s |

Both are instruction-tuned MoE (Mixture of Experts) models — only a subset of parameters are active per token, giving fast inference relative to their total parameter count. Apache 2.0 license.

### Download commands

**Medium (default, recommended):**
```bash
huggingface-cli download unsloth/gemma-4-26B-A4B-it-GGUF \
  gemma-4-26B-A4B-it-UD-Q4_K_M.gguf --local-dir ./models
```

**Small (faster, less RAM):**
```bash
huggingface-cli download unsloth/gemma-4-E4B-it-GGUF \
  gemma-4-E4B-it-Q4_K_M.gguf --local-dir ./models
```

## Configuration

### Docker (recommended)

Set these environment variables in `docker-compose.yml` or via `export` before `docker compose up`:

| Variable | Default | Description |
|---|---|---|
| `SPECS_AGENT_AI_ENABLED` | `0` | Set to `1` to enable AI generation |
| `SPECS_AGENT_AI_MODEL_SIZE` | `medium` | `small`, `medium`, or an absolute path to a custom GGUF |
| `SPECS_AGENT_AI_MODEL_PATH` | (empty) | Explicit model file path (overrides `MODEL_SIZE`) |
| `SPECS_AGENT_AI_N_CTX` | `2048` | Context window size (tokens) |
| `SPECS_AGENT_AI_N_GPU_LAYERS` | `0` | GPU layers to offload. `-1` = full offload (requires GPU) |

### Config file (`~/.specs-agent/config.yaml`)

```yaml
ai:
  enabled: true
  model_size: medium       # "small" | "medium" | "/path/to/custom.gguf"
  model_path: ""           # explicit override (takes precedence over model_size)
  n_ctx: 2048
  n_gpu_layers: 0
  cache_dir: "~/.specs-agent/ai-cache"
```

Environment variables always override config file values.

### Web UI

Open the Test Config modal (click "RUN TESTS →" from the Plan Editor) → navigate to the **AI** tab. From there you can:
- Toggle AI on/off
- Set the model size preset
- Specify a custom model path
- View model status (loaded, available, errors)
- See cache statistics and clear the cache

## Model search paths

The resolver looks for the GGUF file in these locations (first match wins):

1. `SPECS_AGENT_AI_MODEL_PATH` (explicit path)
2. `/models/{filename}` (Docker volume mount)
3. `~/.specs-agent/models/{filename}` (local user dir)
4. `./models/{filename}` (relative to CWD)

## How it works

### Two-tier generation

When generating a test plan, each request body field is classified:

- **Faker (fast path):** Email, date, UUID, IP, boolean, integer, and any field whose name matches a known pattern (phone, city, address, etc.)
- **LLM (slow path):** Fields with meaningful descriptions, enum values, domain-specific names

### Batch prompting

Instead of calling the LLM once per field, all AI-eligible fields for a single endpoint are batched into one prompt. This means a spec with 20 endpoints generates ~20 LLM calls, not hundreds.

### Caching

Responses are cached on disk (SHA-256 hash of field schemas + endpoint identity). The second plan generation for the same spec is instant. Cache is content-addressed — schema changes automatically produce new keys (no stale data).

Clear the cache via:
- Web UI: AI tab → "Clear Cache" button
- API: `POST /ai/cache/clear`
- CLI: `rm -rf ~/.specs-agent/ai-cache/`

### Fallback

If the LLM fails for any field (timeout, unparseable output, model crash), that field falls back to Faker. The plan always generates — AI failure is never fatal.

## Using a custom model

Any GGUF model compatible with llama-cpp-python works. Set the path via env var or config:

```bash
export SPECS_AGENT_AI_MODEL_SIZE=/models/my-custom-model.gguf
```

The prompt format assumes a standard instruction-following model. Non-instruction models may produce lower-quality or unparseable output (gracefully falls back to Faker).

## Troubleshooting

| Problem | Solution |
|---|---|
| "llama-cpp-python not installed" | `pip install 'specs-agent[ai]'` or rebuild Docker with AI enabled |
| "No model file found" | Download a GGUF and place it in `./models/` or set `SPECS_AGENT_AI_MODEL_PATH` |
| Model loads but output is bad | Try a different quantization (Q5_K_M, Q6_K, Q8_0) or a larger model |
| High memory usage | Switch to the `small` preset, or reduce `n_ctx` |
| GPU offload not working | Set `SPECS_AGENT_AI_N_GPU_LAYERS=-1` and ensure your GPU drivers + CUDA/Metal are installed |
| Cache growing too large | Clear via `POST /ai/cache/clear` or delete `~/.specs-agent/ai-cache/` |

## Without Docker (local install)

```bash
# Install with AI support
pip install -e ".[ai]"

# Download model
huggingface-cli download unsloth/gemma-4-26B-A4B-it-GGUF \
  gemma-4-26B-A4B-it-UD-Q4_K_M.gguf --local-dir ~/.specs-agent/models

# Enable in config
cat >> ~/.specs-agent/config.yaml << EOF
ai:
  enabled: true
  model_size: medium
EOF

# Run the TUI or API
specs-agent
# or
specs-agent-api
```
