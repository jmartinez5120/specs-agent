"""Unit tests for the AI cache."""

from __future__ import annotations

from pathlib import Path

import pytest

from specs_agent.ai.cache import AICache


@pytest.fixture
def cache(tmp_path: Path) -> AICache:
    return AICache(cache_dir=tmp_path / "ai-cache")


class TestCacheKey:
    def test_deterministic(self) -> None:
        fields = [{"name": "status", "type": "string"}]
        k1 = AICache.cache_key(fields, "POST", "/missions")
        k2 = AICache.cache_key(fields, "POST", "/missions")
        assert k1 == k2
        assert len(k1) == 64  # SHA-256 hex

    def test_different_endpoint_different_key(self) -> None:
        fields = [{"name": "x", "type": "string"}]
        k1 = AICache.cache_key(fields, "GET", "/a")
        k2 = AICache.cache_key(fields, "GET", "/b")
        assert k1 != k2

    def test_different_fields_different_key(self) -> None:
        f1 = [{"name": "a", "type": "string"}]
        f2 = [{"name": "b", "type": "string"}]
        assert AICache.cache_key(f1, "GET", "/x") != AICache.cache_key(f2, "GET", "/x")

    def test_schema_hash_short(self) -> None:
        h = AICache.schema_hash({"type": "string", "description": "a field"})
        assert isinstance(h, str)
        assert len(h) == 16


class TestCacheCRUD:
    def test_get_miss(self, cache: AICache) -> None:
        assert cache.get("nonexistent") is None
        assert cache.get_value("nonexistent") is None

    def test_put_and_get(self, cache: AICache) -> None:
        path = cache.put("abc123", {"status": "IN_FLIGHT"}, schema_hash="sh", model="gemma4")
        assert path.exists()
        assert "ai-cache" in str(path)
        assert "ab" in str(path)  # two-level dir from key[:2]

        entry = cache.get("abc123")
        assert entry is not None
        assert entry["value"] == {"status": "IN_FLIGHT"}
        assert entry["schema_hash"] == "sh"
        assert entry["model"] == "gemma4"
        assert "created_at" in entry

    def test_get_value_shortcut(self, cache: AICache) -> None:
        cache.put("k1", "hello")
        assert cache.get_value("k1") == "hello"

    def test_overwrite(self, cache: AICache) -> None:
        cache.put("k", "v1")
        cache.put("k", "v2")
        assert cache.get_value("k") == "v2"

    def test_invalidate_existing(self, cache: AICache) -> None:
        cache.put("k", "v")
        assert cache.invalidate("k") is True
        assert cache.get("k") is None

    def test_invalidate_missing(self, cache: AICache) -> None:
        assert cache.invalidate("nope") is False

    def test_complex_values(self, cache: AICache) -> None:
        value = {"name": "Apollo 13", "crew": ["Jim", "Jack", "Fred"], "active": True}
        cache.put("complex", value)
        assert cache.get_value("complex") == value

    def test_corrupt_file_returns_none(self, cache: AICache) -> None:
        cache.put("bad", "ok")
        path = cache._entry_path("bad")
        path.write_text("not-json{{{")
        assert cache.get("bad") is None


class TestClearAndStats:
    def test_clear_empty(self, cache: AICache) -> None:
        assert cache.clear_all() == 0

    def test_clear_populated(self, cache: AICache) -> None:
        for i in range(10):
            cache.put(f"key{i:04d}", f"val{i}")
        count = cache.clear_all()
        assert count == 10
        assert cache.stats()["entries"] == 0

    def test_stats_empty(self, cache: AICache) -> None:
        s = cache.stats()
        assert s["entries"] == 0
        assert s["size_bytes"] == 0

    def test_stats_populated(self, cache: AICache) -> None:
        cache.put("a", "hello")
        cache.put("b", {"x": 1})
        s = cache.stats()
        assert s["entries"] == 2
        assert s["size_bytes"] > 0
        assert "ai-cache" in s["cache_dir"]


class TestTwoLevelDirectory:
    def test_entries_go_into_prefix_subdirs(self, cache: AICache) -> None:
        key = "abcdef0123456789" + "0" * 48  # starts with "ab"
        cache.put(key, "v")
        path = cache._entry_path(key)
        assert path.parent.name == "ab"
        assert path.name == f"{key}.json"

    def test_different_prefixes_different_dirs(self, cache: AICache) -> None:
        k1 = "aa" + "0" * 62
        k2 = "bb" + "0" * 62
        cache.put(k1, "v1")
        cache.put(k2, "v2")
        p1 = cache._entry_path(k1).parent
        p2 = cache._entry_path(k2).parent
        assert p1.name == "aa"
        assert p2.name == "bb"
        assert p1 != p2
