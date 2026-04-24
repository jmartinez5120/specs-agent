"""Configuration management for specs-agent."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


# ------------------------------------------------------------------ #
# Env-var helpers for config overrides (used in Docker / CI)
# ------------------------------------------------------------------ #

def _env_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key, "").strip().lower()
    if v in ("1", "true", "yes"):
        return True
    if v in ("0", "false", "no"):
        return False
    return default


def _env_str(key: str, default: str) -> str:
    return os.environ.get(key, "").strip() or default


def _env_int(key: str, default: int) -> int:
    v = os.environ.get(key, "").strip()
    if v:
        try:
            return int(v)
        except ValueError:
            pass
    return default

CONFIG_DIR_NAME = ".specs-agent"
CONFIG_FILE_NAME = "config.yaml"


@dataclass
class AuthPreset:
    name: str = ""
    type: str = "bearer"
    header: str = ""
    value: str = ""


@dataclass
class RecentSpec:
    path: str = ""
    url: str = ""
    title: str = ""
    last_opened: str = ""

    @property
    def source(self) -> str:
        return self.url or self.path

    @property
    def display(self) -> str:
        return self.title or self.source


@dataclass
class AppConfig:
    version: int = 1
    # Defaults
    base_url: str = ""
    timeout_seconds: float = 30.0
    follow_redirects: bool = True
    verify_ssl: bool = True
    # Performance defaults
    perf_concurrent_users: int = 10
    perf_duration_seconds: int = 30
    perf_ramp_up_seconds: int = 5
    perf_latency_p95_threshold_ms: float = 2000.0
    # Auth
    auth_presets: list[AuthPreset] = field(default_factory=list)
    # Last-used Auth & Global Headers from the Test Configuration modal.
    # Auto-saved on SAVE & RUN, pre-filled on reopen, cleared by the UI button.
    saved_auth_type: str = "none"
    saved_auth_value: str = ""
    saved_auth_header: str = "Authorization"
    saved_token_fetch: dict = field(default_factory=dict)
    # Recent specs
    recent_specs: list[RecentSpec] = field(default_factory=list)
    # Reports
    reports_output_dir: str = "~/.specs-agent/reports"
    reports_format: str = "html"
    reports_open_after: bool = True
    # Theme
    theme: str = "dark"
    # AI scenario generation
    ai_enabled: bool = False
    ai_model_size: str = "medium"  # "small" | "medium" | absolute path to GGUF
    ai_model_path: str = ""  # explicit model path (overrides ai_model_size)
    ai_n_ctx: int = 2048
    ai_n_gpu_layers: int = 0  # -1 for full GPU offload
    ai_cache_dir: str = "~/.specs-agent/ai-cache"
    # AI backend selection (legacy — kept for back-compat).
    # "auto"     → derived from ai_provider
    # "llama_cpp" → in-process GGUF via llama-cpp-python
    # "http"      → OpenAI-compatible API (Docker Model Runner, Ollama, vLLM, etc.)
    ai_backend: str = "auto"
    ai_http_base_url: str = ""
    ai_http_model: str = ""
    ai_http_api_key: str = ""
    # AI provider — the canonical selector going forward.
    # Values: "local_gguf" | "anthropic" | "openai" | "openai_compatible"
    ai_provider: str = "local_gguf"
    # Anthropic Claude
    ai_anthropic_api_key: str = ""
    ai_anthropic_model: str = "claude-haiku-4-5"
    # OpenAI
    ai_openai_api_key: str = ""
    ai_openai_model: str = "gpt-4o-mini"
    ai_openai_base_url: str = ""  # empty → SDK default (api.openai.com/v1)


# ------------------------------------------------------------------ #
# Provider ↔ legacy backend mapping
# ------------------------------------------------------------------ #

# Canonical: provider → legacy ai_backend
_PROVIDER_TO_BACKEND = {
    "local_gguf": "llama_cpp",
    "anthropic": "http",  # legacy field treats both cloud APIs as "http"
    "openai": "http",
    "openai_compatible": "http",
}

# Migration: legacy backend → provider (used when ai_provider is missing)
_BACKEND_TO_PROVIDER = {
    "http": "openai_compatible",
    "llama_cpp": "local_gguf",
    "auto": "local_gguf",
}


def derive_backend(provider: str) -> str:
    """Return the legacy `ai_backend` value implied by a provider."""
    return _PROVIDER_TO_BACKEND.get(provider, "llama_cpp")


def migrate_provider(stored_provider: str, stored_backend: str) -> str:
    """Resolve `ai_provider` for a config that may be pre-migration.

    If the doc/file already has an explicit provider, trust it. Otherwise
    derive it from the legacy backend so old installs keep working.
    """
    if stored_provider:
        return stored_provider
    return _BACKEND_TO_PROVIDER.get(stored_backend or "auto", "local_gguf")


def get_config_dir() -> Path:
    """Return the config directory path (~/.specs-agent/)."""
    return Path.home() / CONFIG_DIR_NAME


def get_config_path() -> Path:
    """Return the config file path."""
    return get_config_dir() / CONFIG_FILE_NAME


def load_config() -> AppConfig:
    """Load config from ~/.specs-agent/config.yaml. Returns defaults if missing."""
    path = get_config_path()
    if not path.exists():
        return AppConfig()

    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return AppConfig()

    return _config_from_dict(data)


def save_config(config: AppConfig) -> None:
    """Save config to ~/.specs-agent/config.yaml."""
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)

    data = _config_to_dict(config)
    path = get_config_path()
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


def add_recent_spec(config: AppConfig, source: str, title: str) -> None:
    """Add or update a recent spec entry."""
    from datetime import datetime, timezone

    is_url = source.startswith(("http://", "https://"))
    entry = RecentSpec(
        path="" if is_url else source,
        url=source if is_url else "",
        title=title,
        last_opened=datetime.now(timezone.utc).isoformat(),
    )

    # Remove existing entry for same source
    config.recent_specs = [
        r for r in config.recent_specs if r.source != source
    ]
    # Prepend
    config.recent_specs.insert(0, entry)
    # Keep max 10
    config.recent_specs = config.recent_specs[:10]


def _config_from_dict(data: dict) -> AppConfig:
    defaults = data.get("defaults", {})
    perf = data.get("performance", {})
    reports = data.get("reports", {})
    ai = data.get("ai", {})

    auth_presets = [
        AuthPreset(
            name=a.get("name", ""),
            type=a.get("type", "bearer"),
            header=a.get("header", ""),
            value=a.get("value", ""),
        )
        for a in data.get("auth_presets", [])
    ]

    recent_specs = [
        RecentSpec(
            path=r.get("path", ""),
            url=r.get("url", ""),
            title=r.get("title", ""),
            last_opened=r.get("last_opened", ""),
        )
        for r in data.get("recent_specs", [])
    ]

    return AppConfig(
        version=data.get("version", 1),
        base_url=defaults.get("base_url", ""),
        timeout_seconds=defaults.get("timeout_seconds", 30.0),
        follow_redirects=defaults.get("follow_redirects", True),
        verify_ssl=defaults.get("verify_ssl", True),
        perf_concurrent_users=perf.get("concurrent_users", 10),
        perf_duration_seconds=perf.get("duration_seconds", 30),
        perf_ramp_up_seconds=perf.get("ramp_up_seconds", 5),
        perf_latency_p95_threshold_ms=perf.get("latency_p95_threshold_ms", 2000.0),
        auth_presets=auth_presets,
        saved_auth_type=data.get("saved_auth", {}).get("type", "none"),
        saved_auth_value=data.get("saved_auth", {}).get("value", ""),
        saved_auth_header=data.get("saved_auth", {}).get("header", "Authorization"),
        saved_token_fetch=data.get("saved_auth", {}).get("token_fetch", {}) or {},
        recent_specs=recent_specs,
        reports_output_dir=reports.get("output_dir", "~/.specs-agent/reports"),
        reports_format=reports.get("format", "html"),
        reports_open_after=reports.get("open_after_export", True),
        theme=data.get("theme", "dark"),
        # AI — env var overrides take precedence
        ai_enabled=_env_bool("SPECS_AGENT_AI_ENABLED", ai.get("enabled", False)),
        ai_model_size=_env_str("SPECS_AGENT_AI_MODEL_SIZE", ai.get("model_size", "medium")),
        ai_model_path=_env_str("SPECS_AGENT_AI_MODEL_PATH", ai.get("model_path", "")),
        ai_n_ctx=_env_int("SPECS_AGENT_AI_N_CTX", ai.get("n_ctx", 2048)),
        ai_n_gpu_layers=_env_int("SPECS_AGENT_AI_N_GPU_LAYERS", ai.get("n_gpu_layers", 0)),
        ai_cache_dir=_env_str("SPECS_AGENT_AI_CACHE_DIR", ai.get("cache_dir", "~/.specs-agent/ai-cache")),
        ai_backend=_env_str("SPECS_AGENT_AI_BACKEND", ai.get("backend", "auto")),
        ai_http_base_url=_env_str("SPECS_AGENT_AI_HTTP_BASE_URL", ai.get("http_base_url", "")),
        ai_http_model=_env_str("SPECS_AGENT_AI_HTTP_MODEL", ai.get("http_model", "")),
        ai_http_api_key=_env_str("SPECS_AGENT_AI_HTTP_API_KEY", ai.get("http_api_key", "")),
        ai_provider=_env_str(
            "SPECS_AGENT_AI_PROVIDER",
            migrate_provider(
                ai.get("provider", ""),
                ai.get("backend", "auto"),
            ),
        ),
        ai_anthropic_api_key=_env_str("SPECS_AGENT_AI_ANTHROPIC_API_KEY", ai.get("anthropic_api_key", "")),
        ai_anthropic_model=_env_str("SPECS_AGENT_AI_ANTHROPIC_MODEL", ai.get("anthropic_model", "claude-haiku-4-5")),
        ai_openai_api_key=_env_str("SPECS_AGENT_AI_OPENAI_API_KEY", ai.get("openai_api_key", "")),
        ai_openai_model=_env_str("SPECS_AGENT_AI_OPENAI_MODEL", ai.get("openai_model", "gpt-4o-mini")),
        ai_openai_base_url=_env_str("SPECS_AGENT_AI_OPENAI_BASE_URL", ai.get("openai_base_url", "")),
    )


def _config_to_dict(config: AppConfig) -> dict:
    return {
        "version": config.version,
        "defaults": {
            "base_url": config.base_url,
            "timeout_seconds": config.timeout_seconds,
            "follow_redirects": config.follow_redirects,
            "verify_ssl": config.verify_ssl,
        },
        "performance": {
            "concurrent_users": config.perf_concurrent_users,
            "duration_seconds": config.perf_duration_seconds,
            "ramp_up_seconds": config.perf_ramp_up_seconds,
            "latency_p95_threshold_ms": config.perf_latency_p95_threshold_ms,
        },
        "auth_presets": [
            {"name": a.name, "type": a.type, "header": a.header, "value": a.value}
            for a in config.auth_presets
        ],
        "saved_auth": {
            "type": config.saved_auth_type,
            "value": config.saved_auth_value,
            "header": config.saved_auth_header,
            "token_fetch": config.saved_token_fetch or {},
        },
        "recent_specs": [
            {
                "path": r.path,
                "url": r.url,
                "title": r.title,
                "last_opened": r.last_opened,
            }
            for r in config.recent_specs
        ],
        "reports": {
            "output_dir": config.reports_output_dir,
            "format": config.reports_format,
            "open_after_export": config.reports_open_after,
        },
        "theme": config.theme,
        "ai": {
            "enabled": config.ai_enabled,
            "model_size": config.ai_model_size,
            "model_path": config.ai_model_path,
            "n_ctx": config.ai_n_ctx,
            "n_gpu_layers": config.ai_n_gpu_layers,
            "cache_dir": config.ai_cache_dir,
            "backend": config.ai_backend,
            "http_base_url": config.ai_http_base_url,
            "http_model": config.ai_http_model,
            "http_api_key": config.ai_http_api_key,
            "provider": config.ai_provider,
            "anthropic_api_key": config.ai_anthropic_api_key,
            "anthropic_model": config.ai_anthropic_model,
            "openai_api_key": config.ai_openai_api_key,
            "openai_model": config.ai_openai_model,
            "openai_base_url": config.ai_openai_base_url,
        },
    }
