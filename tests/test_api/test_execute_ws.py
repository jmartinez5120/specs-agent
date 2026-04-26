"""WebSocket tests for /ws/execute.

TestClient's websocket support is synchronous. We use a MockTransport at
the httpx layer so the runner inside the app doesn't need a live server.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient


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


def _minimal_plan() -> dict:
    return {
        "name": "WS Test Plan",
        "spec_title": "WS Spec",
        "base_url": "http://mock",
        "test_cases": [
            {
                "id": "tc1",
                "endpoint_path": "/thing/1",
                "method": "GET",
                "name": "GET /thing/1 → 200",
                "enabled": True,
                "assertions": [{"type": "status_code", "expected": 200, "description": ""}],
            },
            {
                "id": "tc2",
                "endpoint_path": "/thing/2",
                "method": "GET",
                "name": "GET /thing/2 → 200",
                "enabled": True,
                "assertions": [{"type": "status_code", "expected": 200, "description": ""}],
            },
        ],
    }


def _minimal_config() -> dict:
    return {
        "base_url": "http://mock",
        "timeout_seconds": 5.0,
    }


class TestExecuteWebSocket:
    def test_full_functional_run_streams_events(self, client: TestClient) -> None:
        """Happy path: phase → result → result → progress → complete."""
        def handler(req): return httpx.Response(200, json={"ok": True})

        payload = {"plan": _minimal_plan(), "config": _minimal_config()}

        with _AllPatches(_patch_all_httpx(handler)):
            with client.websocket_connect("/ws/execute") as ws:
                ws.send_text(json.dumps(payload))

                events: list[dict] = []
                while True:
                    try:
                        msg = ws.receive_json()
                    except Exception:
                        break
                    events.append(msg)
                    if msg.get("event") == "complete":
                        break

        event_types = [e["event"] for e in events]
        assert "phase" in event_types
        assert "result" in event_types
        assert "complete" in event_types

        # Exactly 2 result events
        results = [e for e in events if e["event"] == "result"]
        assert len(results) == 2

        # Final report
        complete = next(e for e in events if e["event"] == "complete")
        report = complete["report"]
        assert report["total_tests"] == 2
        assert report["passed_tests"] == 2
        assert report["plan_name"] == "WS Test Plan"

    def test_mixed_pass_fail_reported(self, client: TestClient) -> None:
        calls = {"n": 0}
        def handler(req):
            calls["n"] += 1
            return httpx.Response(200 if calls["n"] % 2 else 500)

        payload = {"plan": _minimal_plan(), "config": _minimal_config()}

        with _AllPatches(_patch_all_httpx(handler)):
            with client.websocket_connect("/ws/execute") as ws:
                ws.send_text(json.dumps(payload))
                events = []
                while True:
                    msg = ws.receive_json()
                    events.append(msg)
                    if msg["event"] == "complete":
                        break

        complete = next(e for e in events if e["event"] == "complete")
        report = complete["report"]
        assert report["total_tests"] == 2
        assert report["passed_tests"] == 1
        assert report["failed_tests"] == 1

    def test_invalid_payload_sends_error(self, client: TestClient) -> None:
        with client.websocket_connect("/ws/execute") as ws:
            ws.send_text("not valid json")
            msg = ws.receive_json()
            assert msg["event"] == "error"

    def test_functional_plus_performance_stream(self, client: TestClient) -> None:
        def handler(req): return httpx.Response(200)

        plan = _minimal_plan()
        plan["test_cases"] = plan["test_cases"][:1]  # one case, faster

        config = _minimal_config()
        config["performance"] = {
            "enabled": True,
            "concurrent_users": 1,
            "duration_seconds": 1,
            "ramp_up_seconds": 0,
            "target_tps": 100,
            "stages": [],
        }

        payload = {"plan": plan, "config": config}

        with _AllPatches(_patch_all_httpx(handler)):
            with client.websocket_connect("/ws/execute") as ws:
                ws.send_text(json.dumps(payload))
                events = []
                while True:
                    msg = ws.receive_json()
                    events.append(msg)
                    if msg["event"] == "complete":
                        break

        event_types = [e["event"] for e in events]
        phases = [e["phase"] for e in events if e["event"] == "phase"]
        assert "functional" in phases
        assert "performance" in phases
        assert "complete" in phases

        complete = next(e for e in events if e["event"] == "complete")
        assert len(complete["report"]["performance_results"]) >= 1
