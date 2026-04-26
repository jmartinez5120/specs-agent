"""Unit tests for specs_agent.reporting.formatters."""

from __future__ import annotations

from specs_agent.reporting.formatters import (
    format_duration,
    format_latency,
    method_color,
    status_badge,
    status_color,
)


class TestFormatDuration:
    def test_sub_second(self) -> None:
        assert format_duration(0.5) == "500ms"
        assert format_duration(0.001) == "1ms"
        assert format_duration(0.0) == "0ms"

    def test_seconds(self) -> None:
        assert format_duration(1.0) == "1.0s"
        assert format_duration(5.5) == "5.5s"
        assert format_duration(59.9) == "59.9s"

    def test_minutes(self) -> None:
        assert format_duration(60) == "1m 0s"
        assert format_duration(90) == "1m 30s"
        assert format_duration(3661) == "61m 1s"


class TestFormatLatency:
    def test_sub_ms(self) -> None:
        assert format_latency(0.5) == "<1ms"
        assert format_latency(0) == "<1ms"

    def test_ms_range(self) -> None:
        assert format_latency(1) == "1ms"
        assert format_latency(42.6) == "43ms"
        assert format_latency(999) == "999ms"

    def test_seconds_range(self) -> None:
        assert format_latency(1000) == "1.00s"
        assert format_latency(2500) == "2.50s"


class TestStatusColor:
    def test_known_statuses(self) -> None:
        assert status_color("passed").startswith("#")
        assert status_color("failed").startswith("#")
        assert status_color("error").startswith("#")
        assert status_color("skipped").startswith("#")

    def test_distinct_colors(self) -> None:
        colors = {status_color(s) for s in ["passed", "failed", "error", "skipped"]}
        assert len(colors) == 4

    def test_unknown_status_returns_default(self) -> None:
        assert status_color("unknown-whatever").startswith("#")


class TestStatusBadge:
    def test_contains_status_upper(self) -> None:
        assert "PASSED" in status_badge("passed")
        assert "FAILED" in status_badge("failed")

    def test_has_span_element(self) -> None:
        badge = status_badge("error")
        assert "<span" in badge
        assert "</span>" in badge
        assert 'class="badge"' in badge

    def test_unknown_status_still_renders(self) -> None:
        # Should not raise; style may be empty but badge still rendered.
        badge = status_badge("weirdstatus")
        assert "WEIRDSTATUS" in badge
        assert "<span" in badge


class TestMethodColor:
    def test_known_methods(self) -> None:
        for method in ["GET", "POST", "PUT", "PATCH", "DELETE"]:
            assert method_color(method).startswith("#")

    def test_unknown_method_returns_default(self) -> None:
        assert method_color("TRACE").startswith("#")
