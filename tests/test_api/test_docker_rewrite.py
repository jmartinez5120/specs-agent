"""Unit tests for the Docker-aware localhost rewrite helper.

Ensures that when the API is running inside a container, references to
`localhost` in spec URLs are transparently rewritten to
`host.docker.internal` so they resolve back to the developer's host
machine.

The rewrite is a pure function — we just patch the "am I in Docker?"
detector on/off.
"""

from __future__ import annotations

import pytest

from specs_agent.api.app import (
    _LOOPBACK_HOSTS,
    _running_in_docker,
    rewrite_localhost_for_docker,
)


@pytest.fixture
def in_docker(monkeypatch):
    monkeypatch.setenv("SPECS_AGENT_IN_DOCKER", "1")


@pytest.fixture
def not_in_docker(monkeypatch, tmp_path):
    monkeypatch.setenv("SPECS_AGENT_IN_DOCKER", "0")
    # Guarantee the fallback check can't pick up /.dockerenv on a CI host
    # running inside Docker — the explicit env var takes priority.


class TestLoopbackHosts:
    def test_includes_all_expected_loopbacks(self) -> None:
        assert "localhost" in _LOOPBACK_HOSTS
        assert "127.0.0.1" in _LOOPBACK_HOSTS
        assert "::1" in _LOOPBACK_HOSTS
        assert "0.0.0.0" in _LOOPBACK_HOSTS


class TestDetectDockerEnv:
    def test_explicit_true(self, monkeypatch) -> None:
        monkeypatch.setenv("SPECS_AGENT_IN_DOCKER", "1")
        assert _running_in_docker() is True

    def test_explicit_true_case_insensitive(self, monkeypatch) -> None:
        for val in ("true", "TRUE", "Yes", "yes"):
            monkeypatch.setenv("SPECS_AGENT_IN_DOCKER", val)
            assert _running_in_docker() is True

    def test_explicit_false(self, monkeypatch) -> None:
        monkeypatch.setenv("SPECS_AGENT_IN_DOCKER", "0")
        assert _running_in_docker() is False

    def test_explicit_false_overrides_dockerenv(self, monkeypatch) -> None:
        """Explicit 0 wins even if /.dockerenv marker exists — useful for
        running the tests inside a dev container without triggering the
        rewrite."""
        monkeypatch.setenv("SPECS_AGENT_IN_DOCKER", "0")
        assert _running_in_docker() is False

    def test_unset_falls_back_to_dockerenv_marker(self, monkeypatch, tmp_path) -> None:
        monkeypatch.delenv("SPECS_AGENT_IN_DOCKER", raising=False)
        # Force the Path check to return False by patching Path.exists
        import specs_agent.api.app as app_mod

        class FakePath:
            def __init__(self, _p): pass
            def exists(self): return False

        monkeypatch.setattr(app_mod, "Path", FakePath)
        assert _running_in_docker() is False


class TestRewriteSkipped:
    def test_empty_source(self, in_docker) -> None:
        assert rewrite_localhost_for_docker("") == ""

    def test_non_string(self, in_docker) -> None:
        # Defensive: guard against unexpected inputs
        assert rewrite_localhost_for_docker(None) is None  # type: ignore[arg-type]

    def test_file_path_unchanged(self, in_docker) -> None:
        assert rewrite_localhost_for_docker("/tmp/spec.yaml") == "/tmp/spec.yaml"
        assert rewrite_localhost_for_docker("./petstore.json") == "./petstore.json"
        assert rewrite_localhost_for_docker("file:///tmp/spec.yaml") == "file:///tmp/spec.yaml"

    def test_non_loopback_url_unchanged(self, in_docker) -> None:
        assert (
            rewrite_localhost_for_docker("https://petstore3.swagger.io/api/v3/openapi.json")
            == "https://petstore3.swagger.io/api/v3/openapi.json"
        )
        assert (
            rewrite_localhost_for_docker("http://10.0.0.5:8080/spec")
            == "http://10.0.0.5:8080/spec"
        )

    def test_not_in_docker_unchanged(self, not_in_docker) -> None:
        assert (
            rewrite_localhost_for_docker("http://localhost:8080/spec")
            == "http://localhost:8080/spec"
        )
        assert (
            rewrite_localhost_for_docker("http://127.0.0.1:8080/spec")
            == "http://127.0.0.1:8080/spec"
        )


class TestRewriteApplied:
    def test_localhost_http(self, in_docker) -> None:
        assert (
            rewrite_localhost_for_docker("http://localhost:8080/v3/api-docs")
            == "http://host.docker.internal:8080/v3/api-docs"
        )

    def test_localhost_https(self, in_docker) -> None:
        assert (
            rewrite_localhost_for_docker("https://localhost:8443/openapi.json")
            == "https://host.docker.internal:8443/openapi.json"
        )

    def test_127_0_0_1(self, in_docker) -> None:
        assert (
            rewrite_localhost_for_docker("http://127.0.0.1:8080/spec")
            == "http://host.docker.internal:8080/spec"
        )

    def test_ipv6_loopback(self, in_docker) -> None:
        assert (
            rewrite_localhost_for_docker("http://[::1]:8080/spec")
            == "http://host.docker.internal:8080/spec"
        )

    def test_0_0_0_0(self, in_docker) -> None:
        assert (
            rewrite_localhost_for_docker("http://0.0.0.0:8080/spec")
            == "http://host.docker.internal:8080/spec"
        )

    def test_no_port(self, in_docker) -> None:
        assert (
            rewrite_localhost_for_docker("http://localhost/spec")
            == "http://host.docker.internal/spec"
        )

    def test_preserves_path_query_fragment(self, in_docker) -> None:
        src = "http://localhost:8080/api/v3/api-docs?format=json&pretty=1#section"
        expected = (
            "http://host.docker.internal:8080/api/v3/api-docs?format=json&pretty=1#section"
        )
        assert rewrite_localhost_for_docker(src) == expected

    def test_preserves_userinfo(self, in_docker) -> None:
        src = "http://user:pass@localhost:8080/spec"
        assert (
            rewrite_localhost_for_docker(src)
            == "http://user:pass@host.docker.internal:8080/spec"
        )

    def test_preserves_username_only(self, in_docker) -> None:
        src = "http://user@localhost:8080/spec"
        assert (
            rewrite_localhost_for_docker(src)
            == "http://user@host.docker.internal:8080/spec"
        )

    def test_case_insensitive_host(self, in_docker) -> None:
        assert (
            rewrite_localhost_for_docker("http://LOCALHOST:8080/spec")
            == "http://host.docker.internal:8080/spec"
        )

    def test_idempotent(self, in_docker) -> None:
        first = rewrite_localhost_for_docker("http://localhost:8080/spec")
        second = rewrite_localhost_for_docker(first)
        # Already rewritten — nothing else to change
        assert first == second == "http://host.docker.internal:8080/spec"


class TestLoadSpecRouteIntegration:
    """End-to-end: POST /specs/load with a localhost URL when the API
    thinks it's in Docker. We patch the engine's loader to capture the
    effective source it receives."""

    def test_load_spec_uses_rewritten_source(self, client, monkeypatch) -> None:
        monkeypatch.setenv("SPECS_AGENT_IN_DOCKER", "1")

        captured: dict = {}

        def fake_load(source: str):
            captured["source"] = source
            # Raise a SpecLoadError so we don't need a real HTTP call
            from specs_agent.parsing.loader import SpecLoadError
            raise SpecLoadError("mocked")

        from specs_agent.engine import Engine as EngineCls
        monkeypatch.setattr(
            EngineCls, "load_spec_from_source",
            lambda self, s: fake_load(s),
        )

        r = client.post(
            "/specs/load",
            json={"source": "http://localhost:8080/v3/api-docs"},
        )
        assert r.status_code == 400
        assert captured["source"] == "http://host.docker.internal:8080/v3/api-docs"
        # The error message should include the rewrite hint
        assert "host.docker.internal" in r.json()["detail"]

    def test_load_spec_public_url_unchanged(self, client, monkeypatch) -> None:
        monkeypatch.setenv("SPECS_AGENT_IN_DOCKER", "1")

        captured: dict = {}

        def fake_load(source: str):
            captured["source"] = source
            from specs_agent.parsing.loader import SpecLoadError
            raise SpecLoadError("mocked")

        from specs_agent.engine import Engine as EngineCls
        monkeypatch.setattr(
            EngineCls, "load_spec_from_source",
            lambda self, s: fake_load(s),
        )

        r = client.post(
            "/specs/load",
            json={"source": "https://petstore3.swagger.io/api/v3/openapi.json"},
        )
        assert r.status_code == 400
        assert captured["source"] == "https://petstore3.swagger.io/api/v3/openapi.json"
        # No rewrite → no hint in the error
        assert "host.docker.internal" not in r.json()["detail"]
