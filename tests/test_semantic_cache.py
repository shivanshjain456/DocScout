"""Unit and integration tests for FEAT-080: Multi-Tiered Semantic Caching with Invalidation Webhooks.

Validates:
1. CacheConfig defaults (lru_maxsize=512, ttl_seconds=300, enable_semantic_matching=False).
2. Tier 1 exact match hits, misses, LRU capacity eviction, and TTL expiration.
3. Tier 2 fallback retrieval and promotion into Tier 1 MRU.
4. Cosine similarity matching (>0.98) on normalized query embeddings.
5. Search parameters isolation preventing cross-filter or cross-mode cache hits.
6. Synchronous invalidation webhook (POST /v1/admin/cache/invalidate) and listener triggers.
7. Sub-millisecond lookup latency (p95 <= 0.8ms) and Prometheus metrics emission.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.api import metrics
from app.api.app import admin_invalidate_cache, app
from app.api.cache import (
    CacheConfig,
    InMemoryTier2Backend,
    RedisTier2Backend,
    TieredCacheStats,
    TieredSemanticCache,
    trigger_corpus_invalidation,
)
from app.api.models import CacheInvalidateRequest
from app.api.security import load_keys


@pytest.fixture
def auth_headers() -> dict[str, str]:
    keys = load_keys()
    first_key = next(iter(keys))
    return {"X-API-Key": first_key}


def test_cache_config_defaults() -> None:
    """Validate canonical configuration defaults for FEAT-080."""
    cfg = CacheConfig()
    assert cfg.lru_maxsize == 512
    assert cfg.ttl_seconds == 300
    assert cfg.enable_semantic_matching is False
    assert cfg.semantic_similarity_threshold == 0.98
    assert cfg.redis_url is None


def test_tiered_cache_stats_dict() -> None:
    """Validate statistics representation across tiers."""
    stats = TieredCacheStats(
        hits=10,
        misses=5,
        evictions=2,
        tier1_hits=7,
        tier2_hits=2,
        semantic_hits=1,
        invalidations=1,
    )
    d = stats.as_dict()
    assert d["hits"] == 10
    assert d["misses"] == 5
    assert d["tier1_hits"] == 7
    assert d["tier2_hits"] == 2
    assert d["semantic_hits"] == 1
    assert d["invalidations"] == 1
    assert d["hit_rate_pct"] == 67


def test_tier1_exact_match_and_lru_eviction() -> None:
    """Verify Tier 1 exact match hit, miss, and strict LRU bound eviction."""
    cfg = CacheConfig(lru_maxsize=3, ttl_seconds=300)
    cache = TieredSemanticCache[str](config=cfg)

    # Put 3 items
    cache.put("k1", "v1")
    cache.put("k2", "v2")
    cache.put("k3", "v3")

    assert len(cache) == 3

    # Exact match hit on k1
    val, tier = cache.get_with_tier("k1")
    assert val == "v1"
    assert tier == "tier1"
    assert cache.stats.tier1_hits == 1

    # Insert k4, should evict k2 (since k1 was accessed and moved to MRU)
    cache.put("k4", "v4")
    assert len(cache) == 3
    assert cache.stats.evictions == 1

    # k2 should be missing in Tier 1, promoted from Tier 2
    assert cache.get("k2") is not None
    assert cache.stats.tier2_hits == 1


def test_tier1_ttl_expiration() -> None:
    """Verify lazy TTL expiration removes stale items on read."""
    cfg = CacheConfig(lru_maxsize=10, ttl_seconds=1)
    tier2 = InMemoryTier2Backend[str](maxsize=10)
    cache = TieredSemanticCache[str](config=cfg, tier2=tier2)

    t0 = time.monotonic()
    cache.put("key_ttl", "val_ttl", now=t0)
    # Simulate time passing beyond TTL
    future_time = t0 + 5.0
    val, tier = cache.get_with_tier("key_ttl", now=future_time)
    assert val is None
    assert tier is None
    assert len(cache) == 0


def test_tier2_fallback_and_promotion() -> None:
    """Verify that an item present only in Tier 2 is retrieved and promoted to Tier 1."""
    cfg = CacheConfig(lru_maxsize=5, ttl_seconds=300)
    tier2 = InMemoryTier2Backend[str](maxsize=10)
    tier2.put("ext_key", "ext_val")

    cache = TieredSemanticCache[str](config=cfg, tier2=tier2)
    assert len(cache) == 0

    val, tier = cache.get_with_tier("ext_key")
    assert val == "ext_val"
    assert tier == "tier2"
    assert cache.stats.tier2_hits == 1
    # Check promotion into Tier 1
    assert len(cache) == 1
    val2, tier2_check = cache.get_with_tier("ext_key")
    assert val2 == "ext_val"
    assert tier2_check == "tier1"


def test_semantic_similarity_cache_hit() -> None:
    """Verify cosine similarity matching (>0.98) on normalized query embeddings."""
    cfg = CacheConfig(
        lru_maxsize=10,
        ttl_seconds=300,
        enable_semantic_matching=True,
        semantic_similarity_threshold=0.98,
        acknowledge_semantic_cache_isolation=True,
    )
    cache = TieredSemanticCache[dict[str, Any]](config=cfg)

    # Base vector: 384-dimensional unit vector
    rng = np.random.default_rng(42)
    vec1 = rng.standard_normal(384).astype(np.float32)
    vec1 /= np.linalg.norm(vec1)

    search_params = ("hybrid", 10, False, None)

    cache.put(
        key=("what is crar for nbfc", *search_params),
        value={"answer": "Minimum CRAR is 15%"},
        query_text="what is crar for nbfc",
        query_vector=vec1,
        search_params=search_params,
    )

    # Paraphrased vector with high cosine similarity: ~0.995
    vec_noise = rng.standard_normal(384).astype(np.float32)
    vec_noise -= np.dot(vec1, vec_noise) * vec1
    vec_noise /= np.linalg.norm(vec_noise)
    alpha = 0.995
    beta = float(np.sqrt(1.0 - alpha**2))
    vec_similar = alpha * vec1 + beta * vec_noise
    cos_sim = float(np.dot(vec1, vec_similar))
    assert cos_sim > 0.98

    # Query with paraphrased vector
    result, hit_tier = cache.get_with_tier(
        key=("what is minimum crar requirement for nbfcs", *search_params),
        query_text="what is minimum crar requirement for nbfcs",
        query_vector=vec_similar,
        search_params=search_params,
    )

    assert result == {"answer": "Minimum CRAR is 15%"}
    assert hit_tier == "semantic"
    assert cache.stats.semantic_hits == 1

    # Query with orthogonal/dissimilar vector (sim < 0.98)
    vec_dissimilar = rng.standard_normal(384).astype(np.float32)
    vec_dissimilar -= np.dot(vec1, vec_dissimilar) * vec1
    vec_dissimilar /= np.linalg.norm(vec_dissimilar)
    sim_dissimilar = float(np.dot(vec1, vec_dissimilar))
    assert sim_dissimilar < 0.98

    result_miss, tier_miss = cache.get_with_tier(
        key=("unrelated query text", *search_params),
        query_text="unrelated query text",
        query_vector=vec_dissimilar,
        search_params=search_params,
    )
    assert result_miss is None
    assert tier_miss is None


def test_semantic_matching_respects_search_params() -> None:
    """Verify that semantic hits do not cross incompatible search parameters (e.g. k, mode)."""
    cfg = CacheConfig(
        lru_maxsize=10,
        enable_semantic_matching=True,
        semantic_similarity_threshold=0.98,
        acknowledge_semantic_cache_isolation=True,
    )
    cache = TieredSemanticCache[str](config=cfg)

    vec = np.ones(384, dtype=np.float32)
    vec /= np.linalg.norm(vec)

    # Stored for k=5
    cache.put(
        key=("crar query", "hybrid", 5),
        value="result_k5",
        query_text="crar query",
        query_vector=vec,
        search_params=("hybrid", 5),
    )

    # Lookup with identical vector but for k=20
    val, tier = cache.get_with_tier(
        key=("crar query paraphrased", "hybrid", 20),
        query_text="crar query paraphrased",
        query_vector=vec,
        search_params=("hybrid", 20),
    )

    # Must miss to avoid returning top-5 response for top-20 request
    assert val is None
    assert tier is None


def test_cache_clear_purges_both_tiers() -> None:
    """Verify cache.clear() purges Tier 1 and Tier 2 completely with zero stale reads."""
    cfg = CacheConfig(lru_maxsize=10)
    cache = TieredSemanticCache[str](config=cfg)

    cache.put("k1", "v1")
    cache.put("k2", "v2")
    assert len(cache) == 2

    cleared = cache.clear()
    assert cleared >= 2
    assert len(cache) == 0
    assert cache.get("k1") is None
    assert cache.get("k2") is None
    assert cache.stats.invalidations == 1


def test_admin_invalidate_cache_webhook_unit() -> None:
    """Verify admin_invalidate_cache endpoint handler logic directly with mock state."""
    req = MagicMock(spec=Request)
    fake_state = MagicMock()
    fake_state.corpus_generation = 1
    fake_state.result_cache = TieredSemanticCache[str](config=CacheConfig())
    fake_state.result_cache.put("k1", "v1")
    fake_state.corpus_chunks = 100
    fake_pool = MagicMock()
    fake_state.pool = fake_pool
    fake_conn = MagicMock()
    fake_pool.connection.return_value.__enter__.return_value = fake_conn
    fake_conn.execute.return_value.fetchone.return_value = (100,)
    req.app.state = fake_state

    payload = CacheInvalidateRequest(reason="unit_test_invalidation")
    resp = admin_invalidate_cache(payload=payload, request=req, fingerprint="test_fp")
    assert resp.status == "ok"
    assert resp.previous_generation == 1
    assert resp.new_generation == 2
    assert resp.entries_cleared >= 1
    assert fake_state.result_cache.get("k1") is None


def test_admin_invalidate_cache_webhook_integration(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Integration test: POST /v1/admin/cache/invalidate purges state and bumps generation."""
    app.state.result_cache.put("test_key", "test_val")
    prev_generation = getattr(app.state, "corpus_generation", 1)

    response = client.post(
        "/v1/admin/cache/invalidate",
        json={"reason": "integration_test_invalidation"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["previous_generation"] == prev_generation
    assert body["new_generation"] == prev_generation + 1
    assert body["entries_cleared"] >= 1

    # Verify zero stale reads
    assert app.state.result_cache.get("test_key") is None


def test_cache_hit_lookup_latency_budget() -> None:
    """Verify cache hit lookup latency <= 0.8ms p95."""
    cfg = CacheConfig(lru_maxsize=512)
    cache = TieredSemanticCache[str](config=cfg)

    # Populate 200 items
    for i in range(200):
        cache.put(f"key_{i}", f"val_{i}")

    durations_ms: list[float] = []
    for i in range(500):
        target = f"key_{i % 200}"
        t0 = time.perf_counter()
        val = cache.get(target)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        durations_ms.append(dt_ms)
        assert val == f"val_{i % 200}"

    durations_sorted = sorted(durations_ms)
    p95_ms = durations_sorted[int(len(durations_sorted) * 0.95)]
    assert p95_ms <= 0.8, f"Expected p95 <= 0.8ms, got {p95_ms:.4f}ms"


def test_corpus_invalidation_trigger() -> None:
    """Verify trigger_corpus_invalidation executes callbacks safely."""
    calls: list[str | None] = []

    def dummy_listener(reason: str | None) -> None:
        calls.append(reason)

    from app.api.cache import register_invalidation_listener, unregister_invalidation_listener

    register_invalidation_listener(dummy_listener)
    try:
        notified = trigger_corpus_invalidation("test_reason")
        assert notified >= 1
        assert "test_reason" in calls
    finally:
        unregister_invalidation_listener(dummy_listener)


def test_redis_tier2_backend_resilience() -> None:
    """Verify RedisTier2Backend handles invalid / unavailable endpoints gracefully."""
    backend = RedisTier2Backend[str](redis_url="redis://invalid.host:9999/0")
    assert backend.get("some_key") is None
    backend.put("some_key", "some_val", ttl=60)
    assert backend.clear() == 0


def test_prometheus_metrics_registration() -> None:
    """Verify Prometheus cache metrics are registered and accessible."""
    metrics.CACHE_HITS_TOTAL.labels(tier="tier1").inc()
    metrics.CACHE_HITS_TOTAL.labels(tier="tier2").inc()
    metrics.CACHE_HITS_TOTAL.labels(tier="semantic").inc()
    metrics.CACHE_MISSES_TOTAL.inc()
    metrics.CACHE_INVALIDATIONS_TOTAL.labels("test_reason").inc()

    body, _ = metrics.render()
    assert b"docscout_cache_hits_total" in body
    assert b"docscout_cache_misses_total" in body
    assert b"docscout_cache_invalidations_total" in body
