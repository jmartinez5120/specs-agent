"""AI scenario generator — the core class that classifies fields and
generates contextually relevant test values via an in-process LLM.

Design:
- Lazy model loading (first call, not import time)
- Thread-safe (Lock around load + inference)
- Two-tier: `should_use_ai()` classifies → Faker fast-path or LLM slow-path
- Batch prompting: one LLM call per endpoint body
- Cache-first: hash-based disk cache checked before inference
- Graceful fallback: any failure → None → caller uses Faker
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from specs_agent.ai.cache import AICache
from specs_agent.ai.models import resolve_model_path
from specs_agent.ai.prompts import (
    SCENARIO_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_batch_prompt,
    build_scenario_prompt,
    parse_batch_response,
    parse_scenario_response,
)

logger = logging.getLogger(__name__)

# Property names that Faker already handles well — skip AI for these.
_FAKER_NAME_PATTERNS = frozenset({
    "email", "mail", "phone", "telephone", "fax",
    "name", "firstname", "first_name", "lastname", "last_name",
    "fullname", "full_name", "username", "user_name",
    "city", "state", "country", "zip", "zipcode", "zip_code",
    "postal", "postalcode", "postal_code",
    "street", "address", "streetaddress", "street_address",
    "url", "uri", "href", "link", "website",
    "ip", "ipv4", "ipv6", "ipaddress", "ip_address",
    "uuid", "guid", "id",
    "password", "secret", "token",
    "company", "companyname", "company_name",
    "jobtitle", "job_title", "job",
    "useragent", "user_agent",
    "domain", "domainname", "domain_name",
    "date", "datetime", "timestamp", "created_at", "updated_at",
})

# JSON schema formats that Faker already handles.
_FAKER_FORMATS = frozenset({
    "email", "date", "date-time", "uri", "url", "uuid",
    "ipv4", "ipv6", "hostname", "byte", "binary",
    "int32", "int64", "float", "double",
})


class AIGenerator:
    """Generates contextually relevant test values using a local LLM.

    Usage:
        gen = AIGenerator(model_path="/models/gemma4.gguf")
        values = gen.generate_for_endpoint(fields, "POST", "/missions", "Create a mission")
        # values = {"name": "Artemis III", "destination": "Moon"} or {} on failure
    """

    def __init__(
        self,
        model_path: str = "",
        model_size: str = "medium",
        n_ctx: int = 2048,
        n_gpu_layers: int = 0,
        cache_dir: str = "~/.specs-agent/ai-cache",
        backend: str = "auto",
        http_base_url: str = "",
        http_model: str = "",
        http_api_key: str = "",
        provider: str = "",
        anthropic_api_key: str = "",
        anthropic_model: str = "claude-haiku-4-5",
        openai_api_key: str = "",
        openai_model: str = "gpt-4o-mini",
        openai_base_url: str = "",
    ) -> None:
        self._model_path = model_path
        self._model_size = model_size
        self._n_ctx = n_ctx
        self._n_gpu_layers = n_gpu_layers
        self._model: Any = None  # llama_cpp.Llama instance (lazy-loaded)
        self._lock = threading.Lock()
        self._load_attempted = False
        self._load_error: str = ""
        self.cache = AICache(cache_dir)

        # Legacy "ai_backend" — used as fallback when provider is empty so
        # callers that haven't migrated to the provider field still work.
        self._backend = backend  # "auto" | "llama_cpp" | "http"
        self._http_base_url = http_base_url
        self._http_model = http_model
        self._http_api_key = http_api_key
        self._http = None  # lazy-init HttpBackend

        # Provider — the canonical selector. Empty string falls back to
        # legacy backend resolution for back-compat with old call sites.
        self._provider = provider
        self._anthropic_api_key = anthropic_api_key
        self._anthropic_model = anthropic_model
        self._anthropic = None  # lazy
        self._openai_api_key = openai_api_key
        self._openai_model = openai_model
        self._openai_base_url = openai_base_url
        self._openai = None  # lazy

    # ------------------------------------------------------------------ #
    # Availability
    # ------------------------------------------------------------------ #

    @staticmethod
    def llama_cpp_available() -> bool:
        """Return True if llama-cpp-python is importable."""
        try:
            import llama_cpp  # noqa: F401
            return True
        except ImportError:
            return False

    @property
    def model_loaded(self) -> bool:
        return self._model is not None

    @property
    def resolved_model_path(self) -> Path | None:
        return resolve_model_path(
            model_size=self._model_size,
            model_path=self._model_path,
        )

    def _resolve_provider(self) -> str:
        """Resolve the active provider.

        Provider takes precedence over legacy `ai_backend`. If provider
        is empty (old config not migrated, old call site), fall back to
        the legacy backend → provider mapping so behavior is unchanged.
        """
        if self._provider:
            return self._provider
        # Legacy fallback
        if self._backend == "http":
            # Closest legacy meaning of "http" was "OpenAI-compatible".
            return "openai_compatible"
        if self._backend == "llama_cpp":
            return "local_gguf"
        # auto: prefer http if configured, else local
        if self._http_base_url and self._http_model:
            return "openai_compatible"
        return "local_gguf"

    def _resolve_backend(self) -> str:
        """Legacy alias kept so internal call sites keep returning the
        old shape ("http" | "llama_cpp"). Maps the resolved provider back
        to the legacy backend name.
        """
        provider = self._resolve_provider()
        if provider == "local_gguf":
            return "llama_cpp"
        # All cloud + openai_compatible providers go through an HTTP-style path
        return "http"

    def _ensure_http(self) -> bool:
        """Initialize the HTTP backend if needed."""
        if self._http is not None:
            return True
        if not self._http_base_url or not self._http_model:
            return False
        from specs_agent.ai.http_backend import HttpBackend
        self._http = HttpBackend(
            base_url=self._http_base_url,
            model=self._http_model,
            api_key=self._http_api_key,
        )
        return True

    def _ensure_anthropic(self) -> bool:
        if self._anthropic is not None:
            return True
        if not self._anthropic_api_key:
            return False
        from specs_agent.ai.anthropic_backend import AnthropicBackend
        self._anthropic = AnthropicBackend(
            api_key=self._anthropic_api_key,
            model=self._anthropic_model,
        )
        return True

    def _ensure_openai(self) -> bool:
        if self._openai is not None:
            return True
        if not self._openai_api_key:
            return False
        from specs_agent.ai.openai_backend import OpenAIBackend
        self._openai = OpenAIBackend(
            api_key=self._openai_api_key,
            model=self._openai_model,
            base_url=self._openai_base_url,
        )
        return True

    def _active_remote_backend(self) -> Any:
        """Return the active remote backend instance (anthropic | openai |
        http) based on the resolved provider, or None for local_gguf /
        when the backend can't be initialized.
        """
        provider = self._resolve_provider()
        if provider == "anthropic":
            return self._anthropic if self._ensure_anthropic() else None
        if provider == "openai":
            return self._openai if self._ensure_openai() else None
        if provider == "openai_compatible":
            return self._http if self._ensure_http() else None
        return None

    def is_available(self) -> bool:
        """Return True if the LLM can be used."""
        provider = self._resolve_provider()
        if provider in ("anthropic", "openai", "openai_compatible"):
            backend = self._active_remote_backend()
            return bool(backend and backend.is_available())
        # local_gguf path
        if not self.llama_cpp_available():
            return False
        return self.resolved_model_path is not None

    def status(self) -> dict[str, Any]:
        """Return a status dict for the API / Web UI."""
        backend = self._resolve_backend()
        base = {
            "backend": backend,
            "llama_cpp_installed": self.llama_cpp_available(),
            "model_found": self.resolved_model_path is not None,
            "model_path": str(self.resolved_model_path) if self.resolved_model_path else "",
            "model_loaded": self.model_loaded,
            "load_error": self._load_error,
            "cache": self.cache.stats(),
        }
        if backend == "http":
            self._ensure_http()
            if self._http:
                base.update({
                    "http_base_url": self._http_base_url,
                    "http_model": self._http_model,
                    "http_available": self._http.is_available(),
                })
        return base

    # ------------------------------------------------------------------ #
    # Model lifecycle
    # ------------------------------------------------------------------ #

    def _ensure_model(self) -> bool:
        """Load the model if not already loaded. Returns True on success.

        For remote providers (anthropic / openai / openai_compatible) this
        is a no-op — the model lives on the server. Just confirm the
        backend is available.
        """
        provider = self._resolve_provider()
        if provider in ("anthropic", "openai", "openai_compatible"):
            backend = self._active_remote_backend()
            return bool(backend and backend.is_available())

        if self._model is not None:
            return True
        if self._load_attempted:
            return False  # Already tried and failed

        with self._lock:
            if self._model is not None:
                return True
            self._load_attempted = True

            path = self.resolved_model_path
            if path is None:
                # Auto-download on first use
                logger.info("AI: no model found locally — attempting download...")
                try:
                    from specs_agent.ai.download import ensure_model
                    path = ensure_model(size=self._model_size)
                except Exception as exc:
                    logger.warning("AI: auto-download failed: %s", exc)
                    path = None

            if path is None:
                self._load_error = "No model file found (download failed or unavailable)"
                logger.warning("AI: no model file found — falling back to Faker")
                return False

            try:
                from llama_cpp import Llama

                logger.info("AI: loading model from %s ...", path)
                self._model = Llama(
                    model_path=str(path),
                    n_ctx=self._n_ctx,
                    n_gpu_layers=self._n_gpu_layers,
                    verbose=False,
                )
                logger.info("AI: model loaded successfully")
                self._load_error = ""
                return True
            except ImportError:
                self._load_error = "llama-cpp-python not installed"
                logger.warning("AI: llama-cpp-python not installed — pip install 'specs-agent[ai]'")
                return False
            except Exception as exc:
                self._load_error = str(exc)
                logger.error("AI: failed to load model: %s", exc)
                return False

    # ------------------------------------------------------------------ #
    # Classification — should this field use AI or Faker?
    # ------------------------------------------------------------------ #

    @staticmethod
    def should_use_ai(prop_name: str, schema: dict) -> bool:
        """Decide whether a property should use the LLM or Faker.

        Returns True for fields where domain context matters:
        - Has a description > 10 chars AND name doesn't match a Faker pattern
        - Has enum values (LLM picks contextually appropriate ones)
        - Is a free-text string with a non-trivial name

        Returns False for fields Faker handles well:
        - Known formats (email, date, uuid, ipv4, ...)
        - Known name patterns (email, phone, city, ...)
        - Simple types (boolean, integer without description)
        """
        name_lower = prop_name.lower().replace("-", "").replace("_", "")
        schema_type = schema.get("type", "string")
        fmt = schema.get("format", "")
        description = schema.get("description", "")

        # Faker fast-path: known format
        if fmt and fmt.lower() in _FAKER_FORMATS:
            return False

        # Faker fast-path: known name pattern
        if name_lower in _FAKER_NAME_PATTERNS:
            return False

        # Faker fast-path: boolean / integer with no meaningful description
        if schema_type in ("boolean", "integer") and len(description) < 10:
            return False

        # AI path: enum values (LLM picks contextually)
        if schema.get("enum"):
            return True

        # AI path: any type with a meaningful description
        if len(description) > 10:
            return True

        # AI path: string with non-trivial name that doesn't match Faker
        if schema_type == "string" and len(name_lower) > 2 and name_lower not in _FAKER_NAME_PATTERNS:
            return True

        # Default: Faker
        return False

    # ------------------------------------------------------------------ #
    # Generation
    # ------------------------------------------------------------------ #

    def generate_for_endpoint(
        self,
        fields: list[dict[str, Any]],
        endpoint_method: str,
        endpoint_path: str,
        endpoint_description: str = "",
        endpoint_summary: str = "",
        endpoint_tags: list[str] | None = None,
        operation_id: str = "",
    ) -> dict[str, Any]:
        """Generate values for multiple fields in one batched LLM call.

        The richer the context (summary + description + tags + operationId),
        the more domain-aware the AI's generated values. Plan generator now
        passes everything Endpoint exposes.
        """
        if not fields:
            return {}

        # Cache key derives from fields + endpoint identity. Adding the
        # description-derived context to the cache key would invalidate
        # cache entries on minor doc tweaks, so we keep it fields-only.
        cache_key = AICache.cache_key(fields, endpoint_method, endpoint_path)
        cached = self.cache.get_value(cache_key)
        if cached is not None and isinstance(cached, dict):
            return cached

        # Load model
        if not self._ensure_model():
            return {}

        # Build prompt
        prompt_text = build_batch_prompt(
            fields,
            endpoint_method,
            endpoint_path,
            endpoint_description,
            endpoint_summary=endpoint_summary,
            endpoint_tags=endpoint_tags,
            operation_id=operation_id,
        )

        # Run inference
        field_names = [f["name"] for f in fields]
        result = self._infer(prompt_text, field_names)

        # Cache the result if non-empty
        if result:
            self.cache.put(
                cache_key,
                result,
                schema_hash=AICache.schema_hash({"fields": fields}),
                model=Path(self._model_path or self._model_size).name,
            )

        return result

    def generate_scenarios(
        self,
        endpoint_method: str,
        endpoint_path: str,
        endpoint_description: str,
        parameters: list[dict],
        body_schema: dict | None,
        documented_responses: list[int],
        endpoint_summary: str = "",
        endpoint_tags: list[str] | None = None,
        operation_id: str = "",
    ) -> list[dict]:
        """Propose additional test scenarios for an endpoint via the LLM.

        Returns a list of scenario dicts with keys:
            name, description, category, expected_status, body, path_params, query_params
        """
        # Cache key includes endpoint identity + schema shape
        cache_key = AICache.cache_key(
            [{"type": "scenario_gen", "responses": documented_responses}],
            endpoint_method,
            endpoint_path,
        )
        cached = self.cache.get_value(cache_key)
        if cached is not None and isinstance(cached, list):
            return cached

        if not self._ensure_model():
            return []

        prompt_text = build_scenario_prompt(
            endpoint_method,
            endpoint_path,
            endpoint_description,
            parameters,
            body_schema,
            documented_responses,
            endpoint_summary=endpoint_summary,
            endpoint_tags=endpoint_tags,
            operation_id=operation_id,
        )

        scenarios = self._infer_scenarios(prompt_text)

        if scenarios:
            self.cache.put(
                cache_key,
                scenarios,
                schema_hash=AICache.schema_hash({"method": endpoint_method, "path": endpoint_path}),
                model=Path(self._model_path or self._model_size).name,
            )

        return scenarios

    def _infer_scenarios(self, prompt: str) -> list[dict]:
        """Run the LLM for scenario generation. Routes by provider."""
        remote = self._active_remote_backend()
        if remote is not None:
            raw = remote.chat_completion(
                SCENARIO_SYSTEM_PROMPT,
                prompt,
                max_tokens=1024,
                temperature=0.8,
                top_p=0.95,
            )
            return parse_scenario_response(raw) if raw else []

        # In-process llama_cpp backend
        if self._model is None:
            return []
        with self._lock:
            try:
                response = self._model.create_chat_completion(
                    messages=[
                        {"role": "system", "content": SCENARIO_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=1024,
                    temperature=0.8,
                    top_p=0.95,
                )
                raw = response["choices"][0]["message"]["content"]
                return parse_scenario_response(raw)
            except Exception as exc:
                logger.warning("AI scenario generation failed: %s", exc)
                return []

    def _infer(self, prompt: str, field_names: list[str]) -> dict[str, Any]:
        """Run the LLM and parse the response. Routes by provider."""
        remote = self._active_remote_backend()
        if remote is not None:
            raw = remote.chat_completion(
                SYSTEM_PROMPT,
                prompt,
                max_tokens=512,
                temperature=0.7,
                top_p=0.9,
            )
            return parse_batch_response(raw, field_names) if raw else {}

        # In-process llama_cpp backend
        if self._model is None:
            return {}

        with self._lock:
            try:
                response = self._model.create_chat_completion(
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=512,
                    temperature=0.7,
                    top_p=0.9,
                )
                raw = response["choices"][0]["message"]["content"]
                return parse_batch_response(raw, field_names)
            except Exception as exc:
                logger.warning("AI inference failed: %s", exc)
                return {}
