#!/usr/bin/env bash
# specs-agent Docker installer
#
# Requires:
#   - Docker Desktop >= 4.44 (ships Docker Model Runner / `docker model` subcommand)
#   - Docker Model Runner enabled in Settings → Beta features
#
# Usage:  ./install.sh                 # defaults to Gemma 4 E4B-it Q4_K_M
#         MODEL=hf.co/... ./install.sh # override via env var
#         ./install.sh --no-ai         # skip model pull, disable AI in the stack

set -euo pipefail

MODEL="${MODEL:-hf.co/unsloth/gemma-4-E4B-it-GGUF:Q4_K_M}"
NO_AI=0
[ "${1:-}" = "--no-ai" ] && NO_AI=1

say()  { printf "\033[36m==>\033[0m %s\n" "$*"; }
ok()   { printf "\033[32m  ✓\033[0m %s\n" "$*"; }
fail() { printf "\033[31mERROR:\033[0m %s\n" "$*" >&2; exit 1; }

say "specs-agent Docker installer"

# ── 1. docker present ─────────────────────────────────────────────────
command -v docker >/dev/null 2>&1 || fail "docker not installed. Install Docker Desktop 4.44+."
ok "docker found ($(docker version --format '{{.Server.Version}}'))"

# ── 2. docker compose present ─────────────────────────────────────────
docker compose version >/dev/null 2>&1 || fail "docker compose not available. Upgrade to Docker Desktop 4.44+."

if [ "$NO_AI" = "0" ]; then
  # ── 3. docker model subcommand (Docker Desktop 4.44+) ───────────────
  if ! docker model --help >/dev/null 2>&1; then
    fail "'docker model' not available. Upgrade Docker Desktop to 4.44+ and enable Model Runner."
  fi
  ok "Docker Model Runner CLI present"

  # ── 4. DMR running? ─────────────────────────────────────────────────
  if ! docker model status >/dev/null 2>&1; then
    fail "Docker Model Runner is not running. Enable it in Docker Desktop → Settings → Beta features → Docker Model Runner."
  fi
  ok "Docker Model Runner is running"

  # ── 5. Pull the model (cached in DMR after first run) ───────────────
  say "Pulling model: $MODEL"
  if docker model list 2>/dev/null | awk 'NR>1{print $1}' | grep -qx "$(basename "$MODEL" | cut -d: -f1)"; then
    ok "Model already present locally"
  else
    docker model pull "$MODEL"
    ok "Model pulled"
  fi
fi

# ── 6. Build & start the stack ────────────────────────────────────────
say "Building and starting services"
if [ "$NO_AI" = "0" ]; then
  export SPECS_AGENT_AI_ENABLED=1
  export SPECS_AGENT_AI_BACKEND=http
  export SPECS_AGENT_AI_HTTP_MODEL="$MODEL"
else
  export SPECS_AGENT_AI_ENABLED=0
fi
docker compose up -d --build

# ── 7. Wait for API health ────────────────────────────────────────────
say "Waiting for API"
for i in $(seq 1 30); do
  if curl -fsS http://localhost:8765/health >/dev/null 2>&1; then
    ok "API is healthy"
    break
  fi
  sleep 1
done

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  specs-agent is running"
echo ""
echo "    Web UI:   http://localhost:5173"
echo "    API:      http://localhost:8765"
if [ "$NO_AI" = "0" ]; then
  echo "    Model:    $MODEL"
  echo "              (GPU inference via Docker Model Runner)"
else
  echo "    AI:       disabled (Faker-only test generation)"
fi
echo ""
echo "    Stop:      docker compose down"
echo "    Logs:      docker compose logs -f api"
echo "════════════════════════════════════════════════════════════════"
