"""End-to-end integration tests using the Mongo backend.

Runs the same flows as test_engine_flow.py — load spec, generate plan,
edit, save, reload, merge, execute, render, history — but through
`MongoStorage` (via `mongomock`) instead of `FileStorage`.

Proves the `Storage` protocol is genuinely swappable: the engine and
API don't care which backend they're talking to.

This also indirectly validates the full API flow against Mongo when
combined with the test_api/test_api_flow tests — if both backends pass
the same flow, the API contract is backend-agnostic.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import mongomock
import pytest

from specs_agent.engine import Engine
from specs_agent.engine.mongo_storage import MongoStorage
from specs_agent.execution.runner import TestRunner
from specs_agent.models.config import PerformanceConfig, TestRunConfig
from specs_agent.reporting.generator import generate_html_report


FIXTURES = Path(__file__).parent.parent / "fixtures"


def _patch_all_httpx(handler):
    orig = httpx.AsyncClient
    def wrapped(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        kw.pop("verify", None)
        return orig(*a, **kw)
    return [
        patch("specs_agent.execution.functional.httpx.AsyncClient", side_effect=wrapped),
        patch("specs_agent.execution.performance.httpx.AsyncClient", side_effect=wrapped),
    ]


class _AllPatches:
    def __init__(self, patches): self.patches = patches
    def __enter__(self):
        for p in self.patches: p.__enter__()
        return self
    def __exit__(self, *a):
        for p in reversed(self.patches): p.__exit__(*a)


@pytest.fixture
def engine() -> Engine:
    """Engine backed by an in-memory mongomock database."""
    client = mongomock.MongoClient()
    storage = MongoStorage(database=client["test_db"])
    return Engine(storage=storage)


# ====================================================================== #
# Full flow — load → plan → save → merge → execute → history → report
# ====================================================================== #


class TestMongoEngineFlow:
    def test_persistence_roundtrip(self, engine: Engine) -> None:
        result = engine.load_spec_from_source(str(FIXTURES / "petstore_v3.json"))
        plan = engine.generate_plan(result.spec)
        original_count = len(plan.test_cases)

        plan.auth_type = "bearer"
        plan.auth_value = "super-secret"
        plan.global_headers = {"X-Client": "mongo-test"}
        plan.test_cases[0].path_params["petId"] = "7"
        plan.test_cases[0].enabled = False

        engine.save_plan(plan)

        # Regenerate + merge
        plan2, merge = engine.generate_or_merge_plan(result.spec)
        assert merge is not None
        assert merge.new == 0
        assert merge.removed == 0
        assert merge.kept == original_count

        assert plan2.auth_type == "bearer"
        assert plan2.auth_value == "super-secret"
        assert plan2.global_headers == {"X-Client": "mongo-test"}
        first = plan2.test_cases[0]
        assert first.path_params.get("petId") == "7"
        assert first.enabled is False

    @pytest.mark.asyncio
    async def test_execute_save_history_render(self, engine: Engine, tmp_path: Path) -> None:
        result = engine.load_spec_from_source(str(FIXTURES / "petstore_v3.json"))
        plan = engine.generate_plan(result.spec)

        config = TestRunConfig(base_url="http://mongo-mock-server")

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"id": 1, "name": "ok"})

        with _AllPatches(_patch_all_httpx(handler)):
            runner = TestRunner(plan, config)
            report = await runner.run()

        assert report.total_tests > 0
        assert report.base_url == "http://mongo-mock-server"

        # Save to history via Mongo backend
        path = engine.save_run_to_history(report)
        assert path.startswith("mongo://")

        runs = engine.list_history(report.spec_title, report.base_url)
        assert len(runs) == 1
        assert runs[0]["total"] == report.total_tests

        loaded = engine.load_history_run(
            report.spec_title, report.base_url, runs[0]["filename"]
        )
        assert loaded is not None
        assert loaded.total_tests == report.total_tests
        assert loaded.pass_rate == report.pass_rate

        # Report renders from Mongo-loaded report just like file-loaded
        html_path = str(tmp_path / "report.html")
        generate_html_report(loaded, html_path)
        assert Path(html_path).exists()
        html = Path(html_path).read_text()
        assert plan.name in html

    @pytest.mark.asyncio
    async def test_functional_plus_performance(self, engine: Engine) -> None:
        result = engine.load_spec_from_source(str(FIXTURES / "petstore_v3.json"))
        plan = engine.generate_plan(result.spec)
        plan.test_cases = [tc for tc in plan.test_cases if tc.enabled][:1]

        config = TestRunConfig(base_url="http://mock")
        config.performance = PerformanceConfig(
            enabled=True,
            concurrent_users=1,
            duration_seconds=1,
            target_tps=100,
            ramp_up_seconds=0,
        )

        def handler(req): return httpx.Response(200)

        with _AllPatches(_patch_all_httpx(handler)):
            report = await TestRunner(plan, config).run()

        assert len(report.performance_results) >= 1
        engine.save_run_to_history(report)

        runs = engine.list_history(report.spec_title, report.base_url)
        loaded = engine.load_history_run(
            report.spec_title, report.base_url, runs[0]["filename"]
        )
        assert loaded is not None
        assert len(loaded.performance_results) >= 1

    def test_archive_plan(self, engine: Engine) -> None:
        result = engine.load_spec_from_source(str(FIXTURES / "petstore_v3.json"))
        plan = engine.generate_plan(result.spec)
        plan.auth_value = "v1-token"
        engine.save_plan(plan)

        archive_uri = engine.archive_plan(plan)
        assert archive_uri.startswith("mongo://")
        assert "plan_archives" in archive_uri

    def test_idempotent_save(self, engine: Engine) -> None:
        """Saving the same plan twice is a no-op — same spec_title key."""
        result = engine.load_spec_from_source(str(FIXTURES / "petstore_v3.json"))
        plan = engine.generate_plan(result.spec)
        plan.test_cases[0].path_params["petId"] = "id-1"

        engine.save_plan(plan)
        plan2 = engine.load_saved_plan(result.spec.title)
        assert plan2 is not None
        engine.save_plan(plan2)
        plan3 = engine.load_saved_plan(result.spec.title)

        assert plan3.test_cases[0].path_params.get("petId") == "id-1"
        assert len(plan3.test_cases) == len(plan.test_cases)
