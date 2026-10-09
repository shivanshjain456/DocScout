"""Tests for citation-grounded answer generation integration in the API.

Verifies that answer generation sits behind the retrieval surface, passages remain intact,
and endpoints /v1/search, /v1/answer, and /v1/chat adhere to the contract.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import Request

from app.api.app import app, search
from app.api.models import Confidence, Passage, Provenance, SearchRequest, SearchResponse, Timings
from app.generate.models import CitationSpan, GeneratedAnswer


def test_search_request_schema_supports_generate_answer() -> None:
    req_default = SearchRequest(query="What is the settlement timeline?")
    assert req_default.generate_answer is False

    req_with_gen = SearchRequest(query="What is the settlement timeline?", generate_answer=True)
    assert req_with_gen.generate_answer is True


def test_search_response_serializes_answer_behind_passages() -> None:
    passage = Passage(
        rank=1,
        chunk_id="b2ed16f7-7426-5161-bc18-7bc1dabb8df7",
        document_id="doc-001",
        source="RBI",
        canonical_url="https://rbi.org.in/test.pdf",
        score=0.95,
        arm_ranks={"dense": 1, "bm25": 1},
        char_start=0,
        char_end=60,
        text="Settlement must be completed within T+1 working days.",
    )
    answer = GeneratedAnswer(
        text="Settlement must be completed within T+1 working days. [b2ed16f7-7426-5161-bc18-7bc1dabb8df7]",
        citations=["b2ed16f7-7426-5161-bc18-7bc1dabb8df7"],
        citation_spans=[
            CitationSpan(
                chunk_id="b2ed16f7-7426-5161-bc18-7bc1dabb8df7",
                source="RBI",
                quote="Settlement must be completed within T+1 working days.",
            )
        ],
        grounded=True,
        abstained=False,
        model_id="docscout-local-deterministic/1",
        latency_ms=12.5,
    )
    resp = SearchResponse(
        query="What is the settlement timeline?",
        mode="hybrid",
        k=1,
        passages=[passage],
        confidence=Confidence(
            evidence_coverage=1.0,
            missing_terms=[],
            low_evidence=False,
            passages_considered=1,
        ),
        provenance=Provenance(
            embedding_model="BAAI/bge-small-en-v1.5",
            embedding_dim=384,
            chunk_size=1000,
            chunk_overlap=150,
            corpus_manifest_digest="test-digest",
            corpus_chunks=230,
            retrieval={"mode": "hybrid"},
        ),
        timings=Timings(total_ms=45.0, retrieval_ms=32.5, generation_ms=12.5, cache_hit=False),
        answer=answer,
    )
    dumped = resp.model_dump()
    assert len(dumped["passages"]) == 1
    assert dumped["passages"][0]["chunk_id"] == "b2ed16f7-7426-5161-bc18-7bc1dabb8df7"
    assert dumped["answer"] is not None
    assert "T+1 working days" in dumped["answer"]["text"]
    assert dumped["answer"]["citations"] == ["b2ed16f7-7426-5161-bc18-7bc1dabb8df7"]
    assert dumped["timings"]["generation_ms"] == 12.5


def test_openapi_documents_answer_and_chat_endpoints() -> None:
    schema = app.openapi()
    assert "/v1/search" in schema["paths"]
    assert "/v1/answer" in schema["paths"]
    assert "/v1/chat" in schema["paths"]
    for path in ("/v1/search", "/v1/answer", "/v1/chat"):
        assert "post" in schema["paths"][path]
        responses = schema["paths"][path]["post"]["responses"]
        for code in ("401", "422", "429"):
            assert code in responses


def test_search_handler_executes_generation_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_request = MagicMock(spec=Request)
    mock_state = MagicMock()
    mock_request.app.state = mock_state

    # Result cache miss
    mock_state.result_cache.get.return_value = None

    # Mock DB hit
    mock_hit = MagicMock()
    mock_hit.rank = 1
    mock_hit.chunk_id = "chunk-test-1"
    mock_hit.document_id = "doc-1"
    mock_hit.source = "RBI"
    mock_hit.canonical_url = "https://rbi.org.in"
    mock_hit.score = 0.9
    mock_hit.arm_ranks = {"dense": 1}
    mock_hit.char_start = 0
    mock_hit.char_end = 50
    mock_hit.text = "Capital adequacy ratio must be maintained at nine percent minimum."
    mock_hit.title = "Master Direction on Capital Adequacy"
    mock_hit.published_date = "2024-09-01"

    mock_retriever = MagicMock()
    mock_retriever.retrieve.return_value = [mock_hit]
    mock_confidence = MagicMock()
    mock_confidence.as_dict.return_value = {
        "evidence_coverage": 1.0,
        "missing_terms": [],
        "low_evidence": False,
        "passages_considered": 1,
    }
    mock_retriever.assess_confidence.return_value = mock_confidence

    mock_conn = MagicMock()
    mock_pool = MagicMock()
    mock_pool.connection.return_value.__enter__.return_value = mock_conn
    mock_state.pool = mock_pool
    mock_state.embedder = MagicMock()
    mock_state.bm25 = MagicMock()
    mock_state.manifest_digest = "sha256-mock"
    mock_state.corpus_chunks = 170

    # Mock generator
    mock_generator = MagicMock()
    mock_answer = GeneratedAnswer(
        text="Capital adequacy ratio must be maintained at nine percent minimum. [chunk-test-1]",
        citations=["chunk-test-1"],
        citation_spans=[],
        grounded=True,
        abstained=False,
        model_id="mock-gen",
    )
    mock_generator.generate.return_value = mock_answer
    mock_state.generator = mock_generator

    import app.api.app as app_mod

    monkeypatch.setattr(app_mod, "Retriever", MagicMock(return_value=mock_retriever))
    req = SearchRequest(query="What is the capital adequacy ratio?", generate_answer=True)
    res = search(req, mock_request, fingerprint="test-fingerprint")

    assert len(res.passages) == 1
    assert res.passages[0].chunk_id == "chunk-test-1"
    assert res.answer is not None
    assert "nine percent minimum" in res.answer.text
    assert res.answer.citations == ["chunk-test-1"]
    mock_generator.generate.assert_called_once()
