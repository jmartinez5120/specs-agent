"""MongoDB-backed storage for the engine.

Implements the same `Storage` protocol as `FileStorage` so the engine
doesn't care which backend is active. Used when specs-agent runs inside
Docker (with the bundled mongodb service) or against an external cluster
(planned MVP 9).

Collections:
    plans           — one doc per saved plan, keyed by spec_title
    plan_archives   — append-only, one doc per archived plan
    configs         — singleton doc (_id: "app")
    history         — one doc per run, keyed by (spec_hash, filename)
    history_index   — one doc per spec (spec_hash) with a `runs` array
                      (mirrors FileStorage's index.json shape so clients
                      see identical shapes across backends)

All serialization happens through the same `_case_to_dict` /
`_report_to_dict` helpers used by the file backend, keeping on-the-wire
schemas identical for the API.
"""

from __future__ import annotations

import hashlib
from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from specs_agent.config import (
    AppConfig,
    AuthPreset,
    RecentSpec,
    _env_bool,
    _env_int,
    _env_str,
    migrate_provider,
)


def _migrate_provider_for_doc(doc: dict) -> str:
    return migrate_provider(doc.get("ai_provider", ""), doc.get("ai_backend", "auto"))
from specs_agent.history.storage import (
    _dict_to_report,
    _report_to_dict,
    _spec_hash,
)
from specs_agent.models.plan import Assertion, AssertionType, TestCase, TestPlan
from specs_agent.models.results import Report


# Default Mongo connection if none provided.
DEFAULT_MONGO_URL = "mongodb://localhost:27017"
DEFAULT_DB_NAME = "specs_agent"


class MongoStorage:
    """pymongo-backed Storage implementation.

    Accepts either:
      - a full MongoDB URL (`mongodb://...`), in which case a new client
        is created; or
      - an existing pymongo-compatible Database (for tests using mongomock).
    """

    def __init__(
        self,
        *,
        url: str | None = None,
        db_name: str = DEFAULT_DB_NAME,
        database: Database | None = None,
    ) -> None:
        if database is not None:
            self.db = database
        else:
            client: MongoClient = MongoClient(url or DEFAULT_MONGO_URL)
            self.db = client[db_name]

        # Collection handles
        self.specs: Collection = self.db["specs"]
        self.plans: Collection = self.db["plans"]
        self.plan_archives: Collection = self.db["plan_archives"]
        self.configs: Collection = self.db["configs"]
        self.history: Collection = self.db["history"]
        self.history_index: Collection = self.db["history_index"]

    # ------------------------------------------------------------------ #
    # Config — singleton document with _id = "app"
    # ------------------------------------------------------------------ #

    def load_config(self) -> AppConfig:
        doc = self.configs.find_one({"_id": "app"})
        if not doc:
            return AppConfig()
        return _doc_to_config(doc)

    def save_config(self, config: AppConfig) -> None:
        data = _config_to_doc(config)
        self.configs.replace_one({"_id": "app"}, data, upsert=True)

    # ------------------------------------------------------------------ #
    # Specs — saved parsed specs for the spec browser
    # ------------------------------------------------------------------ #

    def save_spec(self, title: str, source: str, source_type: str, raw_spec: dict) -> str:
        from datetime import datetime, timezone
        safe_id = title.replace(" ", "_").lower()[:40]
        doc = {
            "_id": safe_id,
            "title": title,
            "source": source,
            "source_type": source_type,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "raw_spec": raw_spec,
        }
        self.specs.replace_one({"_id": safe_id}, doc, upsert=True)
        return f"mongo://{self.db.name}/specs/{safe_id}"

    def list_specs(self, limit: int = 20) -> list[dict]:
        docs = self.specs.find({}, {"raw_spec": 0}).sort("saved_at", -1).limit(limit)
        return [
            {
                "id": doc["_id"],
                "title": doc.get("title", doc["_id"]),
                "source": doc.get("source", ""),
                "source_type": doc.get("source_type", ""),
                "saved_at": doc.get("saved_at", ""),
            }
            for doc in docs
        ]

    def load_spec(self, spec_id: str) -> dict | None:
        doc = self.specs.find_one({"_id": spec_id})
        if not doc:
            return None
        doc.pop("_id", None)
        return doc

    def delete_spec(self, spec_id: str) -> bool:
        result = self.specs.delete_one({"_id": spec_id})
        return result.deleted_count > 0

    # ------------------------------------------------------------------ #
    # Plans — keyed by spec_title (matches FileStorage semantics)
    # ------------------------------------------------------------------ #

    def save_plan(self, plan: TestPlan) -> str:
        doc = _plan_to_doc(plan)
        doc["_id"] = plan.spec_title or plan.name
        self.plans.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        return f"mongo://{self.db.name}/plans/{doc['_id']}"

    def load_plan_for_spec(self, spec_title: str) -> TestPlan | None:
        doc = self.plans.find_one({"_id": spec_title})
        if doc is None:
            # Fallback — match legacy "{title} Test Plan" keys by name
            doc = self.plans.find_one({"spec_title": spec_title})
            if doc is None:
                return None
        return _doc_to_plan(doc)

    def archive_plan(self, plan: TestPlan) -> str:
        from datetime import datetime, timezone

        doc = _plan_to_doc(plan)
        doc["archived_at"] = datetime.now(timezone.utc).isoformat()
        result = self.plan_archives.insert_one(doc)
        return f"mongo://{self.db.name}/plan_archives/{result.inserted_id}"

    # ------------------------------------------------------------------ #
    # History — one doc per run; an index doc per spec
    # ------------------------------------------------------------------ #

    def save_run(self, report: Report) -> str:
        h = _spec_hash(report.spec_title, report.base_url)
        timestamp = report.started_at[:19].replace(":", "-").replace("T", "_")
        filename = f"run_{timestamp}.json"

        # Store the raw run doc (same shape as FileStorage's file contents)
        run_doc = _report_to_dict(report)
        run_doc["_id"] = f"{h}:{filename}"
        run_doc["spec_hash"] = h
        run_doc["filename"] = filename
        self.history.replace_one({"_id": run_doc["_id"]}, run_doc, upsert=True)

        # Update the per-spec index (same summary shape as index.json)
        self._update_index(h, report, filename)

        return f"mongo://{self.db.name}/history/{run_doc['_id']}"

    def list_runs(self, spec_title: str, base_url: str, limit: int = 20) -> list[dict]:
        h = _spec_hash(spec_title, base_url)
        doc = self.history_index.find_one({"_id": h})
        if not doc:
            return []
        return doc.get("runs", [])[:limit]

    def load_run(self, spec_title: str, base_url: str, filename: str) -> Report | None:
        h = _spec_hash(spec_title, base_url)
        doc = self.history.find_one({"_id": f"{h}:{filename}"})
        if not doc:
            return None
        # Strip Mongo-specific fields before reconstructing
        clean = {k: v for k, v in doc.items() if k not in ("_id", "spec_hash", "filename")}
        return _dict_to_report(clean)

    # ------------------------------------------------------------------ #
    # Internal — history index update (mirrors file backend semantics)
    # ------------------------------------------------------------------ #

    def _update_index(self, spec_hash: str, report: Report, filename: str) -> None:
        # Aggregate perf the same way file backend does
        perf = report.performance_results
        if perf:
            all_latencies = [pm.avg_latency_ms for pm in perf if pm.avg_latency_ms]
            avg_latency = sum(all_latencies) / len(all_latencies) if all_latencies else 0
            max_p95 = max((pm.p95_latency_ms for pm in perf), default=0)
            max_p99 = max((pm.p99_latency_ms for pm in perf), default=0)
            total_rps = sum(pm.requests_per_second for pm in perf)
            avg_err = sum(pm.error_rate_pct for pm in perf) / len(perf) if perf else 0
        else:
            avg_latency = max_p95 = max_p99 = total_rps = avg_err = 0

        summary = {
            "filename": filename,
            "timestamp": report.started_at,
            "total": report.total_tests,
            "passed": report.passed_tests,
            "failed": report.failed_tests,
            "errors": report.error_tests,
            "pass_rate": round(report.pass_rate, 1),
            "duration": round(report.duration_seconds, 1),
            "perf_requests": sum(pm.total_requests for pm in perf),
            "perf_avg_ms": round(avg_latency, 1),
            "perf_p95_ms": round(max_p95, 1),
            "perf_p99_ms": round(max_p99, 1),
            "perf_rps": round(total_rps, 1),
            "perf_err_pct": round(avg_err, 1),
        }

        existing = self.history_index.find_one({"_id": spec_hash})
        if existing:
            runs = existing.get("runs", [])
        else:
            runs = []

        # Prepend (newest first), cap at 50 — same as file backend
        runs.insert(0, summary)
        runs = runs[:50]

        self.history_index.replace_one(
            {"_id": spec_hash},
            {
                "_id": spec_hash,
                "spec_title": report.spec_title,
                "base_url": report.base_url,
                "runs": runs,
            },
            upsert=True,
        )


# ====================================================================== #
# Plan ↔ Mongo doc helpers
# ====================================================================== #


def _plan_to_doc(plan: TestPlan) -> dict:
    return {
        "name": plan.name,
        "spec_title": plan.spec_title,
        "base_url": plan.base_url,
        "created_at": plan.created_at,
        "auth_type": plan.auth_type,
        "auth_value": plan.auth_value,
        "global_headers": plan.global_headers,
        "global_variables": dict(getattr(plan, "global_variables", {}) or {}),
        "performance_slas": plan.performance_slas,
        "test_cases": [_case_to_doc(tc) for tc in plan.test_cases],
    }


def _doc_to_plan(doc: dict) -> TestPlan:
    return TestPlan(
        name=doc.get("name", "Loaded Plan"),
        spec_title=doc.get("spec_title", ""),
        base_url=doc.get("base_url", ""),
        created_at=doc.get("created_at", ""),
        auth_type=doc.get("auth_type", "none"),
        auth_value=doc.get("auth_value", ""),
        global_headers=doc.get("global_headers", {}),
        global_variables=doc.get("global_variables", {}) or {},
        performance_slas=doc.get("performance_slas", {}),
        test_cases=[_doc_to_case(c) for c in doc.get("test_cases", [])],
    )


def _case_to_doc(tc: TestCase) -> dict:
    return {
        "id": tc.id,
        "endpoint_path": tc.endpoint_path,
        "method": tc.method,
        "name": tc.name,
        "description": tc.description,
        "enabled": tc.enabled,
        "path_params": tc.path_params,
        "query_params": tc.query_params,
        "headers": tc.headers,
        "body": tc.body,
        "needs_input": tc.needs_input,
        "test_type": tc.test_type,
        "depends_on": tc.depends_on,
        "assertions": [
            {"type": a.type.value, "expected": a.expected, "description": a.description}
            for a in tc.assertions
        ],
        "ai_fields": tc.ai_fields,
        "ai_generated": tc.ai_generated,
        "ai_category": tc.ai_category,
        "local_variables": dict(getattr(tc, "local_variables", {}) or {}),
    }


def _doc_to_case(data: dict) -> TestCase:
    assertions = []
    for a in data.get("assertions", []):
        try:
            atype = AssertionType(a.get("type", "status_code"))
        except ValueError:
            atype = AssertionType.STATUS_CODE
        assertions.append(Assertion(
            type=atype,
            expected=a.get("expected"),
            description=a.get("description", ""),
        ))

    return TestCase(
        id=data.get("id", ""),
        endpoint_path=data.get("endpoint_path", ""),
        method=data.get("method", "GET"),
        name=data.get("name", ""),
        description=data.get("description", ""),
        enabled=data.get("enabled", True),
        path_params=data.get("path_params", {}),
        query_params=data.get("query_params", {}),
        headers=data.get("headers", {}),
        body=data.get("body"),
        needs_input=data.get("needs_input", False),
        test_type=data.get("test_type", "happy"),
        depends_on=data.get("depends_on"),
        assertions=assertions,
        ai_fields=data.get("ai_fields", []),
        ai_generated=data.get("ai_generated", False),
        ai_category=data.get("ai_category", ""),
        local_variables=data.get("local_variables", {}) or {},
    )


# ====================================================================== #
# Config ↔ Mongo doc helpers
# ====================================================================== #


def _config_to_doc(cfg: AppConfig) -> dict:
    return {
        "_id": "app",
        "version": cfg.version,
        "base_url": cfg.base_url,
        "timeout_seconds": cfg.timeout_seconds,
        "follow_redirects": cfg.follow_redirects,
        "verify_ssl": cfg.verify_ssl,
        "perf_concurrent_users": cfg.perf_concurrent_users,
        "perf_duration_seconds": cfg.perf_duration_seconds,
        "perf_ramp_up_seconds": cfg.perf_ramp_up_seconds,
        "perf_latency_p95_threshold_ms": cfg.perf_latency_p95_threshold_ms,
        "ai_enabled": cfg.ai_enabled,
        "ai_model_size": cfg.ai_model_size,
        "ai_model_path": cfg.ai_model_path,
        "ai_n_ctx": cfg.ai_n_ctx,
        "ai_n_gpu_layers": cfg.ai_n_gpu_layers,
        "ai_cache_dir": cfg.ai_cache_dir,
        "ai_backend": cfg.ai_backend,
        "ai_http_base_url": cfg.ai_http_base_url,
        "ai_http_model": cfg.ai_http_model,
        "ai_http_api_key": cfg.ai_http_api_key,
        "ai_provider": cfg.ai_provider,
        "ai_anthropic_api_key": cfg.ai_anthropic_api_key,
        "ai_anthropic_model": cfg.ai_anthropic_model,
        "ai_openai_api_key": cfg.ai_openai_api_key,
        "ai_openai_model": cfg.ai_openai_model,
        "ai_openai_base_url": cfg.ai_openai_base_url,
        "auth_presets": [
            {"name": a.name, "type": a.type, "header": a.header, "value": a.value}
            for a in cfg.auth_presets
        ],
        "saved_auth_type": cfg.saved_auth_type,
        "saved_auth_value": cfg.saved_auth_value,
        "saved_auth_header": cfg.saved_auth_header,
        "saved_token_fetch": dict(cfg.saved_token_fetch or {}),
        "recent_specs": [
            {"path": r.path, "url": r.url, "title": r.title, "last_opened": r.last_opened}
            for r in cfg.recent_specs
        ],
        "reports_output_dir": cfg.reports_output_dir,
        "reports_format": cfg.reports_format,
        "reports_open_after": cfg.reports_open_after,
        "theme": cfg.theme,
    }


def _doc_to_config(doc: dict) -> AppConfig:
    return AppConfig(
        version=doc.get("version", 1),
        base_url=doc.get("base_url", ""),
        timeout_seconds=doc.get("timeout_seconds", 30.0),
        follow_redirects=doc.get("follow_redirects", True),
        verify_ssl=doc.get("verify_ssl", True),
        perf_concurrent_users=doc.get("perf_concurrent_users", 10),
        perf_duration_seconds=doc.get("perf_duration_seconds", 30),
        perf_ramp_up_seconds=doc.get("perf_ramp_up_seconds", 5),
        perf_latency_p95_threshold_ms=doc.get("perf_latency_p95_threshold_ms", 2000.0),
        # AI settings: env vars override stored document so Docker deployments
        # pick up SPECS_AGENT_AI_* without hitting /config first.
        ai_enabled=_env_bool("SPECS_AGENT_AI_ENABLED", doc.get("ai_enabled", False)),
        ai_model_size=_env_str("SPECS_AGENT_AI_MODEL_SIZE", doc.get("ai_model_size", "medium")),
        ai_model_path=_env_str("SPECS_AGENT_AI_MODEL_PATH", doc.get("ai_model_path", "")),
        ai_n_ctx=_env_int("SPECS_AGENT_AI_N_CTX", doc.get("ai_n_ctx", 2048)),
        ai_n_gpu_layers=_env_int("SPECS_AGENT_AI_N_GPU_LAYERS", doc.get("ai_n_gpu_layers", 0)),
        ai_cache_dir=_env_str("SPECS_AGENT_AI_CACHE_DIR", doc.get("ai_cache_dir") or "~/.specs-agent/ai-cache"),
        ai_backend=_env_str("SPECS_AGENT_AI_BACKEND", doc.get("ai_backend", "auto")),
        ai_http_base_url=_env_str("SPECS_AGENT_AI_HTTP_BASE_URL", doc.get("ai_http_base_url", "")),
        ai_http_model=_env_str("SPECS_AGENT_AI_HTTP_MODEL", doc.get("ai_http_model", "")),
        ai_http_api_key=_env_str("SPECS_AGENT_AI_HTTP_API_KEY", doc.get("ai_http_api_key", "")),
        ai_provider=_env_str(
            "SPECS_AGENT_AI_PROVIDER",
            doc.get("ai_provider") or _migrate_provider_for_doc(doc),
        ),
        ai_anthropic_api_key=_env_str("SPECS_AGENT_AI_ANTHROPIC_API_KEY", doc.get("ai_anthropic_api_key", "")),
        ai_anthropic_model=_env_str("SPECS_AGENT_AI_ANTHROPIC_MODEL", doc.get("ai_anthropic_model", "claude-haiku-4-5")),
        ai_openai_api_key=_env_str("SPECS_AGENT_AI_OPENAI_API_KEY", doc.get("ai_openai_api_key", "")),
        ai_openai_model=_env_str("SPECS_AGENT_AI_OPENAI_MODEL", doc.get("ai_openai_model", "gpt-4o-mini")),
        ai_openai_base_url=_env_str("SPECS_AGENT_AI_OPENAI_BASE_URL", doc.get("ai_openai_base_url", "")),
        auth_presets=[
            AuthPreset(
                name=a.get("name", ""),
                type=a.get("type", "bearer"),
                header=a.get("header", ""),
                value=a.get("value", ""),
            )
            for a in doc.get("auth_presets", [])
        ],
        saved_auth_type=doc.get("saved_auth_type", "none"),
        saved_auth_value=doc.get("saved_auth_value", ""),
        saved_auth_header=doc.get("saved_auth_header", "Authorization"),
        saved_token_fetch=dict(doc.get("saved_token_fetch") or {}),
        recent_specs=[
            RecentSpec(
                path=r.get("path", ""),
                url=r.get("url", ""),
                title=r.get("title", ""),
                last_opened=r.get("last_opened", ""),
            )
            for r in doc.get("recent_specs", [])
        ],
        reports_output_dir=doc.get("reports_output_dir", "~/.specs-agent/reports"),
        reports_format=doc.get("reports_format", "html"),
        reports_open_after=doc.get("reports_open_after", True),
        theme=doc.get("theme", "dark"),
    )
