"""Request and response schemas for the serving API.

These are a contract, not a convenience. Two decisions are encoded here and both are
deliberate:

* Every returned passage carries its `chunk_id`, its source document and its character
  span. A citation a caller cannot resolve back to bytes in a specific document is not a
  citation, and ADR-0005 made those ids stable across re-ingests precisely so an answer
  stays checkable later.
* The response states what produced it. The embedding model, the chunker geometry and the
  corpus digest travel with the result, so a saved response can be matched to the
  configuration that generated it instead of being undatable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.generate.models import GeneratedAnswer
from app.retrieval.types import MetadataFilter

# A ceiling on query length. The embedding model truncates at 512 tokens, so anything
# beyond roughly this is silently discarded by the encoder -- better to reject it than to
# answer a question the system only partly read.
MAX_QUERY_CHARS = 512


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # StringConstraints, not Field(strip_whitespace=...): Field silently ignores that
    # keyword in Pydantic v2 and only emits a deprecation warning, so the stripping never
    # happened. It matters beyond tidiness -- the cache is keyed on the query text, so
    # "  rate  " and "rate" would occupy two entries and report a miss for a repeat query.
    query: Annotated[
        str,
        StringConstraints(min_length=3, max_length=MAX_QUERY_CHARS, strip_whitespace=True),
    ]
    k: Annotated[int, Field(default=10, ge=1, le=20)] = 10
    # Exposed so the A/B in ADR-0006 is reproducible against the running service and not
    # only inside the eval harness. `hybrid` is the serving default; the single-arm modes
    # are the documented ablation.
    mode: Literal["hybrid", "dense", "bm25"] = "hybrid"
    # Lets a caller measure the cache rather than take its effect on trust (artifact 3).
    use_cache: bool = True
    # Whether to construct a citation-grounded answer behind the retrieved passages.
    generate_answer: bool = False
    # Declarative metadata filter for in-query pruning (P1-2).
    filter: MetadataFilter | None = None
    # Domain query understanding and expansion (P1-3).
    expand_query: bool = False
    expansion_mode: Literal["none", "synonym", "hyde", "combined"] = "none"


class Passage(BaseModel):
    """One retrieved chunk, with everything needed to verify it."""

    rank: int
    chunk_id: str
    document_id: str
    source: str
    canonical_url: str | None
    score: float
    # Which arm ranked it where. Empty for single-arm modes. This is what makes a result
    # explainable -- ADR-0007 exists because a chunk BM25 ranked first was being dropped,
    # and that was only diagnosable because arm ranks were recorded.
    arm_ranks: dict[str, int]
    char_start: int
    char_end: int
    text: str


class Provenance(BaseModel):
    """What produced this response. Mirrors the eval harness's E-14 fields."""

    embedding_model: str
    embedding_dim: int
    chunk_size: int
    chunk_overlap: int
    corpus_manifest_digest: str
    corpus_chunks: int
    retrieval: dict[str, object]
    corpus_generation: int = 1


class Confidence(BaseModel):
    """Whether the retrieved evidence actually covers the question.

    Reported, never acted on. The signal is real but weak -- it catches roughly a quarter
    of unanswerable questions and mislabels about 3% of answerable ones -- so withholding
    results on it would trade a known failure for a worse one. The caller decides.
    """

    evidence_coverage: float
    missing_terms: list[str]
    low_evidence: bool
    passages_considered: int


class Timings(BaseModel):
    """Server-side milliseconds. Honest about what is and is not included."""

    total_ms: float
    retrieval_ms: float
    generation_ms: float = 0.0
    cache_hit: bool


class SearchResponse(BaseModel):
    query: str
    mode: str
    k: int
    passages: list[Passage]
    confidence: Confidence
    provenance: Provenance
    timings: Timings
    answer: GeneratedAnswer | None = None
    filter: MetadataFilter | None = None


class LivenessResponse(BaseModel):
    """Process liveness probe for orchestrators (GET /healthz).

    Reflects whether the application process is alive, the event loop is responsive,
    and memory-resident components are intact. Never performs DB I/O.
    """

    status: Literal["ok"]
    uptime_seconds: float
    model_loaded: bool
    single_process: bool
    corpus_generation: int


class ReadinessResponse(BaseModel):
    """Traffic readiness probe for load balancers (GET /readyz).

    Reflects whether the service can currently execute retrieval queries:
    database connection pool is healthy, corpus chunks are available (> 0),
    embedding model and BM25 index are ready, and staleness budget status.
    """

    status: Literal["ok", "degraded", "unready"]
    database: bool
    corpus_chunks: int
    embedding_model: str
    model_loaded: bool
    bm25_ready: bool
    cache: dict[str, int]
    rate_limit_per_minute: int
    single_process: bool
    corpus_generation: int
    last_checked_at: datetime | None = None
    stale_hours: float | None = None
    staleness_budget_hours: float = 168.0
    is_stale: bool = False


# Retained for backward-compatibility with callers/tests expecting HealthResponse
HealthResponse = ReadinessResponse


class CacheInvalidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = "manual_admin"


class CacheInvalidateResponse(BaseModel):
    status: Literal["ok"]
    previous_generation: int
    new_generation: int
    entries_cleared: int
    corpus_chunks: int


class ErrorResponse(BaseModel):
    detail: str
