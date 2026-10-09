"""Tests for the serving API.

The API is the only part of DocScout exposed to the internet, so these tests weight
security behaviour as heavily as functionality: what happens without a key, with a wrong
key, with a hostile payload, and past the rate limit.

Keys are injected through the environment rather than read from `.env`. `config.load_dotenv`
uses `setdefault`, so a real environment variable always wins — which makes the suite
hermetic and means it never depends on, or reveals, the operator's actual key.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api import security
from app.api.security import AuthConfigurationError, RateLimiter, load_keys
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth


# Composed from repeated characters on purpose. A realistic-looking random string here is
# indistinguishable from a leaked credential to a secret scanner -- gitleaks flagged the
# first version of this file at entropy 4.45 -- and the right response is to make the
# fixture obviously fake rather than to add an allowlist entry that blunts the scanner for
# every future file.
# --- configuration fails closed ---------------------------------------------------------
def test_missing_key_configuration_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auth that disables itself when a variable is unset is a hole, not a default."""
    monkeypatch.setenv("DOCSCOUT_API_KEY", "")
    with pytest.raises(AuthConfigurationError, match="will not start"):
        load_keys()


def test_whitespace_only_key_configuration_is_still_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCSCOUT_API_KEY", "  ,  , ")
    with pytest.raises(AuthConfigurationError):
        load_keys()


# --- authentication ---------------------------------------------------------------------
def test_search_requires_a_key(client: TestClient) -> None:
    response = client.post("/v1/search", json={"query": "anything at all"})
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "X-API-Key"


def test_wrong_key_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/v1/search", json={"query": "anything at all"}, headers=auth("not-the-key")
    )
    assert response.status_code == 401


def test_rejection_does_not_reveal_whether_a_key_was_well_formed(client: TestClient) -> None:
    """Same status for absent and wrong, so a prober learns nothing from the difference."""
    absent = client.post("/v1/search", json={"query": "anything at all"})
    wrong = client.post("/v1/search", json={"query": "anything at all"}, headers=auth("x" * 48))
    assert absent.status_code == wrong.status_code == 401


def test_a_rotation_key_is_accepted(client: TestClient) -> None:
    """Comma-separated keys exist so one can be retired without downtime."""
    response = client.post(
        "/v1/search", json={"query": "capital adequacy requirements"}, headers=auth(ROTATION_KEY)
    )
    assert response.status_code == 200


def test_key_is_never_echoed_in_a_response(client: TestClient) -> None:
    response = client.post(
        "/v1/search", json={"query": "capital adequacy requirements"}, headers=auth()
    )
    assert PRIMARY_KEY not in response.text


# --- request validation -----------------------------------------------------------------
@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"query": "a"}, "query"),
        ({"query": "x" * 600}, "query"),
        ({"query": "valid question", "k": 0}, "k"),
        ({"query": "valid question", "k": 99}, "k"),
        ({"query": "valid question", "mode": "magic"}, "mode"),
        ({"query": "valid question", "unexpected": True}, "unexpected"),
    ],
)
def test_invalid_requests_are_rejected_with_the_offending_field(
    client: TestClient, payload: dict[str, Any], field: str
) -> None:
    response = client.post("/v1/search", json=payload, headers=auth())
    assert response.status_code == 422
    body = response.json()
    assert body["detail"] == "invalid request"
    assert any(p["field"] == field for p in body["problems"]), body


def test_validation_errors_do_not_echo_the_submitted_value(client: TestClient) -> None:
    """Pydantic's default error body includes `input`; reflecting caller data is a leak."""
    sentinel = "zzz-sentinel-value-zzz"
    response = client.post("/v1/search", json={"query": sentinel, "k": 999}, headers=auth())
    assert response.status_code == 422
    assert sentinel not in response.text


# --- retrieval --------------------------------------------------------------------------
def test_search_returns_checkable_citations(
    client: TestClient, app_conn: psycopg.Connection[Any]
) -> None:
    """Every returned chunk id must resolve to a real row, with the span it claims."""
    response = client.post(
        "/v1/search",
        json={"query": "What are the KYC requirements for foreign portfolio investors?", "k": 5},
        headers=auth(),
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["passages"]) == 5
    assert [p["rank"] for p in body["passages"]] == [1, 2, 3, 4, 5]

    for passage in body["passages"]:
        row = app_conn.execute(
            "SELECT char_start, char_end, text FROM chunks WHERE chunk_id = %s",
            (passage["chunk_id"],),
        ).fetchone()
        assert row is not None, f"cited chunk {passage['chunk_id']} does not exist"
        assert passage["char_start"] == row[0]
        assert passage["char_end"] == row[1]
        assert passage["text"] == row[2]


def test_response_carries_the_provenance_needed_to_date_it(client: TestClient) -> None:
    body = client.post("/v1/search", json={"query": "settlement cycle"}, headers=auth()).json()
    provenance = body["provenance"]
    assert provenance["embedding_model"] == "BAAI/bge-small-en-v1.5"
    assert provenance["embedding_dim"] == 384
    assert provenance["corpus_chunks"] > 0
    assert len(provenance["corpus_manifest_digest"]) == 64
    # The serving defaults of ADR-0006/0007 must be what actually ran.
    assert provenance["retrieval"]["rrf_k"] == 60
    assert provenance["retrieval"]["anchor_arm_top1"] is True


def test_k_is_honoured(client: TestClient) -> None:
    body = client.post(
        "/v1/search", json={"query": "currency chest operations", "k": 2}, headers=auth()
    ).json()
    assert len(body["passages"]) == 2


@pytest.mark.parametrize("mode", ["hybrid", "dense", "bm25"])
def test_every_documented_mode_is_reachable(client: TestClient, mode: str) -> None:
    """The ADR-0006 ablation must be reproducible against the running service."""
    body = client.post(
        "/v1/search", json={"query": "grievance redressal timeline", "mode": mode}, headers=auth()
    ).json()
    assert body["mode"] == mode
    assert body["passages"]


def test_results_are_deterministic(client: TestClient) -> None:
    payload = {"query": "investment in InvIT and REIT units", "k": 5, "use_cache": False}
    first = client.post("/v1/search", json=payload, headers=auth()).json()
    second = client.post("/v1/search", json=payload, headers=auth()).json()
    assert [p["chunk_id"] for p in first["passages"]] == [p["chunk_id"] for p in second["passages"]]


# --- caching ----------------------------------------------------------------------------
def test_cache_hit_is_reported_and_returns_identical_passages(client: TestClient) -> None:
    payload = {"query": "a distinctive query for the cache test", "k": 3}
    cold = client.post("/v1/search", json=payload, headers=auth()).json()
    warm = client.post("/v1/search", json=payload, headers=auth()).json()
    assert cold["timings"]["cache_hit"] is False
    assert warm["timings"]["cache_hit"] is True
    assert cold["passages"] == warm["passages"]


def test_cache_can_be_bypassed_for_measurement(client: TestClient) -> None:
    """Artifact 3 needs the cache's effect measured, which needs a way to turn it off."""
    payload = {"query": "another distinctive query", "k": 3}
    client.post("/v1/search", json=payload, headers=auth())
    bypassed = client.post("/v1/search", json={**payload, "use_cache": False}, headers=auth())
    assert bypassed.json()["timings"]["cache_hit"] is False


def test_cache_key_separates_k_and_mode(client: TestClient) -> None:
    """A cache keyed only on the query text would serve 3 passages to a request for 10."""
    base = {"query": "shared text across cache keys"}
    three = client.post("/v1/search", json={**base, "k": 3}, headers=auth()).json()
    ten = client.post("/v1/search", json={**base, "k": 10}, headers=auth()).json()
    assert len(three["passages"]) == 3
    assert len(ten["passages"]) == 10


# --- rate limiting ----------------------------------------------------------------------
def test_requests_past_the_limit_are_refused_with_retry_after() -> None:
    limiter = RateLimiter(limit=3, window=60.0)
    assert [limiter.check("caller")[0] for _ in range(3)] == [True, True, True]
    allowed, remaining, retry_after = limiter.check("caller")
    assert allowed is False
    assert remaining == 0
    assert 0 < retry_after <= 60.0


def test_the_window_slides() -> None:
    """Old hits must age out, or a caller is locked out permanently after one burst."""
    limiter = RateLimiter(limit=2, window=10.0)
    assert limiter.check("caller", now=0.0)[0] is True
    assert limiter.check("caller", now=1.0)[0] is True
    assert limiter.check("caller", now=2.0)[0] is False
    assert limiter.check("caller", now=11.5)[0] is True


def test_callers_are_limited_independently() -> None:
    limiter = RateLimiter(limit=1, window=60.0)
    assert limiter.check("alice")[0] is True
    assert limiter.check("alice")[0] is False
    assert limiter.check("bob")[0] is True


def test_the_endpoint_enforces_the_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(security, "rate_limiter", RateLimiter(limit=2, window=60.0))
    payload = {"query": "rate limited query text"}
    codes = [client.post("/v1/search", json=payload, headers=auth()).status_code for _ in range(4)]
    assert codes[:2] == [200, 200]
    assert codes[2:] == [429, 429]


# --- ops surface ------------------------------------------------------------------------
def test_healthz_is_unauthenticated_and_reports_readiness(client: TestClient) -> None:
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["database"] is True
    assert body["corpus_chunks"] > 0
    assert body["model_loaded"] is True
    # Stated so nobody reads these numbers as cluster-wide.
    assert body["single_process"] is True
    # P0-2: operational freshness
    assert "last_checked_at" in body
    assert body["last_checked_at"] is not None
    assert "stale_hours" in body
    assert body["stale_hours"] is not None
    assert body["staleness_budget_hours"] > 0
    assert body["is_stale"] is False


def test_demo_page_loads_no_external_assets(client: TestClient) -> None:
    """The page is served into a sandboxed frame with no network.

    A CDN reference would degrade to an unstyled page during review, and a third-party
    script on a page where someone pastes an API key is a bad habit regardless.
    """
    page = client.get("/").text
    assert "<title>DocScout" in page
    for marker in ("http://", "https://cdn", "//unpkg", "//cdnjs", "integrity="):
        assert marker not in page, f"demo page references external asset: {marker}"


def test_openapi_schema_documents_the_search_contract(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert "/v1/search" in schema["paths"]
    responses = schema["paths"]["/v1/search"]["post"]["responses"]
    for code in ("401", "422", "429"):
        assert code in responses


def test_unhandled_errors_do_not_leak_internals(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A public URL must not return a stack trace or a connection string.

    Reuses the module client and flips `raise_server_exceptions` on its transport for the
    duration, rather than constructing a second TestClient. A second client would enter and
    then exit the same application object's lifespan, closing the connection pool that the
    module-scoped client still holds -- every test after this one then failed with
    PoolClosed. Production behaviour is the `raise_server_exceptions=False` path.
    """
    from app.api import app as api_module

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("postgresql://secret:password@host/db")

    monkeypatch.setattr(api_module, "Retriever", boom)
    transport = client._transport  # noqa: SLF001 - no public setter for this flag
    monkeypatch.setattr(transport, "raise_server_exceptions", False)

    response = client.post(
        "/v1/search",
        json={"query": "trigger the failure path", "use_cache": False},
        headers=auth(),
    )
    assert response.status_code == 500
    assert "secret" not in response.text
    assert "Traceback" not in response.text
    assert "internal error (reference " in response.json()["detail"]


# --- request correlation ----------------------------------------------------------------
def test_every_response_carries_a_request_id(client: TestClient) -> None:
    """A caller reporting a bad answer needs something that joins to the logs."""
    response = client.post(
        "/v1/search", json={"query": "capital adequacy requirements"}, headers=auth()
    )
    assert response.status_code == 200
    assert len(response.headers["X-Request-ID"]) == 16


def test_an_inbound_request_id_is_echoed(client: TestClient) -> None:
    """Lets a proxy or client correlate across the hop."""
    response = client.post(
        "/v1/search",
        json={"query": "capital adequacy requirements"},
        headers={**auth(), "X-Request-ID": "caller-supplied-1"},
    )
    assert response.headers["X-Request-ID"] == "caller-supplied-1"


def test_a_hostile_request_id_is_replaced_not_echoed(client: TestClient) -> None:
    """The id lands in every log line for the request, so it must not carry a newline."""
    response = client.post(
        "/v1/search",
        json={"query": "capital adequacy requirements"},
        headers={**auth(), "X-Request-ID": "x" * 300},
    )
    assert response.headers["X-Request-ID"] != "x" * 300
    assert len(response.headers["X-Request-ID"]) == 16


def test_error_responses_also_carry_the_request_id(client: TestClient) -> None:
    response = client.post("/v1/search", json={"query": "no key supplied"})
    assert response.status_code == 401
    assert "X-Request-ID" in response.headers


# --- confidence signal ------------------------------------------------------------------
def test_search_reports_evidence_coverage(client: TestClient) -> None:
    body = client.post(
        "/v1/search",
        json={"query": "What are the KYC requirements for foreign portfolio investors?"},
        headers=auth(),
    ).json()
    confidence = body["confidence"]
    assert 0.0 <= confidence["evidence_coverage"] <= 1.0
    assert confidence["low_evidence"] is False
    assert confidence["passages_considered"] > 0


def test_a_question_the_corpus_cannot_answer_is_flagged_but_still_answered(
    client: TestClient,
) -> None:
    """The flag is advisory. Withholding passages on a signal this weak (AUC 0.730) would
    trade a known failure mode for a worse one, so the caller is warned and still served."""
    body = client.post(
        "/v1/search",
        json={"query": "What is the minimum acceptable ITRI score an MII must maintain?"},
        headers=auth(),
    ).json()
    assert body["confidence"]["low_evidence"] is True
    assert body["confidence"]["missing_terms"]
    assert body["passages"], "a low-evidence flag must not withhold the evidence"


def test_confidence_survives_the_cache(client: TestClient) -> None:
    payload = {"query": "a distinctive query used only by the confidence cache test"}
    cold = client.post("/v1/search", json=payload, headers=auth()).json()
    warm = client.post("/v1/search", json=payload, headers=auth()).json()
    assert warm["timings"]["cache_hit"] is True
    assert warm["confidence"] == cold["confidence"]
