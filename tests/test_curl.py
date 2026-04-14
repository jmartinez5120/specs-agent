"""Tests for cURL command generation."""

from specs_agent.curl_builder import build_curl
from specs_agent.models.plan import TestCase


class TestCurlBuilder:
    def test_simple_get(self):
        tc = TestCase(endpoint_path="/pets", method="GET")
        curl = build_curl(tc, "https://api.example.com")
        assert "curl" in curl
        assert "https://api.example.com/pets" in curl
        assert "-X" not in curl  # GET is default

    def test_post_with_body(self):
        tc = TestCase(
            endpoint_path="/pets",
            method="POST",
            body={"name": "Fido", "tag": "dog"},
        )
        curl = build_curl(tc, "https://api.example.com")
        assert "-X POST" in curl
        assert "Content-Type: application/json" in curl
        assert '"name"' in curl
        assert '"Fido"' in curl

    def test_path_params(self):
        tc = TestCase(
            endpoint_path="/pets/{petId}",
            method="GET",
            path_params={"petId": "123"},
        )
        curl = build_curl(tc, "https://api.example.com")
        assert "/pets/123" in curl
        assert "{petId}" not in curl

    def test_query_params(self):
        tc = TestCase(
            endpoint_path="/pets",
            method="GET",
            query_params={"limit": "10", "status": "active"},
        )
        curl = build_curl(tc, "https://api.example.com")
        assert "limit=10" in curl
        assert "status=active" in curl

    def test_bearer_auth(self):
        tc = TestCase(endpoint_path="/pets", method="GET")
        curl = build_curl(tc, "https://api.example.com", auth_type="bearer", auth_value="tok123")
        assert "Authorization: Bearer tok123" in curl

    def test_basic_auth(self):
        tc = TestCase(endpoint_path="/pets", method="GET")
        curl = build_curl(tc, "https://api.example.com", auth_type="basic", auth_value="user:pass")
        assert "-u" in curl
        assert "user:pass" in curl

    def test_custom_headers(self):
        tc = TestCase(
            endpoint_path="/pets",
            method="GET",
            headers={"X-Request-ID": "abc123"},
        )
        curl = build_curl(tc, "https://api.example.com")
        assert "X-Request-ID: abc123" in curl

    def test_template_vars_resolved(self):
        tc = TestCase(
            endpoint_path="/pets/{petId}",
            method="GET",
            path_params={"petId": "{{$guid}}"},
        )
        curl = build_curl(tc, "https://api.example.com")
        assert "{{" not in curl
        assert "{petId}" not in curl

    def test_delete_method(self):
        tc = TestCase(endpoint_path="/pets/1", method="DELETE")
        curl = build_curl(tc, "https://api.example.com")
        assert "-X DELETE" in curl
