"""Configuration management for specs-agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

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
    # Recent specs
    recent_specs: list[RecentSpec] = field(default_factory=list)
    # Reports
    reports_output_dir: str = "~/.specs-agent/reports"
    reports_format: str = "html"
    reports_open_after: bool = True
    # Theme
    theme: str = "dark"


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
        recent_specs=recent_specs,
        reports_output_dir=reports.get("output_dir", "~/.specs-agent/reports"),
        reports_format=reports.get("format", "html"),
        reports_open_after=reports.get("open_after_export", True),
        theme=data.get("theme", "dark"),
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
    }
