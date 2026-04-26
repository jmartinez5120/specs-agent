"""End-to-end integration test for the specs-agent API.

Drives the entire backend through HTTP + WebSocket in one flow:

    POST /specs/load
      → POST /plans/generate-or-merge
        → (user edits plan)
          → POST /plans/save
            → WS /ws/execute (streams events + final report)
              → POST /reports/html (render the report)
                → GET /history
                  → GET /history/run

Verifies that the API contract is wide enough to support a full Web UI
session. Every step exercises the engine, storage, runner, and reporting
layers — the API is just the transport.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import httpx
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


class TestFullAPIFlow:
    def test_spec_to_plan_to_execute_to_report(
        self, client: TestClient, petstore_spec: str
    ) -> None:
        # 1. Load spec
        r = client.post("/specs/load", json={"source": petstore_spec})
        assert r.status_code == 200
        spec_data = r.json()["spec"]
        spec_title = spec_data["title"]
        raw_spec = spec_data["raw_spec"]

        # 2. Generate-or-merge (no saved plan → merge is null)
        r = client.post(
            "/plans/generate-or-merge",
            json={"spec": {"raw_spec": raw_spec, "source": petstore_spec}},
        )
        assert r.status_code == 200
        assert r.json()["merge"] is None
        plan = r.json()["plan"]
        assert len(plan["test_cases"]) > 0

        # 3. Simulate user edit: override base_url + disable all but the first 3 cases
        plan["base_url"] = "http://mock-server"
        for i, tc in enumerate(plan["test_cases"]):
            tc["enabled"] = i < 3
        plan["auth_type"] = "bearer"
        plan["auth_value"] = "test-token"

        # 4. Save edited plan
        r = client.post("/plans/save", json={"plan": plan})
        assert r.status_code == 200
        assert Path(r.json()["path"]).exists()

        # 5. Regenerate — should merge back our edits
        r = client.post(
            "/plans/generate-or-merge",
            json={"spec": {"raw_spec": raw_spec, "source": petstore_spec}},
        )
        body = r.json()
        assert body["merge"] is not None
        assert body["merge"]["kept"] > 0
        assert body["plan"]["auth_type"] == "bearer"
        assert body["plan"]["auth_value"] == "test-token"
        merged_plan = body["plan"]

        # 6. Execute via WebSocket with a MockTransport backing httpx
        def handler(req): return httpx.Response(
            200, json={"id": 1, "name": "ok"}
        )

        payload = {
            "plan": merged_plan,
            "config": {
                "base_url": "http://mock-server",
                "timeout_seconds": 5.0,
            },
        }

        with _AllPatches(_patch_all_httpx(handler)):
            with client.websocket_connect("/ws/execute") as ws:
                ws.send_text(json.dumps(payload))
                events = []
                while True:
                    msg = ws.receive_json()
                    events.append(msg)
                    if msg["event"] == "complete":
                        break

        # Assert stream had all expected event types
        event_types = {e["event"] for e in events}
        assert {"phase", "progress", "result", "complete"} <= event_types

        complete = next(e for e in events if e["event"] == "complete")
        report_dict = complete["report"]
        assert report_dict["total_tests"] > 0
        assert report_dict["plan_name"] == merged_plan["name"]

        # 7. Render the report as HTML
        r = client.post(
            "/reports/html",
            json={"report": report_dict},
        )
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert merged_plan["name"] in r.text

        # 8. History: the WebSocket route auto-saved the run → list should be non-empty
        base_url = report_dict["base_url"]
        r = client.get(
            "/history",
            params={"spec_title": spec_title, "base_url": base_url},
        )
        assert r.status_code == 200
        runs = r.json()
        assert len(runs) >= 1
        first = runs[0]
        assert first["total"] == report_dict["total_tests"]

        # 9. Load the specific run back
        r = client.get(
            "/history/run",
            params={
                "spec_title": spec_title,
                "base_url": base_url,
                "filename": first["filename"],
            },
        )
        assert r.status_code == 200
        loaded = r.json()
        assert loaded["total_tests"] == report_dict["total_tests"]
        assert loaded["pass_rate"] == report_dict["pass_rate"]
