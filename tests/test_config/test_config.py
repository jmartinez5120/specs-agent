"""Unit tests for the config module."""

import os
from pathlib import Path
from unittest.mock import patch

import yaml

from specs_agent.config import (
    AppConfig,
    AuthPreset,
    RecentSpec,
    _config_from_dict,
    _config_to_dict,
    add_recent_spec,
    load_config,
    save_config,
)


class TestRecentSpec:
    def test_source_prefers_url(self):
        r = RecentSpec(path="/local/path", url="https://api.com/spec.json")
        assert r.source == "https://api.com/spec.json"

    def test_source_falls_back_to_path(self):
        r = RecentSpec(path="/local/path")
        assert r.source == "/local/path"

    def test_display_prefers_title(self):
        r = RecentSpec(title="My API", path="/some/path")
        assert r.display == "My API"

    def test_display_falls_back_to_source(self):
        r = RecentSpec(url="https://api.com/spec.json")
        assert r.display == "https://api.com/spec.json"


class TestAuthPreset:
    def test_defaults(self):
        a = AuthPreset()
        assert a.name == ""
        assert a.type == "bearer"
        assert a.header == ""
        assert a.value == ""


class TestAppConfig:
    def test_defaults(self):
        config = AppConfig()
        assert config.version == 1
        assert config.timeout_seconds == 30.0
        assert config.follow_redirects is True
        assert config.verify_ssl is True
        assert config.perf_concurrent_users == 10
        assert config.theme == "dark"
        assert config.auth_presets == []
        assert config.recent_specs == []


class TestConfigRoundtrip:
    def test_to_dict_and_back(self):
        original = AppConfig(
            base_url="http://localhost:8080",
            timeout_seconds=15.0,
            follow_redirects=False,
            verify_ssl=False,
            perf_concurrent_users=50,
            perf_duration_seconds=60,
            perf_ramp_up_seconds=10,
            perf_latency_p95_threshold_ms=1000.0,
            auth_presets=[
                AuthPreset(name="Dev", type="api_key", header="X-Key", value="secret")
            ],
            recent_specs=[
                RecentSpec(path="/test.yaml", title="Test API", last_opened="2026-01-01")
            ],
            reports_output_dir="/tmp/reports",
            reports_format="pdf",
            reports_open_after=False,
            theme="light",
        )
        data = _config_to_dict(original)
        restored = _config_from_dict(data)

        assert restored.base_url == original.base_url
        assert restored.timeout_seconds == original.timeout_seconds
        assert restored.follow_redirects == original.follow_redirects
        assert restored.verify_ssl == original.verify_ssl
        assert restored.perf_concurrent_users == original.perf_concurrent_users
        assert restored.perf_duration_seconds == original.perf_duration_seconds
        assert restored.perf_ramp_up_seconds == original.perf_ramp_up_seconds
        assert restored.perf_latency_p95_threshold_ms == original.perf_latency_p95_threshold_ms
        assert len(restored.auth_presets) == 1
        assert restored.auth_presets[0].name == "Dev"
        assert restored.auth_presets[0].type == "api_key"
        assert restored.auth_presets[0].header == "X-Key"
        assert len(restored.recent_specs) == 1
        assert restored.recent_specs[0].path == "/test.yaml"
        assert restored.reports_output_dir == "/tmp/reports"
        assert restored.reports_format == "pdf"
        assert restored.reports_open_after is False
        assert restored.theme == "light"

    def test_from_empty_dict(self):
        config = _config_from_dict({})
        assert config.version == 1
        assert config.timeout_seconds == 30.0

    def test_from_partial_dict(self):
        data = {"defaults": {"timeout_seconds": 5.0}, "theme": "light"}
        config = _config_from_dict(data)
        assert config.timeout_seconds == 5.0
        assert config.theme == "light"
        assert config.follow_redirects is True  # default preserved


class TestSaveLoadConfig:
    def test_save_and_load(self, tmp_path):
        config_dir = tmp_path / ".specs-agent"
        config_file = config_dir / "config.yaml"

        with patch("specs_agent.config.get_config_dir", return_value=config_dir), \
             patch("specs_agent.config.get_config_path", return_value=config_file):
            original = AppConfig(
                base_url="http://test:3000",
                perf_concurrent_users=25,
                theme="light",
            )
            save_config(original)

            assert config_file.exists()

            loaded = load_config()
            assert loaded.base_url == "http://test:3000"
            assert loaded.perf_concurrent_users == 25
            assert loaded.theme == "light"

    def test_load_missing_file(self, tmp_path):
        config_file = tmp_path / "nonexistent" / "config.yaml"

        with patch("specs_agent.config.get_config_path", return_value=config_file):
            config = load_config()
            assert config.version == 1  # returns default

    def test_load_corrupt_file(self, tmp_path):
        config_dir = tmp_path / ".specs-agent"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        # Write truly invalid YAML that will cause a parse error
        config_file.write_bytes(b"\x00\x01\x02\xff\xfe")

        with patch("specs_agent.config.get_config_path", return_value=config_file):
            config = load_config()
            assert config.version == 1  # returns default on error

    def test_save_creates_directory(self, tmp_path):
        config_dir = tmp_path / "new_dir" / ".specs-agent"
        config_file = config_dir / "config.yaml"

        with patch("specs_agent.config.get_config_dir", return_value=config_dir), \
             patch("specs_agent.config.get_config_path", return_value=config_file):
            save_config(AppConfig())
            assert config_dir.exists()
            assert config_file.exists()

    def test_saved_file_is_valid_yaml(self, tmp_path):
        config_dir = tmp_path / ".specs-agent"
        config_file = config_dir / "config.yaml"

        with patch("specs_agent.config.get_config_dir", return_value=config_dir), \
             patch("specs_agent.config.get_config_path", return_value=config_file):
            save_config(AppConfig())
            data = yaml.safe_load(config_file.read_text())
            assert isinstance(data, dict)
            assert "version" in data
            assert "defaults" in data


class TestAddRecentSpec:
    def test_add_file_path(self):
        config = AppConfig()
        add_recent_spec(config, "/path/to/spec.yaml", "My API")
        assert len(config.recent_specs) == 1
        assert config.recent_specs[0].path == "/path/to/spec.yaml"
        assert config.recent_specs[0].url == ""
        assert config.recent_specs[0].title == "My API"
        assert config.recent_specs[0].last_opened != ""

    def test_add_url(self):
        config = AppConfig()
        add_recent_spec(config, "https://api.com/openapi.json", "Remote API")
        assert len(config.recent_specs) == 1
        assert config.recent_specs[0].url == "https://api.com/openapi.json"
        assert config.recent_specs[0].path == ""

    def test_prepends_to_list(self):
        config = AppConfig()
        add_recent_spec(config, "/first.yaml", "First")
        add_recent_spec(config, "/second.yaml", "Second")
        assert config.recent_specs[0].title == "Second"
        assert config.recent_specs[1].title == "First"

    def test_deduplicates(self):
        config = AppConfig()
        add_recent_spec(config, "/spec.yaml", "API v1")
        add_recent_spec(config, "/other.yaml", "Other")
        add_recent_spec(config, "/spec.yaml", "API v2")  # same source, new title
        assert len(config.recent_specs) == 2
        assert config.recent_specs[0].title == "API v2"
        assert config.recent_specs[0].path == "/spec.yaml"

    def test_max_10_entries(self):
        config = AppConfig()
        for i in range(15):
            add_recent_spec(config, f"/spec_{i}.yaml", f"API {i}")
        assert len(config.recent_specs) == 10
        # Most recent should be first
        assert config.recent_specs[0].title == "API 14"
