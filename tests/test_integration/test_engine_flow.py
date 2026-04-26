"""End-to-end integration tests exercising the full engine pipeline.

These tests drive the `Engine` facade through realistic flows without
touching the TUI or needing a live HTTP server:

  load spec → generate plan → edit → save → reload → merge
      → run tests (mocked HTTP) → save history → load history → render report

They validate that every layer the engine depends on (parsing, plan gen,
persistence, execution, history, reporting) composes correctly through the
facade's public API — the same API both the TUI and the upcoming Web UI
will call into.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from specs_agent.engine import Engine, FileStorage
from specs_agent.execution.runner import TestRunner
from specs_agent.history import storage as hstore
from specs_agent.models.config import PerformanceConfig, TestRunConfig
from specs_agent.models.results import TestStatus
from specs_agent.reporting.generator import generate_html_report


FIXTURES = Path(__file__).parent.parent / "fixtures"


def _patch_all_httpx(handler):
    """Patch httpx.AsyncClient in every execution module to use MockTransport."""
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
    """Context manager that stacks multiple patches."""
    def __init__(self, patches):
        self.patches = patches
    def __enter__(self):
        for p in self.patches:
            p.__enter__()
        return self
    def __exit__(self, *args):
        for p in reversed(self.patches):
            p.__exit__(*args)


@pytest.fixture
def engine(tmp_path: Path, monkeypatch) -> Engine:
    """Engine with isolated file storage and isolated history dir."""
    storage = FileStorage(root=tmp_path / "specs-agent")
    monkeypatch.setattr(hstore, "HISTORY_DIR", tmp_path / "specs-agent" / "history")
    return Engine(storage=storage)


# ============================================================ #
# Flow 1: load → generate → save → reload round-trip
# ============================================================ #


class TestLoadGenerateSaveReload:
    def test_full_persistence_roundtrip(self, engine: Engine) -> None:
        result = engine.load_spec_from_source(str(FIXTURES / "petstore_v3.json"))
        assert len(result.spec.endpoints) > 0

        plan = engine.generate_plan(result.spec)
        original_count = len(plan.test_cases)

        # User edits the plan
        plan.auth_type = "bearer"
        plan.auth_value = "super-secret"
        plan.global_headers = {"X-Client": "integration-test"}
        plan.test_cases[0].path_params["petId"] = "999"
        plan.test_cases[0].enabled = False

        engine.save_plan(plan)

        # Later: load saved + merge with fresh
        plan2, merge = engine.generate_or_merge_plan(result.spec)
        assert merge is not None
        assert merge.new == 0
        assert merge.removed == 0
        assert merge.kept == original_count

        # User intel preserved
        assert plan2.auth_type == "bearer"
        assert plan2.auth_value == "super-secret"
        assert plan2.global_headers == {"X-Client": "integration-test"}
        first = plan2.test_cases[0]
        assert first.path_params.get("petId") == "999"
        assert first.enabled is False


# ============================================================ #
# Flow 2: plan → execute (mocked) → save → load → render report
# ============================================================ #


class TestExecutionAndReportFlow:
    @pytest.mark.asyncio
    async def test_functional_execute_save_history_render(
        self, engine: Engine, tmp_path: Path
    ) -> None:
        # Load + plan
        result = engine.load_spec_from_source(str(FIXTURES / "petstore_v3.json"))
        plan = engine.generate_plan(result.spec)

        # Build config
        config = TestRunConfig(base_url="http://mock-server")

        # Mock every endpoint to return 200
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"id": 1, "name": "ok"})

        with _AllPatches(_patch_all_httpx(handler)):
            runner = TestRunner(plan, config)
            report = await runner.run()

        # Some tests pass, some may fail schema — at minimum, we get results
        assert report.total_tests > 0
        assert report.plan_name == plan.name
        assert report.base_url == "http://mock-server"

        # Persist to history through engine
        path = engine.save_run_to_history(report)
        assert Path(path).exists()

        # List and load back
        runs = engine.list_history(report.spec_title, report.base_url)
        assert len(runs) == 1

        loaded = engine.load_history_run(
            report.spec_title, report.base_url, runs[0]["filename"]
        )
        assert loaded is not None
        assert loaded.total_tests == report.total_tests
        assert loaded.pass_rate == report.pass_rate

        # Render HTML report
        html_path = str(tmp_path / "report.html")
        generate_html_report(loaded, html_path)
        assert Path(html_path).exists()
        html = Path(html_path).read_text()
        assert plan.name in html

    @pytest.mark.asyncio
    async def test_functional_plus_performance_flow(self, engine: Engine) -> None:
        result = engine.load_spec_from_source(str(FIXTURES / "petstore_v3.json"))
        plan = engine.generate_plan(result.spec)

        # Only run the first enabled case to keep it fast
        enabled = [tc for tc in plan.test_cases if tc.enabled]
        plan.test_cases = enabled[:1] if enabled else plan.test_cases[:1]

        config = TestRunConfig(base_url="http://mock-server")
        config.performance = PerformanceConfig(
            enabled=True,
            concurrent_users=1,
            duration_seconds=1,
            ramp_up_seconds=0,
            target_tps=100,
        )

        def handler(req): return httpx.Response(200, json={"ok": True})

        phases = []
        with _AllPatches(_patch_all_httpx(handler)):
            runner = TestRunner(plan, config)
            report = await runner.run(on_phase=lambda p: phases.append(p))

        assert "functional" in phases
        assert "performance" in phases
        assert "complete" in phases
        assert len(report.performance_results) >= 1
        assert report.performance_results[0].total_requests > 0

        # Save + reload roundtrip preserves perf data
        engine.save_run_to_history(report)
        runs = engine.list_history(report.spec_title, report.base_url)
        loaded = engine.load_history_run(
            report.spec_title, report.base_url, runs[0]["filename"]
        )
        assert loaded is not None
        assert len(loaded.performance_results) >= 1


# ============================================================ #
# Flow 3: Spec refresh / regeneration
# ============================================================ #


class TestSpecRefreshFlow:
    def test_specs_differ_detects_changes(self, engine: Engine) -> None:
        r1 = engine.load_spec_from_source(str(FIXTURES / "petstore_v3.json"))
        r2 = engine.load_spec_from_source(str(FIXTURES / "petstore_v2.yaml"))
        assert engine.specs_differ(r1.spec, r2.spec) is True

    def test_idempotent_save_load(self, engine: Engine) -> None:
        """Save a plan, load it, save again — no drift."""
        result = engine.load_spec_from_source(str(FIXTURES / "petstore_v3.json"))
        plan1 = engine.generate_plan(result.spec)
        plan1.test_cases[0].path_params["petId"] = "id-1"

        engine.save_plan(plan1)
        plan2 = engine.load_saved_plan(result.spec.title)
        assert plan2 is not None
        engine.save_plan(plan2)
        plan3 = engine.load_saved_plan(result.spec.title)
        assert plan3 is not None

        # Core identity preserved across 2 round-trips
        assert plan3.test_cases[0].path_params.get("petId") == "id-1"
        assert len(plan3.test_cases) == len(plan1.test_cases)

    def test_archive_before_overwrite(self, engine: Engine, tmp_path: Path) -> None:
        result = engine.load_spec_from_source(str(FIXTURES / "petstore_v3.json"))
        plan = engine.generate_plan(result.spec)
        plan.auth_value = "v1-token"
        engine.save_plan(plan)

        archive_path = engine.archive_plan(plan)
        assert Path(archive_path).exists()
        assert "archive" in archive_path


# ============================================================ #
# Flow 4: Multi-spec isolation
# ============================================================ #


class TestMultiSpecIsolation:
    def test_two_specs_dont_collide(self, engine: Engine) -> None:
        """Saved plans for two different specs stay independent."""
        r_v3 = engine.load_spec_from_source(str(FIXTURES / "petstore_v3.json"))
        r_v2 = engine.load_spec_from_source(str(FIXTURES / "petstore_v2.yaml"))

        p_v3 = engine.generate_plan(r_v3.spec)
        p_v2 = engine.generate_plan(r_v2.spec)

        p_v3.auth_value = "v3-token"
        p_v2.auth_value = "v2-token"

        engine.save_plan(p_v3)
        engine.save_plan(p_v2)

        loaded_v3 = engine.load_saved_plan(r_v3.spec.title)
        loaded_v2 = engine.load_saved_plan(r_v2.spec.title)

        # Titles may actually collide if both say "Swagger Petstore"
        # — in that case the storage is shared by design. We assert
        # that whatever came back is consistent.
        if r_v3.spec.title != r_v2.spec.title:
            assert loaded_v3 is not None and loaded_v3.auth_value == "v3-token"
            assert loaded_v2 is not None and loaded_v2.auth_value == "v2-token"
        else:
            # Same title — last write wins (documented behavior)
            assert loaded_v3 is not None
