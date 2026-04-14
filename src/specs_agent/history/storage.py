"""Persist and load test run history to disk."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from specs_agent.models.results import (
    AssertionResult,
    PerformanceMetrics,
    Report,
    TestResult,
    TestStatus,
)

HISTORY_DIR = Path.home() / ".specs-agent" / "history"


def _spec_hash(spec_title: str, base_url: str) -> str:
    """Stable hash for a spec (title + base_url)."""
    key = f"{spec_title}|{base_url}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _get_spec_dir(spec_title: str, base_url: str) -> Path:
    h = _spec_hash(spec_title, base_url)
    safe_name = spec_title.replace(" ", "_").lower()[:30]
    return HISTORY_DIR / f"{safe_name}_{h}"


def save_run(report: Report) -> str:
    """Save a test run report to history. Returns the file path."""
    spec_dir = _get_spec_dir(report.spec_title, report.base_url)
    spec_dir.mkdir(parents=True, exist_ok=True)

    timestamp = report.started_at[:19].replace(":", "-").replace("T", "_")
    filename = f"run_{timestamp}.json"
    path = spec_dir / filename

    data = _report_to_dict(report)
    path.write_text(json.dumps(data, indent=2, default=str))

    # Update index
    _update_index(spec_dir, report, filename)

    return str(path)


def list_runs(spec_title: str, base_url: str, limit: int = 20) -> list[dict]:
    """List recent runs for a spec. Returns list of run summaries."""
    spec_dir = _get_spec_dir(spec_title, base_url)
    index_path = spec_dir / "index.json"
    if not index_path.exists():
        return []

    try:
        index = json.loads(index_path.read_text())
        runs = index.get("runs", [])
        return runs[:limit]
    except Exception:
        return []


def load_run(spec_title: str, base_url: str, filename: str) -> Report | None:
    """Load a specific run from history."""
    spec_dir = _get_spec_dir(spec_title, base_url)
    path = spec_dir / filename
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text())
        return _dict_to_report(data)
    except Exception:
        return None


def _update_index(spec_dir: Path, report: Report, filename: str) -> None:
    """Update the index.json with the new run."""
    index_path = spec_dir / "index.json"
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text())
        except Exception:
            index = {"spec_title": report.spec_title, "base_url": report.base_url, "runs": []}
    else:
        index = {"spec_title": report.spec_title, "base_url": report.base_url, "runs": []}

    # Aggregate performance metrics
    perf = report.performance_results
    total_perf_reqs = sum(pm.total_requests for pm in perf)
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
        "perf_requests": total_perf_reqs,
        "perf_avg_ms": round(avg_latency, 1),
        "perf_p95_ms": round(max_p95, 1),
        "perf_p99_ms": round(max_p99, 1),
        "perf_rps": round(total_rps, 1),
        "perf_err_pct": round(avg_err, 1),
    }

    # Prepend (newest first)
    index["runs"].insert(0, summary)
    # Keep max 50 runs
    index["runs"] = index["runs"][:50]

    index_path.write_text(json.dumps(index, indent=2))


def _report_to_dict(report: Report) -> dict:
    return {
        "plan_name": report.plan_name,
        "base_url": report.base_url,
        "spec_title": report.spec_title,
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "duration_seconds": report.duration_seconds,
        "functional_results": [
            {
                "test_case_id": r.test_case_id,
                "test_case_name": r.test_case_name,
                "endpoint": r.endpoint,
                "method": r.method,
                "status": r.status.value,
                "status_code": r.status_code,
                "response_time_ms": r.response_time_ms,
                "error_message": r.error_message,
                "assertion_results": [
                    {
                        "assertion_type": a.assertion_type,
                        "expected": str(a.expected),
                        "actual": str(a.actual),
                        "passed": a.passed,
                        "message": a.message,
                    }
                    for a in r.assertion_results
                ],
            }
            for r in report.functional_results
        ],
        "performance_results": [
            {
                "endpoint": pm.endpoint,
                "method": pm.method,
                "total_requests": pm.total_requests,
                "successful_requests": pm.successful_requests,
                "failed_requests": pm.failed_requests,
                "avg_latency_ms": pm.avg_latency_ms,
                "p50_latency_ms": pm.p50_latency_ms,
                "p95_latency_ms": pm.p95_latency_ms,
                "p99_latency_ms": pm.p99_latency_ms,
                "min_latency_ms": pm.min_latency_ms,
                "max_latency_ms": pm.max_latency_ms,
                "requests_per_second": pm.requests_per_second,
                "error_rate_pct": pm.error_rate_pct,
                "sla_p95_ms": pm.sla_p95_ms,
                "sla_p99_ms": pm.sla_p99_ms,
                "sla_throughput_rps": pm.sla_throughput_rps,
                "sla_timeout_ms": pm.sla_timeout_ms,
            }
            for pm in report.performance_results
        ],
    }


def _dict_to_report(data: dict) -> Report:
    functional = []
    for r in data.get("functional_results", []):
        functional.append(TestResult(
            test_case_id=r.get("test_case_id", ""),
            test_case_name=r.get("test_case_name", ""),
            endpoint=r.get("endpoint", ""),
            method=r.get("method", ""),
            status=TestStatus(r.get("status", "error")),
            status_code=r.get("status_code"),
            response_time_ms=r.get("response_time_ms", 0),
            error_message=r.get("error_message", ""),
            assertion_results=[
                AssertionResult(
                    assertion_type=a.get("assertion_type", ""),
                    expected=a.get("expected"),
                    actual=a.get("actual"),
                    passed=a.get("passed", False),
                    message=a.get("message", ""),
                )
                for a in r.get("assertion_results", [])
            ],
        ))

    performance = []
    for pm in data.get("performance_results", []):
        performance.append(PerformanceMetrics(
            endpoint=pm.get("endpoint", ""),
            method=pm.get("method", ""),
            total_requests=pm.get("total_requests", 0),
            successful_requests=pm.get("successful_requests", 0),
            failed_requests=pm.get("failed_requests", 0),
            avg_latency_ms=pm.get("avg_latency_ms", 0),
            p50_latency_ms=pm.get("p50_latency_ms", 0),
            p95_latency_ms=pm.get("p95_latency_ms", 0),
            p99_latency_ms=pm.get("p99_latency_ms", 0),
            min_latency_ms=pm.get("min_latency_ms", 0),
            max_latency_ms=pm.get("max_latency_ms", 0),
            requests_per_second=pm.get("requests_per_second", 0),
            error_rate_pct=pm.get("error_rate_pct", 0),
            sla_p95_ms=pm.get("sla_p95_ms"),
            sla_p99_ms=pm.get("sla_p99_ms"),
            sla_throughput_rps=pm.get("sla_throughput_rps"),
            sla_timeout_ms=pm.get("sla_timeout_ms"),
        ))

    return Report(
        plan_name=data.get("plan_name", ""),
        base_url=data.get("base_url", ""),
        spec_title=data.get("spec_title", ""),
        started_at=data.get("started_at", ""),
        finished_at=data.get("finished_at", ""),
        duration_seconds=data.get("duration_seconds", 0),
        functional_results=functional,
        performance_results=performance,
    )
