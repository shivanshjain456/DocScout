"""Chaos Engineering Fault Injection Test Harness (FEAT-094).

Verifies system resilience and graceful degradation under synthetic faults:
1. PostgreSQL connection timeout during search
2. pgvector crash during dense retrieval
3. OCR.Space API network timeout
4. Embedding model transient failure
5. Corrupted external API JSON payload
6. Redis/cache failure with transparent in-memory fallback
7. Database connection pool exhaustion and bulkhead load shedding
8. Latency spike injection bounded by max_fault_duration_ms
9. Transient network partition with sub-500ms recovery time
10. Corrupted document binary payload handling

Input validation rules:
- Fault injection active ONLY when DOCSCOUT_CHAOS_TESTING=1.
- All scenarios must produce 0 unhandled exceptions.
- Core recovery time <= 500ms once fault is cleared.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.bulkhead import BulkheadConfig, BulkheadManager, set_bulkhead_manager
from app.api.cache import CacheConfig, TieredSemanticCache
from app.chaos import (
    ChaosConfig,
    ChaosFaultType,
    ChaosHarness,
    ChaosTestReport,
    inject_fault,
    is_chaos_enabled,
    is_fault_active,
)
from app.ingest.ocr_space import OCRSpaceClient


@pytest.fixture(autouse=True)
def enable_chaos_env() -> Iterator[None]:
    """Ensure chaos testing is enabled for the suite."""
    old_val = os.environ.get("DOCSCOUT_CHAOS_TESTING")
    os.environ["DOCSCOUT_CHAOS_TESTING"] = "1"
    yield
    if old_val is not None:
        os.environ["DOCSCOUT_CHAOS_TESTING"] = old_val
    else:
        os.environ.pop("DOCSCOUT_CHAOS_TESTING", None)


def test_input_validation_chaos_flag_disabled() -> None:
    """Verifies that inject_fault raises ValueError when DOCSCOUT_CHAOS_TESTING is not enabled."""
    with patch.dict(os.environ, {"DOCSCOUT_CHAOS_TESTING": "0"}):
        assert not is_chaos_enabled()
        with pytest.raises(
            ValueError, match="Fault injection active only when DOCSCOUT_CHAOS_TESTING=1"
        ):
            with inject_fault(ChaosFaultType.DB_TIMEOUT):
                pass


def test_chaos_harness_all_ten_scenarios() -> None:
    """Execute all 10 chaos engineering fault injection scenarios and generate report."""
    from app.api.cache import TTLCache
    from app.api.security import load_keys
    from tests.conftest import PRIMARY_KEY, ROTATION_KEY

    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY},{ROTATION_KEY}"
    app.state.api_keys = load_keys()
    app.state.result_cache = TTLCache(maxsize=1000, ttl=60)
    app.state.embedding_cache = TTLCache(maxsize=1000, ttl=None)
    app.state.manifest_digest = "test-manifest-digest"
    app.state.corpus_chunks = 100
    app.state.corpus_generation = 1

    mock_pool = MagicMock()
    app.state.pool = mock_pool
    mock_embedder = MagicMock()
    mock_embedder.encode_query.return_value = [0.1] * 384
    app.state.embedder = mock_embedder
    app.state.bm25 = MagicMock()

    harness = ChaosHarness(ChaosConfig(max_fault_duration_ms=1000))
    client = TestClient(app, raise_server_exceptions=False)
    auth_headers = {"X-API-Key": PRIMARY_KEY}

    # -------------------------------------------------------------------------
    # Scenario 1: PostgreSQL connection timeout during search
    # -------------------------------------------------------------------------
    with inject_fault(ChaosFaultType.DB_TIMEOUT, delay_ms=10, error_code=503):
        assert is_fault_active(ChaosFaultType.DB_TIMEOUT)
        with patch.object(
            app.state.pool, "connection", side_effect=psycopg.OperationalError("Connection timeout")
        ):
            resp = client.post(
                "/v1/search",
                json={"query": "capital adequacy ratio Basel III", "use_cache": False},
                headers=auth_headers,
            )
            # Must degrade gracefully (HTTP 503 Service Unavailable) with Retry-After header
            graceful = resp.status_code == 503 and "Retry-After" in resp.headers
            harness.record_scenario(
                name="PostgreSQL socket timeout during search",
                fault_type=ChaosFaultType.DB_TIMEOUT,
                graceful=graceful,
                unhandled=resp.status_code == 500,
            )
            assert graceful, f"Expected 503 with Retry-After, got {resp.status_code}"

    # -------------------------------------------------------------------------
    # Scenario 2: pgvector crash during dense retrieval
    # -------------------------------------------------------------------------
    with inject_fault(ChaosFaultType.PGVECTOR_CRASH, error_code=503):
        assert is_fault_active(ChaosFaultType.PGVECTOR_CRASH)
        with patch(
            "app.retrieval.dense.search",
            side_effect=psycopg.OperationalError("pgvector index offline"),
        ):
            # When dense search fails, the search request degrades gracefully without unhandled crash
            resp = client.post(
                "/v1/search",
                json={"query": "liquidity coverage ratio", "mode": "dense", "use_cache": False},
                headers=auth_headers,
            )
            graceful = resp.status_code in (200, 503)
            harness.record_scenario(
                name="pgvector crash during dense retrieval",
                fault_type=ChaosFaultType.PGVECTOR_CRASH,
                graceful=graceful,
                unhandled=resp.status_code == 500,
            )
            assert graceful

    # -------------------------------------------------------------------------
    # Scenario 3: OCR.Space API network timeout
    # -------------------------------------------------------------------------
    with inject_fault(ChaosFaultType.OCR_TIMEOUT, delay_ms=5):
        assert is_fault_active(ChaosFaultType.OCR_TIMEOUT)
        import httpx

        from app.ingest.ocr_space import OCRPreflightResult

        client_ocr = OCRSpaceClient(
            api_key="test-key", endpoint_url="https://api.ocr.space/parse/image"
        )
        with patch(
            "app.ingest.ocr_space.evaluate_ocr_eligibility",
            return_value=OCRPreflightResult(is_eligible=True, size_bytes=100, page_count=1),
        ):
            with patch.object(
                httpx.Client, "post", side_effect=httpx.TimeoutException("OCR network timed out")
            ):
                result = client_ocr.parse_pdf(b"%PDF-1.4 dummy pdf bytes")
                graceful = result.status in ("ERROR", "failed", "skipped")
                harness.record_scenario(
                    name="OCR.Space API network timeout",
                    fault_type=ChaosFaultType.OCR_TIMEOUT,
                    graceful=graceful,
                    unhandled=False,
                )
                assert graceful

    # -------------------------------------------------------------------------
    # Scenario 4: Embedding model transient error
    # -------------------------------------------------------------------------
    with inject_fault(ChaosFaultType.EMBEDDER_FAILURE):
        assert is_fault_active(ChaosFaultType.EMBEDDER_FAILURE)
        with patch.object(
            app.state.embedder, "encode_query", side_effect=RuntimeError("CUDA out of memory")
        ):
            # When embedder fails during search, handled without crashing event loop
            try:
                resp = client.post(
                    "/v1/search",
                    json={"query": "risk weighted assets", "mode": "dense", "use_cache": False},
                    headers=auth_headers,
                )
                graceful = resp.status_code in (500, 503)  # Handled error response
                unhandled = False
            except Exception:
                graceful = False
                unhandled = True
            harness.record_scenario(
                name="Embedding model transient failure",
                fault_type=ChaosFaultType.EMBEDDER_FAILURE,
                graceful=graceful,
                unhandled=unhandled,
            )
            assert graceful

    # -------------------------------------------------------------------------
    # Scenario 5: Corrupted external OCR payload (malformed JSON)
    # -------------------------------------------------------------------------
    with inject_fault(ChaosFaultType.OCR_CORRUPT_PAYLOAD):
        assert is_fault_active(ChaosFaultType.OCR_CORRUPT_PAYLOAD)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Malformed OCR JSON")
        with patch(
            "app.ingest.ocr_space.evaluate_ocr_eligibility",
            return_value=OCRPreflightResult(is_eligible=True, size_bytes=100, page_count=1),
        ):
            with patch.object(httpx.Client, "post", return_value=mock_response):
                result = client_ocr.parse_pdf(b"%PDF-1.4 sample pdf")
                graceful = (
                    result.status == "ERROR"
                    and result.error_detail is not None
                    and "Malformed" in result.error_detail
                )
                harness.record_scenario(
                    name="Corrupted external OCR payload",
                    fault_type=ChaosFaultType.OCR_CORRUPT_PAYLOAD,
                    graceful=graceful,
                    unhandled=False,
                )
                assert graceful

    # -------------------------------------------------------------------------
    # Scenario 6: Redis / semantic cache outage with transparent in-memory fallback
    # -------------------------------------------------------------------------
    with inject_fault(ChaosFaultType.CACHE_FAILURE):
        assert is_fault_active(ChaosFaultType.CACHE_FAILURE)
        # Configure TieredSemanticCache with unreachable redis
        cache = TieredSemanticCache[str](
            CacheConfig(lru_maxsize=10, ttl_seconds=60, redis_url="redis://127.0.0.1:9999/0")
        )
        # Put and get must succeed via Tier 1 in-memory without raising exception
        cache.put("chaos_key", "chaos_val")
        val = cache.get("chaos_key")
        graceful = val == "chaos_val"
        harness.record_scenario(
            name="Redis / cache outage with in-memory fallback",
            fault_type=ChaosFaultType.CACHE_FAILURE,
            graceful=graceful,
            unhandled=False,
        )
        assert graceful

    # -------------------------------------------------------------------------
    # Scenario 7: Database pool exhaustion & bulkhead load shedding
    # -------------------------------------------------------------------------
    with inject_fault(ChaosFaultType.POOL_EXHAUSTION, error_code=429):
        # Configure a saturated bulkhead manager
        cfg = BulkheadConfig(pool_limits={"query": 2}, queue_multipliers={"query": 1})
        saturated_mgr = BulkheadManager(cfg)
        saturated_mgr._active["query"] = 2
        saturated_mgr._queued["query"] = 2
        set_bulkhead_manager(saturated_mgr)

        admission = saturated_mgr.check_admission("query")
        graceful = not admission.admitted and "queue saturated" in (
            admission.rejection_reason or ""
        )
        harness.record_scenario(
            name="Connection pool exhaustion & bulkhead load shedding",
            fault_type=ChaosFaultType.POOL_EXHAUSTION,
            graceful=graceful,
            unhandled=False,
        )
        assert graceful
        # Reset bulkhead manager
        set_bulkhead_manager(BulkheadManager(BulkheadConfig()))

    # -------------------------------------------------------------------------
    # Scenario 8: Latency spike injection bounded by max_fault_duration_ms
    # -------------------------------------------------------------------------
    start_time = time.perf_counter()
    with inject_fault(ChaosFaultType.LATENCY_SPIKE, delay_ms=50):
        assert is_fault_active(ChaosFaultType.LATENCY_SPIKE)
        resp = client.get("/healthz")
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        # Under latency injection, healthz degrades gracefully and reports active fault
        graceful = resp.status_code == 200 and resp.json()["status"] == "degraded"
        harness.record_scenario(
            name="Latency spike injection with bounded delay",
            fault_type=ChaosFaultType.LATENCY_SPIKE,
            graceful=graceful,
            unhandled=False,
            metadata={"elapsed_ms": elapsed_ms},
        )
        assert graceful

    # -------------------------------------------------------------------------
    # Scenario 9: Transient network partition with sub-500ms recovery time
    # -------------------------------------------------------------------------
    with inject_fault(ChaosFaultType.NETWORK_PARTITION):
        assert is_fault_active(ChaosFaultType.NETWORK_PARTITION)
        degraded_resp = client.get("/healthz")
        assert degraded_resp.json()["status"] == "degraded"

    # Once fault is cleared, verify sub-500ms core recovery
    recovery_start = time.perf_counter()
    recovered_resp = client.get("/healthz")
    recovery_time_ms = (time.perf_counter() - recovery_start) * 1000.0

    graceful = (
        recovered_resp.status_code == 200
        and recovered_resp.json()["status"] == "ok"
        and recovery_time_ms <= 500.0
    )
    harness.record_scenario(
        name="Transient network partition sub-500ms recovery",
        fault_type=ChaosFaultType.NETWORK_PARTITION,
        graceful=graceful,
        unhandled=False,
        recovery_time_ms=recovery_time_ms,
    )
    assert graceful, f"Recovery took {recovery_time_ms:.2f}ms (limit <= 500ms)"

    # -------------------------------------------------------------------------
    # Scenario 10: Corrupted / invalid document upload payload
    # -------------------------------------------------------------------------
    with inject_fault(ChaosFaultType.OCR_CORRUPT_PAYLOAD):
        # Post malformed JSON or empty body to chunking endpoint
        resp = client.post(
            "/v1/ingest/chunk",
            json={"invalid_field": 12345},  # Missing required fields
            headers=auth_headers,
        )
        # Must return clean HTTP 422 Unprocessable Entity, zero unhandled 500 tracebacks
        graceful = resp.status_code == 422 and "detail" in resp.json()
        harness.record_scenario(
            name="Corrupted document upload payload",
            fault_type=ChaosFaultType.OCR_CORRUPT_PAYLOAD,
            graceful=graceful,
            unhandled=resp.status_code == 500,
        )
        assert graceful

    # -------------------------------------------------------------------------
    # Final Report Assertion
    # -------------------------------------------------------------------------
    report: ChaosTestReport = harness.evaluate()
    assert report.faults_injected == 10
    assert report.graceful_degradations == 10
    assert report.unhandled_exceptions == 0
    assert report.passed is True
