from __future__ import annotations

import time

import pytest

from bridge.session_cache import TTLCache


class TestTTLCache:
    def test_basic_set_get(self):
        cache = TTLCache[str](max_size=4, ttl_seconds=10.0)
        cache["a"] = "apple"
        assert cache["a"] == "apple"
        assert cache.get("a") == "apple"
        assert len(cache) == 1

    def test_contains_missing(self):
        cache = TTLCache[str](max_size=4, ttl_seconds=10.0)
        assert "a" not in cache

    def test_contains_expired(self):
        cache = TTLCache[str](max_size=4, ttl_seconds=0.1)
        cache["a"] = "apple"
        assert "a" in cache
        time.sleep(0.15)
        assert "a" not in cache

    def test_get_updates_access_time(self):
        cache = TTLCache[str](max_size=2, ttl_seconds=0.2)
        cache["a"] = "apple"
        time.sleep(0.15)
        # Touching a should refresh its TTL
        _ = cache["a"]
        time.sleep(0.15)
        assert "a" in cache

    def test_lru_eviction(self):
        cache = TTLCache[str](max_size=2, ttl_seconds=10.0)
        cache["a"] = "apple"
        cache["b"] = "banana"
        cache["c"] = "cherry"
        assert "a" not in cache
        assert "b" in cache
        assert "c" in cache

    def test_sweep_expired(self):
        cache = TTLCache[str](max_size=4, ttl_seconds=0.1)
        cache["a"] = "apple"
        cache["b"] = "banana"
        time.sleep(0.15)
        cache["c"] = "cherry"
        evicted = cache.sweep_expired()
        assert evicted == 2
        assert "a" not in cache
        assert "b" not in cache
        assert "c" in cache

    def test_stats(self):
        cache = TTLCache[str](max_size=4, ttl_seconds=10.0)
        cache["a"] = "apple"
        stats = cache.stats()
        assert stats.size == 1
        assert stats.max_size == 4
        assert stats.ttl_seconds == 10.0
        assert stats.evicted_ttl == 0
        assert stats.evicted_lru == 0

    def test_pop(self):
        cache = TTLCache[str](max_size=4, ttl_seconds=10.0)
        cache["a"] = "apple"
        assert cache.pop("a") == "apple"
        assert "a" not in cache

    def test_delete(self):
        cache = TTLCache[str](max_size=4, ttl_seconds=10.0)
        cache["a"] = "apple"
        del cache["a"]
        assert "a" not in cache
