# specs-agent API image — lean build, no model baked in.
#
# Inference runs on the host via Docker Model Runner (Docker Desktop 4.44+).
# The container talks to DMR over HTTP at `model-runner.docker.internal`, so
# no GGUF needs to ship inside this image. `install.sh` pulls the model into
# DMR once on first run, then every `docker compose up` is offline.

# ─────────────── Stage 1: builder ───────────────
FROM python:3.13-slim AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc g++ libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --prefix=/install .


# ─────────────── Stage 2: runtime ───────────────
FROM python:3.13-slim AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash --uid 1000 specs \
    && mkdir -p /home/specs/.specs-agent/ai-cache \
    && chown -R specs:specs /home/specs/.specs-agent
WORKDIR /app

# Copy site-packages + console scripts from builder
COPY --from=builder /install /usr/local

USER specs

# Defaults route AI through Docker Model Runner on the host.
ENV SPECS_AGENT_HOST=0.0.0.0 \
    SPECS_AGENT_PORT=8765 \
    SPECS_AGENT_STORAGE=mongo \
    SPECS_AGENT_MONGO_URL=mongodb://mongo:27017/?replicaSet=rs0&directConnection=true \
    SPECS_AGENT_MONGO_DB=specs_agent \
    SPECS_AGENT_IN_DOCKER=1 \
    SPECS_AGENT_SEARCH=elasticsearch \
    ELASTICSEARCH_URL=http://elasticsearch:9200 \
    SPECS_AGENT_AI_ENABLED=1 \
    SPECS_AGENT_AI_BACKEND=http \
    SPECS_AGENT_AI_HTTP_BASE_URL=http://model-runner.docker.internal/engines/v1 \
    SPECS_AGENT_AI_HTTP_MODEL=hf.co/unsloth/gemma-4-E4B-it-GGUF:Q4_K_M \
    SPECS_AGENT_AI_N_CTX=2048 \
    PYTHONUNBUFFERED=1

EXPOSE 8765

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8765/health || exit 1

CMD ["python", "-m", "specs_agent.api"]
