"""Models and schemas for citation-grounded answer generation.

Defines the structure of generated answers sitting behind the retrieval tier,
strictly preserving passage provenance and chunk citations.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class CitationSpan(BaseModel):
    """Specific chunk and text snippet cited by a generated claim."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    source: str
    quote: str
    char_start: int | None = None
    char_end: int | None = None


class GeneratedAnswer(BaseModel):
    """An answer constructed from retrieved passages with verified citations.

    Sits behind the retrieval tier -- passages are never replaced or omitted.
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    citations: list[str] = Field(default_factory=list)
    citation_spans: list[CitationSpan] = Field(default_factory=list)
    grounded: bool = True
    abstained: bool = False
    abstention_reason: str | None = None
    model_id: str
    finish_reason: str = "stop"
    latency_ms: float = 0.0


class GenerationConfig(BaseModel):
    """Configuration governing answer generation and grounding behavior."""

    model_config = ConfigDict(extra="forbid")

    model_id: str = "docscout-local-deterministic/1"
    temperature: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    max_tokens: Annotated[int, Field(ge=16, le=2048)] = 512
    abstain_on_low_evidence: bool = True
    low_evidence_threshold: float = 0.65


class ResearchStep(BaseModel):
    """A discrete, auditable step in the research agent loop."""

    model_config = ConfigDict(extra="forbid")

    step_index: int
    phase: str
    thought: str
    tool_name: str | None = None
    tool_args: dict[str, str | int | float | bool | list[str]] | None = None
    observation: str = ""
    duration_ms: float = 0.0


class StructuredTable(BaseModel):
    """Tabular comparison artifact extracted during research synthesis."""

    model_config = ConfigDict(extra="forbid")

    headers: list[str]
    rows: list[list[str]]


class ResearchArtifact(BaseModel):
    """Full research report produced by the agentic research loop."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    workspace_id: str
    query: str
    title: str
    markdown: str
    table_data: StructuredTable | None = None
    steps: list[ResearchStep] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    citation_spans: list[CitationSpan] = Field(default_factory=list)
    timings: dict[str, float] = Field(default_factory=dict)
    grounded: bool = True
    abstained: bool = False
    created_at: str = ""
