"""Formatting helpers for report templates."""

from __future__ import annotations


def format_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.0f}s"


def format_latency(ms: float) -> str:
    if ms < 1:
        return "<1ms"
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.2f}s"


def status_color(status: str) -> str:
    return {
        "passed": "#55cc55",
        "failed": "#cc4444",
        "error": "#cc9944",
        "skipped": "#7a7a9a",
    }.get(status, "#c0c0d0")


def status_badge(status: str) -> str:
    colors = {
        "passed": "background:#1a3a1a;color:#55cc55",
        "failed": "background:#3a1a1a;color:#cc4444",
        "error": "background:#3a2a0a;color:#cc9944",
        "skipped": "background:#2a2a2a;color:#7a7a9a",
    }
    style = colors.get(status, "")
    return f'<span class="badge" style="{style}">{status.upper()}</span>'


def method_color(method: str) -> str:
    return {
        "GET": "#55cc55",
        "POST": "#cc9944",
        "PUT": "#5599dd",
        "PATCH": "#55aacc",
        "DELETE": "#cc4444",
    }.get(method, "#c0c0d0")
