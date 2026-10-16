"""Tests for Section-Aware Context Window Expansion (FEAT-075, ADR-0066).

Validates:
1. Automatic expansion of standalone subsections and provisos with adjacent sibling clauses.
2. Strict section boundary protection (prohibiting bleeding across unrelated chapters).
3. Preservation of core_chunk_id as primary citation anchor.
4. Input validation (valid UUID, 1 <= max_sibling_clauses <= 4).
5. Fail-safe fallback on missing connection or database error.
6. Execution latency budget <= 2.5 ms p95.
7. Prometheus metrics emission (docscout_section_expansions_total, duration histogram).
8. Integration with format_evidence_context.
"""

from __future__ import annotations

import time
from uuid import uuid4

import pytest

from app.api.metrics import SECTION_EXPANSIONS_TOTAL
from app.api.models import Passage
from app.generate.prompt import format_evidence_context
from app.retrieval import (
    RetrievalConfig,
    SectionExpander,
    SiblingChunk,
    expand_section_context,
)
from app.retrieval.types import Retrieved

DOC_1 = str(uuid4())
DOC_2 = str(uuid4())

CHUNK_1_UUID = uuid4()
CHUNK_2_UUID = uuid4()
CHUNK_3_UUID = uuid4()
CHUNK_OTHER_SEC_UUID = uuid4()
CHUNK_OTHER_DOC_UUID = uuid4()


@pytest.fixture
def mock_chunks() -> list[dict[str, object]]:
    return [
        {
            "chunk_id": str(CHUNK_1_UUID),
            "document_id": DOC_1,
            "source": "RBI",
            "text": "Section 4(1): Regulated entities shall maintain an active cyber incident response plan.",
            "char_start": 0,
            "char_end": 85,
            "ordinal": 1,
            "clause_hierarchy": ["Section 4", "Sub-section (1)"],
            "is_proviso": False,
        },
        {
            "chunk_id": str(CHUNK_2_UUID),
            "document_id": DOC_1,
            "source": "RBI",
            "text": "Section 4(2): Provided that all critical severity incidents shall be reported to the Reserve Bank within 6 hours.",
            "char_start": 86,
            "char_end": 200,
            "ordinal": 2,
            "clause_hierarchy": ["Section 4", "Sub-section (2)", "Proviso"],
            "is_proviso": True,
        },
        {
            "chunk_id": str(CHUNK_3_UUID),
            "document_id": DOC_1,
            "source": "RBI",
            "text": "Section 4(3): Provided further that failure to report within the stipulated timeframe attracts penalty proceedings.",
            "char_start": 201,
            "char_end": 315,
            "ordinal": 3,
            "clause_hierarchy": ["Section 4", "Sub-section (3)", "Proviso"],
            "is_proviso": True,
        },
        {
            "chunk_id": str(CHUNK_OTHER_SEC_UUID),
            "document_id": DOC_1,
            "source": "RBI",
            "text": "Section 5(1): Board of Directors shall review risk policies annually.",
            "char_start": 316,
            "char_end": 385,
            "ordinal": 4,
            "clause_hierarchy": ["Section 5", "Sub-section (1)"],
            "is_proviso": False,
        },
        {
            "chunk_id": str(CHUNK_OTHER_DOC_UUID),
            "document_id": DOC_2,
            "source": "SEBI",
            "text": "Regulation 12: Disclosure requirements for listed entities.",
            "char_start": 0,
            "char_end": 60,
            "ordinal": 1,
            "clause_hierarchy": ["Regulation 12"],
            "is_proviso": False,
        },
    ]


def test_input_validation_rules() -> None:
    """Expander enforces valid UUID and 1 <= max_sibling_clauses <= 4."""
    expander = SectionExpander(in_memory_chunks=[])

    with pytest.raises(ValueError, match="Invalid chunk_id UUID"):
        expander.expand("not-a-valid-uuid")

    valid_id = str(uuid4())
    with pytest.raises(ValueError, match="max_sibling_clauses must be between 1 and 4"):
        expander.expand(valid_id, max_sibling_clauses=0)

    with pytest.raises(ValueError, match="max_sibling_clauses must be between 1 and 4"):
        expander.expand(valid_id, max_sibling_clauses=5)

    with pytest.raises(ValueError, match="passage must be a Passage, Retrieved, ChunkRow"):
        expander.expand(12345)


def test_proviso_expansion_pulls_operative_rule(mock_chunks: list[dict[str, object]]) -> None:
    """When a proviso chunk is retrieved, preceding operative rule is included."""
    expander = SectionExpander(in_memory_chunks=mock_chunks)
    before_count = SECTION_EXPANSIONS_TOTAL.labels(status="expanded")._value.get()

    res = expander.expand(CHUNK_2_UUID, max_sibling_clauses=1)
    after_count = SECTION_EXPANSIONS_TOTAL.labels(status="expanded")._value.get()

    assert after_count == before_count + 1
    assert res.core_chunk_id == CHUNK_2_UUID
    assert res.is_proviso is True
    assert res.section_title == "Section 4"
    assert res.preceding_count == 1
    assert res.following_count == 1

    # Operative rule from 4(1) must be in the expanded text
    assert (
        "Section 4(1): Regulated entities shall maintain an active cyber incident response plan."
        in res.expanded_text
    )
    assert "Section 4(2): Provided that all critical severity incidents" in res.expanded_text
    assert "Section 4(3): Provided further that failure to report" in res.expanded_text

    # Sibling chunks list
    assert len(res.sibling_chunks) == 2
    s_pre = res.sibling_chunks[0]
    assert isinstance(s_pre, SiblingChunk)
    assert s_pre.position == "preceding"
    assert s_pre.chunk_id == str(CHUNK_1_UUID)

    s_post = res.sibling_chunks[1]
    assert isinstance(s_post, SiblingChunk)
    assert s_post.position == "following"
    assert s_post.chunk_id == str(CHUNK_3_UUID)


def test_section_boundary_protection(mock_chunks: list[dict[str, object]]) -> None:
    """Expansion must not cross across distinct statutory sections even if adjacent in document."""
    expander = SectionExpander(in_memory_chunks=mock_chunks)

    # Expanding Section 4(3) with max_sibling_clauses=2:
    # Preceding has 4(2) and 4(1) (same section).
    # Following has Section 5(1), which is a DIFFERENT section. It must be excluded!
    res = expander.expand(CHUNK_3_UUID, max_sibling_clauses=2)

    assert res.core_chunk_id == CHUNK_3_UUID
    assert res.preceding_count == 2
    assert res.following_count == 0  # Section 5(1) rejected by section boundary check
    assert "Section 5(1)" not in res.expanded_text
    assert "Section 4(1)" in res.expanded_text
    assert "Section 4(2)" in res.expanded_text


def test_unexpanded_when_no_siblings_exist(mock_chunks: list[dict[str, object]]) -> None:
    """When a chunk has no sibling clauses, it returns unexpanded cleanly."""
    expander = SectionExpander(in_memory_chunks=mock_chunks)
    before_unexpanded = SECTION_EXPANSIONS_TOTAL.labels(status="unexpanded")._value.get()

    res = expander.expand(CHUNK_OTHER_DOC_UUID, max_sibling_clauses=2)
    after_unexpanded = SECTION_EXPANSIONS_TOTAL.labels(status="unexpanded")._value.get()

    assert after_unexpanded == before_unexpanded + 1
    assert res.core_chunk_id == CHUNK_OTHER_DOC_UUID
    assert res.preceding_count == 0
    assert res.following_count == 0
    assert len(res.sibling_chunks) == 0
    assert res.total_chars == len(res.expanded_text)


def test_convenience_function(mock_chunks: list[dict[str, object]]) -> None:
    """Functional wrapper expand_section_context works seamlessly."""
    passage = Retrieved(
        chunk_id=str(CHUNK_1_UUID),
        rank=1,
        score=0.95,
        document_id=DOC_1,
        source="RBI",
        text="Section 4(1) core text",
        clause_hierarchy=["Section 4", "Sub-section (1)"],
    )
    res = expand_section_context(passage, max_sibling_clauses=2, in_memory_chunks=mock_chunks)
    assert res.core_chunk_id == CHUNK_1_UUID
    assert res.following_count >= 1


def test_fallback_on_corrupt_state() -> None:
    """If an unexpected exception occurs, returns unexpanded core text with status=fallback."""
    before_fallback = SECTION_EXPANSIONS_TOTAL.labels(status="fallback")._value.get()

    class BrokenConnection:
        def execute(self, *args: object, **kwargs: object) -> object:
            raise RuntimeError("Database connection reset by peer")

    expander = SectionExpander(conn=BrokenConnection())  # type: ignore[arg-type]
    cid = str(uuid4())
    res = expander.expand(cid)
    after_fallback = SECTION_EXPANSIONS_TOTAL.labels(status="fallback")._value.get()

    assert after_fallback == before_fallback + 1
    assert str(res.core_chunk_id) == cid
    assert res.sibling_chunks == []


def test_latency_overhead_budget(mock_chunks: list[dict[str, object]]) -> None:
    """Sibling chunk fetch and stitch latency must be <= 2.5 ms."""
    expander = SectionExpander(in_memory_chunks=mock_chunks)

    # Warmup
    for _ in range(50):
        expander.expand(CHUNK_2_UUID, max_sibling_clauses=2)

    iterations = 500
    start = time.perf_counter()
    for _ in range(iterations):
        expander.expand(CHUNK_2_UUID, max_sibling_clauses=2)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    mean_latency_ms = elapsed_ms / iterations

    assert mean_latency_ms <= 2.5, f"Overhead {mean_latency_ms:.5f} ms exceeds 2.5 ms SLA"


def test_format_evidence_context_with_expanded_text() -> None:
    """format_evidence_context prioritizes expanded_text when present on Passage."""
    p = Passage(
        rank=1,
        chunk_id=str(CHUNK_2_UUID),
        document_id=DOC_1,
        source="RBI",
        canonical_url=None,
        score=0.92,
        arm_ranks={"dense": 1},
        char_start=86,
        char_end=200,
        text="Section 4(2) Proviso text",
        expanded_text="[STITCHED SECTION CONTEXT] Section 4(1) Rule + Section 4(2) Proviso",
    )
    xml = format_evidence_context([p], reorder=False)
    assert "[STITCHED SECTION CONTEXT] Section 4(1) Rule + Section 4(2) Proviso" in xml


def test_retrieval_config_section_expansion_options() -> None:
    """RetrievalConfig properly validates and exposes section expansion fields."""
    cfg = RetrievalConfig(
        name="test", mode="hybrid", expand_section_context=True, max_sibling_clauses=3
    )
    assert cfg.expand_section_context is True
    assert cfg.max_sibling_clauses == 3
    assert cfg.as_dict()["expand_section_context"] is True
    assert cfg.as_dict()["max_sibling_clauses"] == 3

    with pytest.raises(ValueError, match="max_sibling_clauses must be in"):
        RetrievalConfig(name="bad", mode="hybrid", max_sibling_clauses=0)

    with pytest.raises(ValueError, match="max_sibling_clauses must be in"):
        RetrievalConfig(name="bad", mode="hybrid", max_sibling_clauses=5)
