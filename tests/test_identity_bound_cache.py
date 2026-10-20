"""Tests for Outcome Area O4: Cached Results are Identity-Bound.

Enforces:
1. No cache hit, similarity comparison, or eviction decision crosses an identity, permission, or corpus-state boundary.
2. A test inserting byte-identical query vectors under different scopes asserts a miss.
3. Invalidation tests per boundary (identity, clearance, corpus state).
4. Content above a sensitivity threshold is not cached at all.
5. Enabling semantic matching requires explicit acknowledgement.
6. Cache-hit log carries scope and tier, but zero content or query text.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.api.cache import (
    CacheConfig,
    CacheScope,
    TieredSemanticCache,
)


def test_byte_identical_query_vectors_under_different_scopes_miss() -> None:
    """Byte-identical query vectors under different identity/permission/corpus scopes MUST produce a miss."""
    config = CacheConfig(
        enable_semantic_matching=True,
        acknowledge_semantic_cache_isolation=True,
        semantic_similarity_threshold=0.95,
    )
    cache = TieredSemanticCache[str](config=config)

    scope_alpha = CacheScope(
        tenant_id="tenant-alpha",
        user_id="user-1",
        clearance_level=0,
        corpus_state="gen-1",
    )
    scope_beta = CacheScope(
        tenant_id="tenant-beta",
        user_id="user-2",
        clearance_level=0,
        corpus_state="gen-1",
    )
    scope_alpha_elevated = CacheScope(
        tenant_id="tenant-alpha",
        user_id="user-1",
        clearance_level=2,
        corpus_state="gen-1",
    )
    scope_alpha_new_corpus = CacheScope(
        tenant_id="tenant-alpha",
        user_id="user-1",
        clearance_level=0,
        corpus_state="gen-2",
    )

    q_vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)

    # Store entry under scope_alpha
    cache.put_scoped(
        scope=scope_alpha,
        query="what is the cash limit?",
        value="Alpha result",
        query_vector=q_vec,
    )

    # 1. Exact match under scope_alpha hits
    hit_val, tier = cache.get_scoped(
        scope=scope_alpha,
        query="what is the cash limit?",
        query_vector=q_vec,
    )
    assert hit_val == "Alpha result"
    assert tier in ("tier1", "semantic")

    # 2. Byte-identical vector under different tenant (scope_beta) MUST MISS
    miss_beta, _ = cache.get_scoped(
        scope=scope_beta,
        query="what is the cash limit?",
        query_vector=q_vec,
    )
    assert miss_beta is None

    # 3. Byte-identical vector under different clearance MUST MISS
    miss_elevated, _ = cache.get_scoped(
        scope=scope_alpha_elevated,
        query="what is the cash limit?",
        query_vector=q_vec,
    )
    assert miss_elevated is None

    # 4. Byte-identical vector under different corpus state MUST MISS
    miss_corpus, _ = cache.get_scoped(
        scope=scope_alpha_new_corpus,
        query="what is the cash limit?",
        query_vector=q_vec,
    )
    assert miss_corpus is None


def test_semantic_comparison_never_crosses_boundary() -> None:
    """Semantic matching (>0.98 similarity) never compares across identity boundaries."""
    config = CacheConfig(
        enable_semantic_matching=True,
        acknowledge_semantic_cache_isolation=True,
        semantic_similarity_threshold=0.90,
    )
    cache = TieredSemanticCache[str](config=config)

    scope_user_a = CacheScope(tenant_id="t1", user_id="alice", clearance_level=1, corpus_state="v1")
    scope_user_b = CacheScope(tenant_id="t1", user_id="bob", clearance_level=1, corpus_state="v1")

    vec_a = np.array([0.99, 0.01, 0.0], dtype=np.float32)
    vec_b = np.array([0.98, 0.02, 0.0], dtype=np.float32)

    cache.put_scoped(
        scope=scope_user_a, query="query one", value="Secret Alice", query_vector=vec_a
    )

    # Bob asks a semantically identical query
    res, _ = cache.get_scoped(scope=scope_user_b, query="query two", query_vector=vec_b)
    # Must never hit Alice's cached answer
    assert res is None


def test_invalidation_per_boundary() -> None:
    """Invalidation selectively strands entries by tenant, user, or corpus state."""
    cache = TieredSemanticCache[str](config=CacheConfig())
    scope_a = CacheScope(tenant_id="t1", user_id="u1", clearance_level=0, corpus_state="v1")
    scope_b = CacheScope(tenant_id="t1", user_id="u2", clearance_level=0, corpus_state="v1")

    cache.put_scoped(scope=scope_a, query="q1", value="val1")
    cache.put_scoped(scope=scope_b, query="q2", value="val2")

    # Invalidate user u1
    evicted = cache.invalidate_scope(tenant_id="t1", user_id="u1")
    assert evicted == 1

    # u1 is gone, u2 remains
    assert cache.get_scoped(scope=scope_a, query="q1")[0] is None
    assert cache.get_scoped(scope=scope_b, query="q2")[0] == "val2"

    # Invalidate corpus v1
    cache.invalidate_scope(corpus_state="v1")
    assert cache.get_scoped(scope=scope_b, query="q2")[0] is None


def test_sensitive_content_not_cached() -> None:
    """Content above sensitivity threshold is not cached."""
    cache = TieredSemanticCache[str](config=CacheConfig(max_cacheable_clearance=1))
    scope_confidential = CacheScope(
        tenant_id="t1", user_id="u1", clearance_level=2, corpus_state="v1"
    )

    stored = cache.put_scoped(
        scope=scope_confidential,
        query="sensitive query",
        value="Classified Material",
        is_sensitive=True,
    )
    assert stored is False

    # Lookup confirms it was never cached
    val, _ = cache.get_scoped(scope=scope_confidential, query="sensitive query")
    assert val is None


def test_semantic_matching_requires_explicit_acknowledgement() -> None:
    """Enabling semantic matching without explicit acknowledgement raises ValueError."""
    with pytest.raises(ValueError, match="acknowledge_semantic_cache_isolation"):
        CacheConfig(
            enable_semantic_matching=True,
            acknowledge_semantic_cache_isolation=False,
        )


def test_cache_hit_log_carries_scope_but_no_content() -> None:
    """Cache-hit log audit inspects emitted metadata: carries scope but zero query/answer text."""
    from app.api.cache import format_cache_hit_log

    scope = CacheScope(tenant_id="t1", user_id="u1", clearance_level=1, corpus_state="v1")
    log_data = format_cache_hit_log(
        scope=scope,
        hit_tier="tier1",
        query_text="What is the secret balance?",
        value="Secret balance is 1000",
    )

    assert log_data["tenant_id"] == "t1"
    assert log_data["clearance_level"] == 1
    assert log_data["hit_tier"] == "tier1"
    # Zero content allowed in log
    assert "What is the secret balance?" not in str(log_data)
    assert "Secret balance is 1000" not in str(log_data)
    assert "query_text" not in log_data
    assert "value" not in log_data
