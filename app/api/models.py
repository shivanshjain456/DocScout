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

from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.generate.models import GeneratedAnswer, ResearchArtifact
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
    # Ontological relationship filter constraining retrieval (FEAT-008)
    relationship_filter: (
        Literal["supersedes", "requires", "enables", "complements", "specializedBy"] | None
    ) = None
    # Graph degree centrality query boosting (FEAT-009)
    enable_centrality_boost: bool = True
    centrality_weight: Annotated[float, Field(ge=0.0, le=0.3)] = 0.15
    # Context-aware token disambiguation (FEAT-011)
    enable_disambiguation: bool = True
    # Intent-driven query classification & routing (FEAT-013)
    enable_intent_routing: bool = True
    # Audience & difficulty banding filter (FEAT-015)
    difficulty_band: Literal["foundational", "intermediate", "advanced", "expert"] | None = None
    # Automatic query tagging & metadata constraining (FEAT-016)
    auto_constrain_tags: bool = False
    # Typo-tolerant regulatory token normalization (FEAT-018)
    enable_normalization: bool = True
    # Persona-tailored query profiling (FEAT-020)
    persona: (
        Literal[
            "general",
            "fintech_developer",
            "statutory_auditor",
            "risk_officer",
            "compliance_officer",
        ]
        | None
    ) = None
    # Entity vintage & grandfathering applicability filter (FEAT-036)
    entity_vintage: Literal["existing", "new"] | None = None
    # Point-in-time active circular temporal filtering (FEAT-039)
    as_of_date: date | None = None

    @field_validator("as_of_date")
    @classmethod
    def validate_as_of_date(cls, v: date | None) -> date | None:
        if v is not None:
            if v > date.today():
                raise ValueError("as_of_date cannot be in the future")
            if v < date(1990, 1, 1):
                raise ValueError("as_of_date cannot be before 1990-01-01")
        return v


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
    title: str | None = None
    published_date: str | None = None
    matching_relationships: list[str] = Field(default_factory=list)
    centrality_boost: float = 0.0
    difficulty_level: str | None = None

    @model_validator(mode="after")
    def _adapt_difficulty_window(self) -> Passage:
        if self.difficulty_level and self.text:
            from app.retrieval.difficulty import adapt_snippet

            self.text = adapt_snippet(self.text, self.difficulty_level)
        return self


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


class IntentClassification(BaseModel):
    """Diagnostic intent routing metadata and prescriptive first move (FEAT-013)."""

    intent_id: str
    label: str
    primary_domain: str
    first_move: str
    confidence: float
    recommended_terms: list[str]


# --- Persona-Tailored Query Profiling (FEAT-020) ---


class PersonaProfileResponse(BaseModel):
    id: str
    name: str
    title: str
    description: str
    target_audience: str
    weight_dense: float = 1.0
    weight_lexical: float = 1.0
    rrf_k: int = 60
    default_expansion_mode: str = "none"
    default_difficulty_band: str | None = None
    centrality_weight: float = 0.15
    preferred_layers: list[str] = Field(default_factory=list)
    auto_constrain_tags: bool = False


class PersonaListResponse(BaseModel):
    personas: list[PersonaProfileResponse]
    total: int


# --- Statutory Compliance Formulas & Quantitative Verification (FEAT-021) ---


class FormulaDefinition(BaseModel):
    id: str
    name: str
    domain: str
    expression: str
    required_variables: list[str]
    variable_descriptions: dict[str, str] = Field(default_factory=dict)
    unit: str
    standard: str | list[str] | None = None
    note: str | None = None
    statutory_threshold: str | None = None


class FormulaListResponse(BaseModel):
    formulas: list[FormulaDefinition]
    total: int


class FormulaCalcRequest(BaseModel):
    formula_id: str
    inputs: dict[str, float]
    custom_expression: str | None = None
    precision_decimal_places: int = 4


class FormulaCalcResult(BaseModel):
    formula_id: str
    name: str
    expression: str
    computed_value: float
    unit: str
    standard: str | list[str] | None = None
    note: str | None = None
    statutory_threshold: str | None = None
    is_compliant: bool | None = None
    steps: list[str] = Field(default_factory=list)
    duration_ms: float = 0.0


# --- Statutory Boundary Validation (FEAT-023) ---


class RatioFinding(BaseModel):
    ratio_name: str
    reported_value: float
    statutory_threshold: str
    status: Literal["COMPLIANT", "WARNING", "BREACH"]
    circular_citation: str
    margin: float
    margin_percentage: float
    operator: Literal[">=", "<=", ">", "<"]
    threshold_value: float
    unit: str
    guidance: str
    regulator: str
    category: str


class RatioValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_type: str = Field(
        default="commercial_bank",
        description="Regulated entity class (e.g. commercial_bank, nbfc_si, small_finance_bank, payment_bank, ucb, general)",
    )
    ratios: dict[str, float] = Field(
        ...,
        description="Key-value mapping of ratio or metric names to reported numeric values",
    )
    tolerance_percentage: float = Field(
        default=0.05,
        ge=0.0,
        le=0.5,
        description="Tolerance buffer (default 0.05 = 5%) within which a ratio is flagged as AMBER WARNING",
    )


class RatioValidationResponse(BaseModel):
    overall_status: Literal["COMPLIANT", "WARNING", "BREACH"]
    entity_type: str
    tolerance_percentage: float
    summary: dict[str, int]
    findings: list[RatioFinding]
    latency_ms: float


class StatutoryBoundaryDefinition(BaseModel):
    rule_id: str
    ratio_name: str
    description: str
    regulator: str
    statutory_citation: str
    operator: Literal[">=", "<=", ">", "<"]
    threshold_value: float
    unit: str
    default_tolerance_pct: float
    category: str
    applicable_entities: list[str]
    guidance_on_breach: str


class BoundaryCatalogResponse(BaseModel):
    boundaries: list[StatutoryBoundaryDefinition]
    total: int


# --- Compliance "What-If" Sensitivity Simulator (FEAT-024) ---


class ScenarioPoint(BaseModel):
    step: int
    variable: str
    input_value: float
    delta_percentage: float
    computed_value: float
    status: Literal["COMPLIANT", "WARNING", "BREACH"] | None = None
    margin: float | None = None


class SensitivityResult(BaseModel):
    variable: str
    description: str | None = None
    baseline_input: float
    partial_derivative: float
    elasticity: float
    direction: Literal["positive", "negative", "neutral"]
    impact_rank: int
    breach_boundary_value: float | None = None


class StressScenarioResult(BaseModel):
    name: str
    description: str
    inputs: dict[str, float]
    computed_value: float
    delta_percentage_from_baseline: float
    status: Literal["COMPLIANT", "WARNING", "BREACH"] | None = None


class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    formula_id: str
    base_inputs: dict[str, float]
    deltas: dict[str, list[float]] = Field(default_factory=dict)
    sweep_variable: str | None = None
    sweep_percentage_range: float = Field(default=0.20, ge=0.01, le=1.0)
    sweep_steps: int = Field(default=10, ge=2, le=50)
    preset_scenario: str | None = None
    entity_type: str = "commercial_bank"


class SimulationResponse(BaseModel):
    formula_id: str
    formula_name: str
    expression: str
    unit: str
    baseline_value: float
    baseline_status: Literal["COMPLIANT", "WARNING", "BREACH"] | None = None
    statutory_threshold: str | None = None
    sensitivity_gradients: dict[str, float]
    elasticities: dict[str, float]
    sensitivities: list[SensitivityResult]
    scenario_curves: dict[str, list[ScenarioPoint]]
    stress_tests: list[StressScenarioResult] = Field(default_factory=list)
    latency_ms: float


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
    intent: IntentClassification | None = None
    extracted_tags: list[str] = Field(default_factory=list)
    normalized_query: str | None = None
    corrections_applied: dict[str, str] = Field(default_factory=dict)
    persona: str | None = None
    persona_applied: PersonaProfileResponse | None = None


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


class DocumentResponse(BaseModel):
    """Authoritative document metadata resolving an ingested circular (FR-14)."""

    document_id: str
    canonical_url: str
    source: str
    authority: str
    title: str | None = None
    published_date: str | None = None
    detail_page: str | None = None
    version_count: int = 1
    current_version_id: str | None = None
    chunk_count: int = 0
    created_at: datetime | None = None


class ErrorResponse(BaseModel):
    detail: str


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Annotated[
        str,
        StringConstraints(min_length=3, max_length=1024, strip_whitespace=True),
    ]
    workspace_id: str = "00000000-0000-0000-0000-000000000000"
    k: Annotated[int, Field(default=5, ge=1, le=20)] = 5
    mode: Literal["dense", "bm25", "hybrid", "graph-hybrid"] = "graph-hybrid"
    max_aspects: Annotated[int, Field(default=3, ge=1, le=5)] = 3


class WorkspaceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[
        str,
        StringConstraints(min_length=1, max_length=200, strip_whitespace=True),
    ] = "Default Regulatory Workspace"


class WorkspaceResponse(BaseModel):
    workspace_id: str
    name: str
    created_at: str


class ResearchArtifactSummary(BaseModel):
    artifact_id: str
    query: str
    title: str
    grounded: bool
    abstained: bool
    created_at: str


class ResearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact: ResearchArtifact
    workspace_id: str


# --- Analyst Identity & Research Interests ---


class UserProfileResponse(BaseModel):
    user_id: str
    auth0_sub: str
    email: str
    role: str
    display_name: str | None = None
    is_service_key: bool = False


class UserInterestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: Annotated[
        str,
        StringConstraints(min_length=2, max_length=200, strip_whitespace=True),
    ]
    regulator: Literal["RBI", "SEBI", "ALL"] = "ALL"
    keywords: list[str] = Field(default_factory=list)


class UserInterestResponse(BaseModel):
    interest_id: str
    user_id: str
    topic: str
    regulator: str
    keywords: list[str]
    created_at: str


# --- Brevo Subscriptions & Regulatory Digests ---


def _default_regulators() -> list[Literal["RBI", "SEBI", "ALL"]]:
    return ["ALL"]


class SubscriptionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frequency: Literal["immediate", "daily", "weekly"] = "weekly"
    topics: list[str] = Field(default_factory=lambda: ["ALL"])
    regulators: list[Literal["RBI", "SEBI", "ALL"]] = Field(default_factory=_default_regulators)
    consent: bool = Field(
        ...,
        description="Explicit user consent required for regulatory email alerts.",
    )


class SubscriptionResponse(BaseModel):
    subscription_id: str
    user_id: str
    email: str
    frequency: str
    is_active: bool
    topics: list[str]
    regulators: list[str]
    consent_ts: str
    unsubscribe_url: str


class UnsubscribeResponse(BaseModel):
    status: str
    detail: str


class DigestDispatchResponse(BaseModel):
    status: str
    frequency: str
    dispatched_notifications: int


class WebhookProcessResponse(BaseModel):
    status: str
    event: str
    processed: bool


# --- OCR.Space Inspection & Fallback ---


class OCRInspectionResponse(BaseModel):
    sha256: str
    status: str
    engine: str
    pages_processed: int
    clean_char_count: int
    extracted_text_sample: str
    latency_ms: float
    error_detail: str | None = None
    cached: bool = False


# --- Regulatory Discovery ---


class DiscoveryTriggerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rbi_limit: Annotated[int, Field(default=5, ge=1, le=20)] = 5
    sebi_limit: Annotated[int, Field(default=5, ge=1, le=20)] = 5
    dry_run: bool = False


class DiscoveryTriggerResponse(BaseModel):
    status: str
    discovered_total: int
    new_documents: int
    content_revisions: int
    unchanged: int
    failed: int
    items: list[dict[str, Any]]


# --- Knowledge Graph Subgraph Projection (FEAT-004) ---


class GraphNode(BaseModel):
    id: str
    label: str
    domain: str = "regulatory"
    level: str = "statutory"


class GraphEdge(BaseModel):
    source: str
    target: str
    relation: str


class SubgraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    root_id: str


# --- Interactive Search Query Suggestions (FEAT-019) ---


class QuerySuggestion(BaseModel):
    id: str
    text: str
    category: Literal["term", "statutory", "acronym", "related"]
    domain: str | None = None
    domain_name: str | None = None
    score: float = 1.0
    highlight: str | None = None
    related_queries: list[str] = Field(default_factory=list)


class SuggestionResponse(BaseModel):
    query: str
    normalized_query: str | None = None
    suggestions: list[QuerySuggestion]
    latency_ms: float
    total: int


# --- Standard-Linked Formula Annotator (FEAT-025) ---


class StandardResponse(BaseModel):
    id: str
    name: str
    governing_body: str
    domain: str
    jurisdiction: str = "global"
    category: str = "technical"
    description: str | None = None
    official_reference_url: str | None = None
    note: str | None = None
    aliases: list[str] = Field(default_factory=list)


class StandardListResponse(BaseModel):
    total: int
    standards: list[StandardResponse]


class AnnotatedFormulaResponse(BaseModel):
    formula_id: str
    formula_name: str
    expression: str
    standard_id: str | None = None
    standard_name: str | None = None
    governing_body: str | None = None
    domain: str | None = None
    standard_citation: str | None = None
    confidence: float = 1.0
    status: Literal["LINKED", "UNLINKED", "AMBIGUOUS"] = "LINKED"
    linked_clauses: list[str] = Field(default_factory=list)


class AnnotateFormulaRequest(BaseModel):
    formula_id: str | None = None
    formula_name: str | None = None
    expression: str | None = None
    standard_hint: str | None = None
    text_snippet: str | None = None
    strict_matching: bool = True


# --- Numerical Regulatory Evidence Extractor (FEAT-026) ---


class StatutoryParameterModel(BaseModel):
    id: str
    document_id: str
    parameter_name: str
    parameter_type: str
    numeric_value: float
    unit: str
    normalized_value: float
    normalized_unit: str
    comparison_operator: str
    statutory_context: str
    threshold_ceiling: float | None = None
    section_reference: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    confidence_score: float = 1.0


class ExtractParametersRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1, max_length=100_000)
    document_id: str = "doc-generic"
    version_id: str | None = None


class ExtractParametersResponse(BaseModel):
    document_id: str
    parameters: list[StatutoryParameterModel]
    total_count: int
    parameter_types: list[str]
    latency_ms: float


class DocumentParametersResponse(BaseModel):
    document_id: str
    parameters: list[StatutoryParameterModel]
    total_count: int


# --- Mathematical Sanity & Consistency Auditor (FEAT-027) ---


class ConsistencyAnomalyModel(BaseModel):
    anomaly_type: str
    severity: str
    rule_name: str
    message: str
    location: str
    reported_value: float | None = None
    expected_value: float | None = None
    discrepancy: float | None = None
    tolerance: float = 0.01
    remediation_hint: str = ""


class AuditTableModel(BaseModel):
    title: str | None = None
    headers: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    row_labels: list[str] = Field(default_factory=list)
    has_row_totals: bool | None = None
    has_col_totals: bool | None = None
    tolerance: float = 0.01


class AuditSanityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str | None = None
    return_code: str = "GENERIC"
    declared_values: dict[str, float] = Field(default_factory=dict)
    tables: list[AuditTableModel] = Field(default_factory=list)
    tolerance: float = 0.01


class AuditSanityResponse(BaseModel):
    is_valid: bool
    total_rules_checked: int
    anomalies_count: int
    anomalies: list[ConsistencyAnomalyModel]
    passed_checks: list[str]
    summary: str
    latency_ms: float


class AuditRuleDefinitionModel(BaseModel):
    rule_id: str
    name: str
    category: str
    severity: str
    statutory_ref: str
    description: str


class AuditRulesCatalogResponse(BaseModel):
    rules: list[AuditRuleDefinitionModel]
    total_count: int


# --- Indian Financial Unit Normalizer (FEAT-028) ---


class NormalizedQuantityModel(BaseModel):
    raw_expression: str
    canonical_value: float
    canonical_unit: str
    currency_symbol: str | None = None
    scale_label: str
    scale_multiplier: float
    indian_words: str
    indian_numeric_formatted: str
    international_words: str
    international_numeric_formatted: str
    bps_equivalent: float | None = None
    percent_equivalent: float | None = None
    synonym_representations: list[str] = Field(default_factory=list)
    is_valid: bool = True


class NormalizeUnitsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expressions: list[str] = Field(..., min_length=1, max_length=100)


class NormalizeUnitsResponse(BaseModel):
    results: list[NormalizedQuantityModel]
    total_count: int
    latency_ms: float


class QuantityComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expression_a: str = Field(..., min_length=1, max_length=200)
    expression_b: str = Field(..., min_length=1, max_length=200)
    tolerance: float = 0.001


class QuantityComparisonResponse(BaseModel):
    are_equivalent: bool
    quantity_a: NormalizedQuantityModel
    quantity_b: NormalizedQuantityModel
    absolute_difference: float
    relative_difference: float
    tolerance: float
    latency_ms: float


# --- Formula Dependency Graph Builder (FEAT-029) ---


class GraphNodeModel(BaseModel):
    node_id: str
    name: str
    node_type: str
    expression: str | None = None
    description: str = ""
    category: str = "general"
    unit: str = "ratio"
    tier: int = 0
    dependencies: list[str] = Field(default_factory=list)


class GraphEdgeModel(BaseModel):
    source: str
    target: str
    parameter_name: str


class DependencyGraphResponse(BaseModel):
    graph_id: str
    name: str
    domain: str
    description: str
    nodes: dict[str, GraphNodeModel]
    edges: list[GraphEdgeModel]
    topological_order: list[str]
    execution_tiers: list[list[str]]
    target_variables: list[str]


class BuildGraphFormulaInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=100)
    name: str | None = None
    expression: str = Field(..., min_length=1)
    description: str = ""
    category: str = "custom"
    unit: str = "ratio"
    dependencies: list[str] | None = None


class BuildGraphRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph_id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=200)
    domain: str = "custom"
    description: str = ""
    formulas: list[BuildGraphFormulaInput] = Field(..., min_length=1)
    target_variables: list[str] | None = None


class EvaluateGraphRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph_id: str | None = None
    template_id: str | None = None
    provided_inputs: dict[str, float] = Field(..., min_length=1)


class EvaluationTraceStep(BaseModel):
    node_id: str
    node_type: str
    value: float | None = None
    status: str
    expression: str | None = None
    tier: int | None = None
    missing_prerequisites: list[str] | None = None
    error: str | None = None


class EvaluateGraphResponse(BaseModel):
    is_complete: bool
    target_outputs: dict[str, float | None]
    computed_values: dict[str, float]
    trace: list[EvaluationTraceStep]
    missing_variables: list[str]
    latency_ms: float


class PrerequisiteCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph_id: str | None = None
    template_id: str | None = None
    target_variables: list[str] | None = None
    provided_inputs: dict[str, float] = Field(default_factory=dict)


class PrerequisiteCheckResponse(BaseModel):
    is_ready: bool
    target_variables: list[str]
    required_inputs_count: int
    provided_inputs: list[str]
    missing_inputs: list[str]
    completion_percentage: float
    resolvable_intermediates: list[str]


class GraphTemplateSummaryModel(BaseModel):
    template_id: str
    name: str
    domain: str
    stages_count: int
    target_variables: list[str]
    description: str


# --- Historical Formula Evolution & Versioning (FEAT-030) ---


class FormulaVersionModel(BaseModel):
    id: str
    formula_id: str
    version_label: str
    regulatory_framework: str
    effective_from: str
    effective_to: str | None = None
    expression: str
    eval_expression: str
    variables: list[str]
    thresholds: dict[str, Any] = Field(default_factory=dict)
    circular_reference: str | None = None
    change_summary: str
    is_currently_active: bool = False


class FormulaHistoryResponse(BaseModel):
    formula_id: str
    total_versions: int
    history: list[FormulaVersionModel]


class ResolveFormulaVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of_date: str = Field(..., description="Target point-in-time date in YYYY-MM-DD format.")


class CompareFormulaVersionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_a_id: str = Field(..., min_length=1)
    version_b_id: str = Field(..., min_length=1)


class CompareFormulaVersionsResponse(BaseModel):
    formula_id: str
    version_a_id: str
    version_b_id: str
    version_a_label: str
    version_b_label: str
    expression_changed: bool
    expression_a: str
    expression_b: str
    variables_added: list[str]
    variables_removed: list[str]
    variables_retained: list[str]
    threshold_changes: dict[str, dict[str, Any]]
    change_type: str
    summary: str


class TrackedFormulaSummaryModel(BaseModel):
    formula_id: str
    current_label: str
    regulatory_framework: str
    version_count: int
    earliest_effective: str
    current_expression: str
    current_thresholds: dict[str, Any]


# --- Statutory Deprecation & Supersession Engine (FEAT-031) ---


class StatutoryDeprecationModel(BaseModel):
    id: str
    subject: str
    subject_type: str
    regulator: str
    status: str
    reason: str
    superseded_by: str | None = None
    effective_date: str
    sunset_date: str | None = None
    grandfathering_clause: str | None = None
    replacement: list[str]
    guidance: str
    severity: str
    citation_patterns: list[str] = []
    aliases: list[str] = []
    is_sunset_passed: bool = False


class SupersessionNodeModel(BaseModel):
    instrument_id: str
    title: str
    regulator: str
    status: str
    effective_date: str
    is_currently_active: bool


class SupersessionChainModel(BaseModel):
    root_instrument: str
    active_authority: str
    depth: int
    has_cycle: bool
    chain: list[SupersessionNodeModel]


class DeprecationDetectionModel(BaseModel):
    deprecation_id: str
    matched_text: str
    subject: str
    subject_type: str
    regulator: str
    status: str
    severity: str
    superseded_by: str | None = None
    active_authority: str | None = None
    supersession_chain: list[str] = []
    reason: str
    replacement: list[str]
    guidance: str
    effective_date: str
    sunset_date: str | None = None
    is_sunset_passed: bool = False
    grandfathering_clause: str | None = None


class CheckSupersessionRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=100000)
    as_of_date: str | None = Field(
        default=None, description="Optional ISO date YYYY-MM-DD for point-in-time check"
    )
    regulator: str | None = Field(
        default=None, description="Optional regulator filter e.g. RBI, SEBI, PMLA"
    )


class CheckSupersessionResponse(BaseModel):
    detections: list[DeprecationDetectionModel]
    total_flagged: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    is_compliant: bool
    recommended_actions: list[str]
    latency_ms: float


class DeprecationCatalogResponse(BaseModel):
    deprecations: list[StatutoryDeprecationModel]
    total_count: int
    regulators: list[str]


# --- Circular Clause Conflict Detector (FEAT-032) ---


class CircularClauseModel(BaseModel):
    id: str
    circular_id: str
    circular_title: str
    regulator: str
    section_reference: str
    clause_text: str
    domain_category: str
    modality: str
    parameter_name: str | None = None
    parameter_value: float | None = None
    parameter_unit: str | None = None
    comparison_operator: str | None = None
    effective_date: str
    is_active: bool = True


class DetectedConflictModel(BaseModel):
    conflict_id: str
    clause_a: CircularClauseModel
    clause_b: CircularClauseModel
    conflict_type: str
    severity: str
    parameter_name: str | None = None
    explanation: str
    prescriptive_action: str


class DetectConflictsRequest(BaseModel):
    clauses: list[CircularClauseModel] | None = Field(
        default=None,
        description="Optional list of custom clauses to analyze; if omitted, checks active registry.",
    )
    domain_category: str | None = Field(
        default=None,
        description="Optional domain filter e.g. fldg, incident_reporting, capital_adequacy",
    )


class DetectConflictsResponse(BaseModel):
    conflicts: list[DetectedConflictModel]
    total_conflicts: int
    critical_count: int
    high_count: int
    medium_count: int
    has_conflicts: bool
    domains_affected: list[str]
    latency_ms: float


class CompareClausePairRequest(BaseModel):
    clause_a: CircularClauseModel
    clause_b: CircularClauseModel


class CompareClausePairResponse(BaseModel):
    conflict_detected: bool
    conflict: DetectedConflictModel | None = None
    latency_ms: float


class ConflictBenchmarkResponse(BaseModel):
    total_conflicting_pairs: int
    detected_conflicts: int
    detection_rate: float
    total_non_conflicting_pairs: int
    false_positives: int
    precision: float
    benchmark_passed: bool


# --- Regulatory & Technical Antipattern Scanner (FEAT-033) ---


class AntipatternRuleModel(BaseModel):
    id: str
    practice: str
    antipattern: str
    consequence: str
    instead: list[str]
    domain_category: str
    severity: str
    regex_patterns: list[str] = []
    keywords: list[str] = []


class AntipatternFindingModel(BaseModel):
    rule_id: str
    practice: str
    antipattern: str
    consequence: str
    instead: list[str]
    severity: str
    domain_category: str
    matched_snippet: str
    line_number: int | None = None
    confidence: float


class ScanAntipatternsRequest(BaseModel):
    text: str = Field(
        ...,
        min_length=1,
        max_length=150000,
        description="Compliance manual, policy, or architecture document text",
    )
    document_name: str = Field(
        default="manual.md", description="Identifier or filename for audit tracking"
    )
    severity_filter: str | None = Field(
        default=None, description="Optional severity filter: CRITICAL, HIGH, MEDIUM"
    )


class ScanAntipatternsResponse(BaseModel):
    document_name: str
    findings: list[AntipatternFindingModel]
    total_findings: int
    critical_count: int
    high_count: int
    medium_count: int
    overall_score: float
    affected_domains: list[str]
    is_healthy: bool
    latency_ms: float


class AntipatternCatalogResponse(BaseModel):
    rules: list[AntipatternRuleModel]
    total_count: int
    domains: list[str]


class AntipatternBenchmarkResponse(BaseModel):
    total_seeded_antipatterns: int
    detected_antipatterns: int
    false_positives: int
    false_negatives: int
    recall: float
    precision: float
    overall_score: float
    benchmark_passed: bool


# --- "Instead-Of" Prescriptive Remediation Engine (FEAT-034) ---


class PracticeRecommendationModel(BaseModel):
    name: str
    term_id: str
    definition: str
    value_justification: str
    tier: int
    domain: str
    gate_criteria: str | None = None
    implementation_steps: list[str] = []
    standard_reference: str | None = None


class RemediationPlanModel(BaseModel):
    flaw_id: str
    flaw_type: str
    identified_flaw: str
    consequence_or_reason: str
    severity: str
    recommended_practices: list[PracticeRecommendationModel]
    guidance: str | None = None
    lookup_latency_ms: float = 0.0


class GenerateRemediationRequest(BaseModel):
    flaw_id: str | None = Field(
        default=None,
        description="Canonical flaw identifier (e.g. ap-line-coverage or DREAD)",
    )
    practice_or_subject: str | None = Field(
        default=None,
        description="Practice or deprecation title (e.g. Statement Coverage or DREAD)",
    )
    include_implementation_steps: bool = Field(
        default=True,
        description="Whether to generate actionable implementation checklist steps",
    )


class BatchRemediationRequest(BaseModel):
    flaw_ids: list[str] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="List of flaw IDs to generate remediations for",
    )
    include_implementation_steps: bool = Field(
        default=True,
        description="Whether to include actionable implementation checklist steps",
    )


class BatchRemediationResponse(BaseModel):
    total_findings: int
    remediated_findings: int
    plans: list[RemediationPlanModel]
    unique_recommended_practices: list[str]
    latency_ms: float


class RemediationCatalogResponse(BaseModel):
    total_plans: int
    total_practices_mapped: int
    plans: list[RemediationPlanModel]


class RegulatoryDeadlineModel(BaseModel):
    doc_id: str
    mandate_description: str
    effective_date: str
    days_remaining: int
    urgency_level: Literal["CRITICAL", "WARNING", "INFO"]
    extracted_snippet: str | None = None
    confidence: float = 1.0


class ExtractDeadlinesRequest(BaseModel):
    text: str = Field(..., min_length=100, description="Circular document text")
    doc_id: str = Field(..., description="Circular identifier or reference")
    critical_threshold_days: int = Field(default=15, ge=1)
    warning_threshold_days: int = Field(default=45, ge=1)
    reference_date: str | None = Field(default=None, description="Reference date YYYY-MM-DD")


class ExtractDeadlinesResponse(BaseModel):
    doc_id: str
    total_deadlines: int
    deadlines: list[RegulatoryDeadlineModel]
    latency_ms: float = 0.0


class DispatchDeadlineAlertsRequest(BaseModel):
    deadlines: list[RegulatoryDeadlineModel] = Field(default_factory=list)
    recipients: list[str] = Field(
        default_factory=list, description="Target email recipients for cutover alerts"
    )
    dry_run: bool = Field(default=False, description="Simulate dispatch without sending emails")


class DispatchDeadlineAlertsResponse(BaseModel):
    total_checked: int
    alerts_dispatched: int
    critical_count: int
    warning_count: int
    info_count: int
    duration_ms: float


class ClassifyScopeRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Clause text to classify")


class ClassifyScopeResponse(BaseModel):
    scope: Literal["ALL", "NEW_ENTRANTS_ONLY", "GRANDFATHERED_EXISTING"]
    confidence: float
    operative_condition: str
    latency_ms: float = 0.0


class ScorecardRequest(BaseModel):
    policy_document_texts: list[str] = Field(
        ...,
        description="List of policy document texts to evaluate against compliance rubrics",
    )
    organization_type: str = Field(
        default="scheduled_commercial_bank",
        description="Type of entity: scheduled_commercial_bank, nbfc, payment_aggregator, fintech, etc.",
    )
    include_pdf: bool = Field(
        default=False,
        description="Whether to render and return a base64-encoded PDF audit scorecard",
    )
    grading_rubric_weights: dict[str, float] | None = Field(
        default=None,
        description="Custom rubric weights for antipatterns, deprecations, and standards_coverage",
    )

    @field_validator("policy_document_texts")
    @classmethod
    def validate_policy_texts(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("At least 1 policy document text must be provided")
        has_adequate_doc = any(len(doc.split()) >= 100 for doc in v if doc and doc.strip())
        if not has_adequate_doc:
            raise ValueError("At least 1 policy document text must contain at least 100 words")
        return v


class ScorecardResponse(BaseModel):
    overall_grade: Literal["A", "B", "C", "D", "F"]
    numerical_score: float = Field(..., ge=0.0, le=100.0)
    antipatterns_count: int
    deprecations_count: int
    standards_coverage_score: float = Field(..., ge=0.0, le=100.0)
    critical_risks: list[str]
    remediation_timeline_days: int
    markdown_report: str
    pdf_content_base64: str | None = None
    latency_ms: float = 0.0


class StandardMetadata(BaseModel):
    id: str
    name: str
    governing_body: str
    domain: str
    jurisdiction: str = "global"
    category: str = "technical"
    note: str | None = None
    description: str | None = None
    official_reference_url: str | None = None
    control_families: list[str] = Field(default_factory=list)
    control_count: int = 0
    mapped_circulars_count: int = 0
    aliases: list[str] = Field(default_factory=list)


class StandardsListResponse(BaseModel):
    standards: list[StandardMetadata]
    total: int
    domains: list[str] = Field(default_factory=list)
    governing_bodies: list[str] = Field(default_factory=list)


# --- Cross-Framework Control Mapping Matrix (FEAT-042) ---


class MappedControl(BaseModel):
    framework: str
    control_id: str
    title: str
    equivalence_level: Literal["EXACT", "SUBSET", "SUPERSET"]
    citation_spans: list[str] = Field(default_factory=list)
    notes: str | None = None


class CrosswalkResponse(BaseModel):
    source_framework: str
    target_framework: str
    source_control: str | None = None
    source_control_title: str | None = None
    target_controls: list[MappedControl] = Field(default_factory=list)
    citation_spans: list[str] = Field(default_factory=list)
    equivalence_summary: str | None = None
    coverage_percentage: float | None = None
    total_mappings: int = 0
    mappings: list[dict[str, Any]] | None = None


# --- Multi-Jurisdiction Compliance Harmonizer (FEAT-043) ---


class HarmonizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(
        ..., min_length=2, max_length=200, description="Compliance domain or statutory subject"
    )
    jurisdiction_a: str = Field(
        ..., description="First jurisdiction code (e.g. IN_RBI, EU_DORA, US_NIST)"
    )
    jurisdiction_b: str = Field(
        ..., description="Second jurisdiction code (e.g. EU_GDPR, US_FEDRAMP, GLOBAL_ISO)"
    )


class HarmonizationReport(BaseModel):
    topic: str
    jurisdiction_a: str
    jurisdiction_b: str
    delta_classification: Literal["STRICTER_A", "EQUIVALENT", "STRICTER_B"]
    comparative_analysis: str
    localized_mandates: list[str] = Field(default_factory=list)
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    statutory_citations: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0


# --- ISO/NIST Clause Cross-Citation Hyperlinking (FEAT-046) ---


class ExtractStandardMentionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(
        ..., min_length=1, max_length=500000, description="Regulatory circular text to analyze"
    )
    document_id: str | None = Field(default=None, description="Optional document UUID")
    chunk_id: str | None = Field(default=None, description="Optional chunk UUID")


class StandardMentionResponse(BaseModel):
    span: list[int]
    raw_text: str
    standard_id: str
    control_hint: str | None = None
    standard_name: str | None = None
    governing_body: str | None = None


class ExtractStandardMentionsResponse(BaseModel):
    mentions: list[StandardMentionResponse]
    total_count: int


class DocumentStandardMentionsResponse(BaseModel):
    document_id: str
    mentions: list[StandardMentionResponse]
    total_count: int


# --- Audit Evidence Package Exporter (FEAT-047) ---


class ExportEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        ..., min_length=1, max_length=512, description="Target search query or audit mandate"
    )
    passage_ids: list[str] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="List of cited passage or chunk IDs to bundle (1 to 50 items)",
    )
    format: Literal["PDF", "ZIP", "MARKDOWN"] = Field(
        default="PDF", description="Output export archive format"
    )
    audit_reference_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        pattern=r"^[a-zA-Z0-9_\-\.:/ ]+$",
        description="Auditor reference tracking number or engagement ID",
    )
    include_control_mappings: bool = Field(
        default=True, description="Whether to include resolved statutory control crosswalks"
    )


class ExportResponse(BaseModel):
    download_url: str
    file_sha256: str
    expires_at: datetime
    items_included: int
    format: Literal["PDF", "ZIP", "MARKDOWN"]
    audit_reference_id: str


# --- Continuous Compliance Observation Window Tracker (FEAT-048) ---


class TelemetryEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="default", max_length=100)
    control_id: str = Field(..., min_length=1, max_length=100)
    observation_timestamp: datetime
    check_result: Literal["PASS", "FAIL"]
    evidence_hash: str = Field(..., min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")


class TelemetryBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="default", max_length=100)
    control_id: str | None = Field(default=None, max_length=100)
    observation_timestamp: datetime | None = None
    check_result: Literal["PASS", "FAIL"] | None = None
    evidence_hash: str | None = Field(default=None, max_length=64)
    events: list[TelemetryEventInput] | None = None

    @model_validator(mode="after")
    def validate_batch_or_single(self) -> TelemetryBatch:
        if self.events is None or len(self.events) == 0:
            if (
                not self.control_id
                or not self.observation_timestamp
                or not self.check_result
                or not self.evidence_hash
            ):
                raise ValueError(
                    "Either 'events' list or (control_id, observation_timestamp, check_result, evidence_hash) must be provided"
                )
        return self

    def to_events(self) -> list[TelemetryEventInput]:
        if self.events and len(self.events) > 0:
            return self.events
        if not (
            self.control_id
            and self.observation_timestamp
            and self.check_result
            and self.evidence_hash
        ):
            raise ValueError(
                "Missing required telemetry event fields: control_id, observation_timestamp, check_result, evidence_hash"
            )
        return [
            TelemetryEventInput(
                tenant_id=self.tenant_id,
                control_id=self.control_id,
                observation_timestamp=self.observation_timestamp,
                check_result=self.check_result,
                evidence_hash=self.evidence_hash,
            )
        ]


class TelemetryIngestResponse(BaseModel):
    accepted_count: int
    status: str = "INGESTED"
    event_ids: list[str]


class ObservationStatusResponse(BaseModel):
    control_id: str
    tenant_id: str = "default"
    observation_window_days: int
    compliance_percentage: float
    unbroken_streak_days: int
    total_observations: int
    pass_count: int
    fail_count: int
    window_start: datetime | None = None
    window_end: datetime | None = None
    status: Literal["COMPLIANT", "NON_COMPLIANT", "INSUFFICIENT_DATA"]


class ObservationConfigModel(BaseModel):
    min_window_days: int = 90


# --- Third-Party Vendor Risk Assessment Engine (FEAT-049) ---


class VendorRiskAuditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_text: str = Field(
        ...,
        min_length=100,
        max_length=150000,
        description="Raw text of third-party vendor agreement (100 to 150,000 characters)",
    )
    vendor_type: Literal["CLOUD", "SAAS", "PAYMENT_SWITCH", "DATACENTER"] = Field(
        ..., description="Classification category of third-party vendor"
    )
    vendor_name: str | None = Field(
        default=None, max_length=150, description="Optional legal entity name of the vendor"
    )
    strict_localization: bool = Field(
        default=True, description="Whether to enforce strict Indian onshore data storage"
    )


class MissingClauseModel(BaseModel):
    clause_name: str
    statutory_requirement: str
    rbi_circular_citation: str
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    remediation_guidance: str


class DetectedClauseModel(BaseModel):
    clause_name: str
    confidence: float
    matched_snippet: str


class VendorRiskReportResponse(BaseModel):
    vendor_name: str | None = None
    vendor_type: Literal["CLOUD", "SAAS", "PAYMENT_SWITCH", "DATACENTER"]
    compliance_score: float
    risk_rating: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    mandatory_clauses_present: list[str]
    missing_clauses: list[MissingClauseModel]
    detected_clauses: list[DetectedClauseModel]
    contract_char_count: int
    audit_timestamp: datetime
    strict_localization_enforced: bool


# --- Algorithmic & AI Impact Assessment Framework (FEAT-050) ---


class AlgoAssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_name: str = Field(
        ...,
        min_length=1,
        max_length=150,
        description="Name or identifier of algorithmic/AI system being assessed",
    )
    model_type: Literal[
        "algorithmic_trading",
        "credit_scoring",
        "llm_agent",
        "fraud_detection",
        "general_ai",
    ] = Field(
        default="algorithmic_trading",
        description="Domain category of the model under statutory review",
    )
    system_spec_text: str = Field(
        ...,
        min_length=100,
        max_length=50000,
        description="System architecture, risk controls, or model card documentation (100-50,000 chars)",
    )
    strict_kill_switch_required: bool = Field(
        default=True,
        description="Enforce hard conformity cap if automated kill switch is absent for trading systems",
    )


class FailedControlModel(BaseModel):
    control_id: str
    title: str
    regulation_ref: str
    remedy: str


class AlgoAssessmentResponse(BaseModel):
    system_name: str
    model_type: str
    conformity_score: float
    status: Literal["CONFORMANT", "CONDITIONAL", "NON_CONFORMANT"]
    passed_controls: list[str]
    failed_controls: list[FailedControlModel]
    negative_flags: list[str]
    audit_certificate_id: str
    evaluated_at: datetime
    summary: str


# --- Interactive Compliance Playbook Runtime (FEAT-051 & FEAT-052) ---


class StartPlaybookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    playbook_id: str = Field(
        ...,
        description="Taxonomy playbook ID (e.g., 'playbook.foundations-30d')",
    )
    tenant_id: str = Field(
        default="default",
        description="Multi-tenant identifier for playbook execution isolation",
    )
    assigned_lead: str = Field(
        default="Compliance Team",
        min_length=1,
        max_length=150,
        description="Name or role of the compliance lead in charge",
    )


class AdvanceStageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_stage: int | None = Field(
        default=None,
        ge=1,
        le=10,
        description="Target stage number to transition to (defaults to current_stage + 1)",
    )


class CompleteMilestoneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    milestone_id: str = Field(
        ...,
        min_length=1,
        description="ID of the milestone within the active stage to complete",
    )
    evidence_doc_id: str | None = Field(
        default=None,
        description="Optional reference ID to grounding evidence artifact or document",
    )
    notes: str = Field(
        default="",
        max_length=2000,
        description="Compliance audit notes or verification remarks",
    )


class MilestoneSummaryModel(BaseModel):
    id: str
    title: str
    role: str
    mandatory: bool = True
    estimated_hours: int = 8
    completed: bool = False
    completed_at: str | None = None
    evidence_doc_id: str | None = None
    notes: str = ""


class StageProgress(BaseModel):
    stage_number: int
    stage_name: str
    total_milestones: int
    completed_milestones: int
    completion_ratio: float
    exit_ready: bool


class StageSummaryModel(BaseModel):
    number: int

    name: str
    objective: str
    exit_criteria: list[str]
    milestones: list[MilestoneSummaryModel]


class PlaybookTemplateSummary(BaseModel):
    playbook_id: str
    title: str
    description: str
    domain: str
    total_stages: int
    stages: list[StageSummaryModel]


class PlaybookRunResponse(BaseModel):
    run_id: str
    tenant_id: str
    playbook_id: str
    title: str
    assigned_lead: str
    current_stage: int
    total_stages: int
    status: Literal["ACTIVE", "BLOCKED", "COMPLETED"]
    stage_data: dict[str, Any]
    created_at: datetime
    updated_at: datetime


# --- Automated Stage Exit Criteria Validator (FEAT-053) ---


class CriterionCheck(BaseModel):
    criterion: str
    status: Literal["PASSED", "FAILED"]
    evidence_ref: str = ""


class ExitValidationResult(BaseModel):
    can_advance: bool
    exit_statement: str
    checks_evaluated: list[CriterionCheck]
    blocking_issues: list[str]
    override_applied: bool = False
    validation_id: str | None = None


class PromoteStageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_stage: int = Field(
        ...,
        ge=1,
        le=10,
        description="Current active stage number being promoted from",
    )
    override_justification: str | None = Field(
        default=None,
        description="Optional administrative exception rationale for bypassing exit criteria (min 15 chars)",
    )


# --- Role-Based Compliance Task Routing (FEAT-054) ---


class RoleTask(BaseModel):
    task_id: str
    title: str
    stage: int
    term_reference: str = ""
    estimated_hours: int = 8
    role: str
    completed: bool = False
    mandatory: bool = True


class RoleTaskList(BaseModel):
    role: str
    pending_tasks: list[RoleTask]
    completed_tasks: list[RoleTask] = Field(default_factory=list)
    total_estimated_hours: int = 0


# --- Regulatory Cyber Incident Response Playbook (FEAT-055) ---


class DeclareIncidentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Literal["SEV1", "SEV2"] = Field(
        ...,
        description="Incident severity tier per statutory incident response matrix",
    )
    summary: str = Field(
        ...,
        min_length=20,
        description="Incident summary and initial forensic observations (minimum 20 characters)",
    )
    systems_impacted: list[str] = Field(
        ...,
        min_length=1,
        description="Critical banking and infrastructure systems impacted",
    )
    discovery_timestamp: datetime = Field(
        ...,
        description="Timestamp when the cybersecurity incident was first discovered",
    )

    @field_validator("discovery_timestamp")
    @classmethod
    def validate_discovery_timestamp_not_future(cls, v: datetime) -> datetime:
        now = datetime.now(UTC)
        v_utc = v if v.tzinfo is not None else v.replace(tzinfo=UTC)
        if (v_utc - now).total_seconds() > 10:
            raise ValueError("discovery_timestamp cannot be in the future")
        return v


class IncidentActionItem(BaseModel):
    action_id: str
    title: str
    role: str = "sre"
    completed: bool = False
    completed_at: datetime | None = None


class IncidentCrisisState(BaseModel):
    incident_id: UUID
    severity: Literal["SEV1", "SEV2"]
    summary: str
    systems_impacted: list[str]
    discovery_timestamp: datetime
    statutory_reporting_deadline: datetime
    minutes_remaining: int
    required_actions: list[str]
    actions_completed: list[str] = Field(default_factory=list)
    disclosure_draft: str
    status: Literal["DECLARED", "CONTAINED", "REPORTED", "RESOLVED"] = "DECLARED"
    warning_issued: bool = False
    run_id: UUID | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CompleteIncidentActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: str = Field(default="", description="Optional verification or forensic notes")


# --- Regulated Release Certification Pipeline (FEAT-056) ---


class CertifyReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commit_sha: str = Field(
        ...,
        pattern=r"^[0-9a-fA-F]{40}$",
        description="40-character hexadecimal git commit SHA",
    )
    build_id: str = Field(..., min_length=1, description="CI build identifier")
    test_report_path: str = Field(..., description="Path to JUnit XML or JSON test report")
    coverage_report_path: str = Field(..., description="Path to coverage report (XML or JSON)")
    mutation_report_path: str | None = Field(
        default=None, description="Path to mutation score report"
    )
    sast_report_path: str | None = Field(
        default=None, description="Path to static security scan report"
    )


class ReleaseCertificate(BaseModel):
    certificate_id: UUID
    commit_sha: str
    build_id: str
    is_certified: bool
    gsn_safety_case_json: dict[str, Any]
    signature_sha256: str
    rejection_reasons: list[str] = Field(default_factory=list)
    certified_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# --- Post-Quantum Cryptographic Migration Tracker (FEAT-057) ---


class EndpointCryptoSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hostname: str = Field(..., min_length=1, description="Target hostname or FQDN")
    port: int = Field(default=443, ge=1, le=65535, description="TLS service port")
    tls_version: str = Field(..., description="TLS protocol version, e.g. TLSv1.3, TLSv1.2")
    cipher_suite: str = Field(
        ..., min_length=1, description="Negotiated or supported cipher suite string"
    )
    key_exchange_group: str | None = Field(
        default=None, description="Key exchange group or KEM name"
    )
    cert_signature_algo: str = Field(..., description="X.509 certificate signature algorithm")
    cert_key_size: int | None = Field(default=None, description="Public key size in bits")
    cert_expiry: date | None = Field(default=None, description="Certificate expiration date")


class CryptographicInventoryBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoints: list[EndpointCryptoSpec] = Field(
        ..., min_length=1, description="List of endpoint cryptographic specifications"
    )


class PQCScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoints: list[EndpointCryptoSpec] = Field(
        ..., min_length=1, description="Batch of endpoint crypto specs to scan"
    )
    flag_rsa_under_3072: bool = Field(
        default=True, description="Flag RSA keys under 3072 bits as deprecated/vulnerable"
    )


class CryptoAssetItem(BaseModel):
    asset_id: UUID
    tenant_id: str = "default"
    hostname: str
    hostname_hash: str
    tls_version: str
    cipher_suite: str
    cert_signature_algo: str
    cert_key_size: int | None = None
    cert_expiry: date | None = None
    classification: Literal[
        "PQC_READY", "HYBRID", "CLASSICAL_SAFE", "CLASSICAL_DEPRECATED", "UNKNOWN_AUDIT_REQUIRED"
    ]
    hndl_vulnerable: bool
    quantum_safe_algo: str | None = None
    warning: str | None = None
    recommended_action: str
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PQCReadinessReport(BaseModel):
    total_assets: int
    quantum_vulnerable_count: int
    pqc_ready_count: int
    hybrid_count: int
    deprecated_count: int
    unknown_count: int
    hndl_exposure_score: float
    readiness_score: float
    migration_milestone: Literal[
        "PHASE_1_INVENTORY", "PHASE_2_HYBRID_TRANSITION", "PHASE_3_QUANTUM_RESILIENT"
    ]
    assets: list[CryptoAssetItem] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PQCInventoryResponse(BaseModel):
    tenant_id: str
    total_count: int
    assets: list[CryptoAssetItem]


# --- Digital Operational Resilience Framework (DORA) (FEAT-058) ---


class ICTSystemSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_id: str = Field(..., min_length=1, description="Unique system identifier")
    name: str = Field(..., min_length=1, description="System name")
    criticality: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] = Field(
        default="MEDIUM", description="DORA system criticality tier"
    )
    is_third_party: bool = Field(
        default=False, description="Whether the system is provided by a third-party vendor"
    )
    third_party_provider: str | None = Field(
        default=None, description="Name of third-party vendor if applicable"
    )
    is_critical_third_party: bool = Field(
        default=False,
        description="Whether vendor is a designated Critical ICT Third-Party Provider (CTPP)",
    )
    has_exit_strategy: bool = Field(
        default=False, description="Whether comprehensive exit and transition strategy exists"
    )
    last_tlpt_date: date | None = Field(
        default=None, description="Date of last Threat-Led Penetration Test (TLPT/TIBER-EU)"
    )
    rto_minutes: int | None = Field(
        default=None, ge=0, description="Recovery Time Objective in minutes"
    )
    rpo_minutes: int | None = Field(
        default=None, ge=0, description="Recovery Point Objective in minutes"
    )
    has_incident_plan: bool = Field(
        default=True,
        description="Whether documented incident response and reporting playbook exists",
    )
    has_threat_intel_sharing: bool = Field(
        default=False,
        description="Whether cyber threat intelligence sharing agreement is active",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional system architecture metadata"
    )


class DORAAssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="default", description="Tenant isolation identifier")
    ict_systems: list[ICTSystemSpec] = Field(
        ..., min_length=1, description="List of enterprise ICT system architecture specs"
    )


class PillarStatus(BaseModel):
    pillar_name: str
    compliance_pct: float
    gaps: list[str] = Field(default_factory=list)
    articles: list[str] = Field(default_factory=list)


class ResilienceTestRecord(BaseModel):
    test_id: UUID = Field(default_factory=uuid4)
    tenant_id: str = "default"
    system_id: str
    test_type: str = Field(
        ..., description="Type of resilience test, e.g. TLPT, FAILOVER, DR_SCENARIO"
    )
    executed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    passed: bool
    evidence_hash: str = Field(
        ..., description="Cryptographic SHA-256 hash of verified test evidence"
    )
    findings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RecordResilienceTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_id: str = Field(..., min_length=1, description="Target ICT system ID")
    test_type: str = Field(
        ..., min_length=1, description="Type of resilience test, e.g. TLPT, FAILOVER, DR"
    )
    passed: bool = Field(..., description="Whether the test passed successfully")
    evidence_hash: str = Field(..., min_length=8, description="Cryptographic hash of test evidence")
    findings: list[str] = Field(default_factory=list, description="Findings or gaps identified")
    tenant_id: str = Field(default="default", description="Tenant isolation key")


class RecordResilienceTestResponse(BaseModel):
    test_id: UUID
    status: str
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DORAComplianceReport(BaseModel):
    tenant_id: str = "default"
    total_systems: int
    critical_systems: int
    overall_readiness: float
    pillars: dict[str, PillarStatus]
    recommendations: list[str] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DORASystemsResponse(BaseModel):
    tenant_id: str
    total_count: int
    systems: list[ICTSystemSpec]


# --- Custom Enterprise Compliance Playbook Builder (FEAT-060) ---


class CustomMilestoneDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, description="Unique milestone identifier within playbook")
    title: str = Field(
        ..., min_length=1, description="Milestone title or actionable task description"
    )
    role: str = Field(
        default="compliance-officer",
        description="Assigned role: sre, developer, compliance-officer, legal, security, risk-lead",
    )
    mandatory: bool = Field(
        default=True, description="Whether milestone is mandatory for stage completion"
    )
    estimated_hours: int = Field(default=8, ge=1, le=240, description="Estimated hours to complete")


class CustomStageDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_number: int = Field(..., ge=1, le=6, description="Sequential stage index (1-based)")
    stage_name: str = Field(..., min_length=1, description="Descriptive stage title")
    description: str = Field(default="", description="Stage purpose and operational scope")
    milestones: list[CustomMilestoneDefinition] = Field(
        ..., min_length=1, description="List of discrete milestones for this stage"
    )
    exit_criteria: list[str] = Field(
        ..., min_length=1, description="List of mandatory exit criteria required to pass stage gate"
    )


class CustomPlaybookDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        ..., min_length=1, description="Canonical playbook identifier, e.g. playbook.custom-xyz"
    )
    name: str = Field(..., min_length=1, description="Human-readable title of custom playbook")
    goal: str = Field(
        ..., min_length=1, description="Primary governance objective or regulatory purpose"
    )
    domain: str = Field(
        default="custom", description="Compliance or engineering domain taxonomy tag"
    )
    stages: list[CustomStageDefinition] = Field(
        ..., min_length=2, max_length=6, description="Ordered stages (minimum 2, maximum 6)"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary authoring and versioning metadata"
    )


class PlaybookTemplateResponse(BaseModel):
    template_id: str
    is_valid: bool
    stages_count: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CustomPlaybookListResponse(BaseModel):
    tenant_id: str
    total_count: int
    playbooks: list[CustomPlaybookDefinition]


# --- Hierarchical Structure-Aware Circular Chunking (FEAT-061) ---


class HierarchicalChunkModel(BaseModel):
    chunk_id: UUID = Field(..., description="Unique chunk UUID identifier")
    parent_chunk_id: UUID | None = Field(
        default=None, description="UUID of parent structural clause if nested or proviso"
    )
    ordinal: int = Field(..., ge=0, description="Sequential chunk index in document")
    text: str = Field(..., min_length=1, description="Exact chunk text slice")
    clause_hierarchy: list[str] = Field(
        default_factory=list,
        description="Ordered taxonomy path, e.g. ['Section 2', 'Clause (a)']",
    )
    char_start: int = Field(..., ge=0, description="Inclusive character start index in source text")
    char_end: int = Field(..., gt=0, description="Exclusive character end index in source text")
    token_count: int = Field(
        ..., ge=1, le=512, description="Token count complying with 512 context ceiling"
    )
    is_proviso: bool = Field(
        default=False, description="True if chunk represents or contains a regulatory proviso"
    )
    chunk_type: str = Field(
        default="standard",
        description="Structural type: gazette_header, preamble, section, clause, proviso, schedule, standard",
    )


class ChunkingRequest(BaseModel):
    text: str = Field(..., min_length=100, description="Document raw or cleaned regulatory text")
    max_chunk_tokens: int = Field(default=512, ge=64, le=512)
    min_chunk_tokens: int = Field(default=64, ge=16, le=256)
    preserve_provisos: bool = Field(default=True)
    strategy: str = Field(default="hierarchical")


class ChunkingResponse(BaseModel):
    total_chunks: int
    uncovered_characters: int
    strategy: str
    chunks: list[HierarchicalChunkModel]


# --- High-Fidelity Table Lineage & Matrix Parser (FEAT-062) ---


class ExtractedTable(BaseModel):
    table_id: str = Field(..., description="Unique table identifier")
    page_number: int = Field(default=1, ge=1, description="1-indexed PDF or section page number")
    headers: list[str] = Field(default_factory=list, description="Resolved column headers")
    matrix: list[list[str]] = Field(
        default_factory=list, description="2D matrix of cell string values"
    )
    markdown_repr: str = Field(..., description="GitHub-flavored Markdown table representation")
    json_repr: dict[str, Any] = Field(
        default_factory=dict, description="Structured JSON representation with schema"
    )
    cell_coordinates: list[dict[str, Any]] = Field(
        default_factory=list, description="Optional bounding box coordinates per cell"
    )


class TableParserConfig(BaseModel):
    strategy: Literal["pdfplumber", "docling", "miner_u"] = Field(
        default="pdfplumber", description="Underlying table parsing extraction strategy"
    )
    min_rows: int = Field(default=2, ge=1, description="Minimum rows required to qualify as table")
    min_cols: int = Field(
        default=2, ge=1, description="Minimum columns required to qualify as table"
    )
    merge_multi_headers: bool = Field(
        default=True, description="Whether to merge hierarchical multi-row headers"
    )
    snap_tolerance: float = Field(default=3.0, ge=0.0)
    join_tolerance: float = Field(default=3.0, ge=0.0)


class TableExtractionRequest(BaseModel):
    doc_id: str | None = Field(default=None, description="Optional source document identifier")
    content_base64: str | None = Field(
        default=None, description="Base64 encoded PDF or binary stream"
    )
    text_content: str | None = Field(
        default=None, description="Raw text or ASCII table content for parsing"
    )
    config: TableParserConfig = Field(default_factory=TableParserConfig)


class TableExtractionResponse(BaseModel):
    tables: list[ExtractedTable]
    table_count: int
    total_cells: int
    strategy: str
    processing_time_ms: float


# --- Bidirectional Character-Exact Offset Traceability Matrix (FEAT-063) ---


class ChunkCoordinates(BaseModel):
    chunk_id: UUID = Field(..., description="Target chunk UUID")
    page_number: int = Field(default=1, ge=1, description="1-indexed PDF page number")
    bbox: tuple[float, float, float, float] = Field(
        ..., description="(x0, y0, x1, y1) bounding box in standard 72 DPI points"
    )
    char_start: int = Field(..., ge=0, description="Inclusive character start index")
    char_end: int = Field(..., gt=0, description="Exclusive character end index")


class TraceabilityConfig(BaseModel):
    strict_offset_verification: bool = Field(
        default=True, description="Enforce strict character boundary checks"
    )
    dpi: int = Field(default=72, description="Target PDF render DPI")
    merge_adjacent_words: bool = Field(
        default=True, description="Merge intra-line word boxes into continuous line highlights"
    )


class CoordinateExtractionRequest(BaseModel):
    content_base64: str = Field(..., description="Base64 encoded PDF document")
    char_start: int = Field(..., ge=0, description="Start character offset of highlighted span")
    char_end: int = Field(..., gt=0, description="End character offset of highlighted span")
    chunk_id: UUID | None = Field(default=None, description="Optional chunk identifier")
    config: TraceabilityConfig = Field(default_factory=TraceabilityConfig)


class CoordinateExtractionResponse(BaseModel):
    coordinates: list[ChunkCoordinates]
    total_boxes: int
    page_number: int
    highlight_css: str
    iou_score: float


# --- OCR Degradation & Confidence Scoring Pipeline (FEAT-064) ---


class OCRQualityConfig(BaseModel):
    degradation_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Confidence threshold below which a page is flagged as degraded",
    )
    auto_preprocess: bool = Field(
        default=True,
        description="Automatically apply multi-pass image preprocessing to degraded pages",
    )


class OCRQualityScore(BaseModel):
    page_number: int = Field(default=1, ge=1, description="1-indexed PDF page number")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Overall character confidence score")
    is_degraded: bool = Field(
        ..., description="Whether the page confidence falls below the degradation threshold"
    )
    preprocessing_applied: list[str] = Field(
        default_factory=list,
        description="List of preprocessing transformations applied",
    )
    extracted_text: str = Field(default="", description="Extracted plain text from page")


class OCRQualityRequest(BaseModel):
    content_base64: str = Field(..., description="Base64 encoded PDF page or raster image")
    page_number: int = Field(default=1, ge=1, description="Page number to evaluate")
    config: OCRQualityConfig = Field(default_factory=OCRQualityConfig)


class OCRQualityResponse(BaseModel):
    quality_score: OCRQualityScore
    sha256: str
    processing_time_ms: float


# --- Intelligent Regulatory Furniture & Gazette Stamp Stripper (FEAT-065) ---


class FurnitureConfig(BaseModel):
    strip_gazette_stamps: bool = Field(
        default=True, description="Strip recurring official gazette header stamps"
    )
    strip_page_numbers: bool = Field(
        default=True, description="Strip running page numbers and pagination labels"
    )
    strip_watermarks: bool = Field(
        default=True, description="Strip administrative and confidentiality watermarks"
    )
    strip_printer_signatures: bool = Field(
        default=True, description="Strip government press printer signatures and colophons"
    )
    strip_authority_banners: bool = Field(
        default=True, description="Strip authority publication date lines and registration numbers"
    )


class StrippedFurnitureSummary(BaseModel):
    total_characters_stripped: int = Field(
        ..., ge=0, description="Total characters replaced with spaces"
    )
    total_tokens_stripped: int = Field(
        ..., ge=0, description="Total word tokens eliminated from search index"
    )
    categories_matched: list[str] = Field(
        default_factory=list, description="Furniture categories detected and stripped"
    )


class StripFurnitureRequest(BaseModel):
    text: str = Field(..., description="Raw statutory text extracted from document")
    config: FurnitureConfig = Field(default_factory=FurnitureConfig)


class StripFurnitureResponse(BaseModel):
    cleaned_text: str = Field(..., description="Cleaned text with exact length preservation")
    summary: StrippedFurnitureSummary
    length_preserved: bool = Field(..., description="Whether len(cleaned_text) == len(raw_text)")


# --- Annexure, Schedule & FAQ Relational Association (FEAT-066) ---


SectionType = Literal["MAIN", "ANNEXURE", "SCHEDULE", "FAQ", "APPENDIX"]
RelationshipType = Literal["ANNEXURE", "SCHEDULE", "FAQ", "APPENDIX"]


class DocumentSectionModel(BaseModel):
    section_id: str = Field(..., description="Unique section identifier (UUID)")
    document_id: str | None = Field(default=None, description="Document ID UUID")
    version_id: str | None = Field(default=None, description="Document version UUID")
    section_identifier: str = Field(
        ..., description="Canonical label (e.g. MAIN, Annexure I, Schedule A)"
    )
    section_title: str = Field(default="", description="Detected section heading title")
    section_type: SectionType = Field(..., description="Section category")
    char_start: int = Field(..., ge=0, description="Starting character offset in document")
    char_end: int = Field(..., ge=0, description="Ending character offset in document")
    parent_section_id: str | None = Field(default=None, description="Parent section UUID if nested")


class SectionRelationshipModel(BaseModel):
    parent_section_id: str = Field(..., description="Parent section UUID")
    child_section_id: str = Field(..., description="Child section UUID")
    relationship_type: RelationshipType = Field(..., description="Type of structural link")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Metadata or section attributes"
    )


class AnnexureLinkerConfig(BaseModel):
    auto_link_faqs: bool = Field(
        default=True, description="Automatically link FAQ sections to main body"
    )
    auto_link_annexures: bool = Field(
        default=True, description="Automatically link technical annexures"
    )
    auto_link_schedules: bool = Field(
        default=True, description="Automatically link regulatory schedules"
    )
    auto_link_appendices: bool = Field(default=True, description="Automatically link appendices")


class LinkAnnexuresRequest(BaseModel):
    text: str = Field(..., description="Raw or cleaned document text with headings")
    document_id: str | None = Field(default=None, description="Optional document UUID")
    version_id: str | None = Field(default=None, description="Optional version UUID")
    config: AnnexureLinkerConfig = Field(default_factory=AnnexureLinkerConfig)


class LinkAnnexuresResponse(BaseModel):
    sections: list[DocumentSectionModel] = Field(default_factory=list)
    relationships: list[SectionRelationshipModel] = Field(default_factory=list)
    total_linked: int = Field(..., ge=0, description="Number of relational links established")
    execution_time_ms: float = Field(..., ge=0.0, description="Linking overhead in milliseconds")


class DocumentRelationshipsResponse(BaseModel):
    document_id: str = Field(..., description="Document UUID")
    relationships: list[SectionRelationshipModel] = Field(default_factory=list)


# --- Bilingual Devanagari / Hindi Normalization & Parsing (FEAT-068) ---


class DevanagariNormalizeConfig(BaseModel):
    normalize_nfc: bool = Field(
        default=True, description="Apply canonical Unicode NFC normalization"
    )
    strip_zwj: bool = Field(default=False, description="Strip zero-width joiners and non-joiners")
    clean_orphaned_matras: bool = Field(
        default=True, description="Remove orphaned combining vowel signs"
    )
    separate_bilingual_sections: bool = Field(
        default=True, description="Segment into language-specific sections"
    )


class DevanagariNormalizeRequest(BaseModel):
    text: str = Field(
        ..., min_length=1, description="Raw document text containing Devanagari or English"
    )
    config: DevanagariNormalizeConfig = Field(default_factory=DevanagariNormalizeConfig)


class BilingualSectionModel(BaseModel):
    language: str = Field(..., description="Linguistic classification: hi, en, or mixed")
    text: str = Field(..., description="Section content")
    char_start: int = Field(..., ge=0, description="Start character offset")
    char_end: int = Field(..., ge=0, description="End character offset")
    devanagari_ratio: float = Field(..., ge=0.0, le=1.0, description="Devanagari character density")


class DevanagariNormalizeResponse(BaseModel):
    normalized_text: str = Field(..., description="Normalized Unicode text")
    devanagari_character_count: int = Field(..., ge=0, description="Count of Devanagari characters")
    devanagari_ratio: float = Field(
        ..., ge=0.0, le=1.0, description="Fraction of Devanagari characters"
    )
    sections: list[BilingualSectionModel] = Field(
        default_factory=list, description="Classified sections"
    )
    hindi_column_text: str = Field(default="", description="Extracted Hindi column text stream")
    english_column_text: str = Field(default="", description="Extracted English column text stream")
    latency_ms: float = Field(..., ge=0.0, description="Processing duration in milliseconds")


# --- Automated Regulatory Metadata Extraction (FEAT-069) ---


class MetadataExtractorConfigModel(BaseModel):
    strict_pattern_matching: bool = Field(
        default=True,
        description="Whether strict pattern matching is enforced for regulatory metadata.",
    )


class RegulatoryMetadataExtractRequest(BaseModel):
    text: str = Field(
        ...,
        min_length=100,
        description="Document raw or extracted text (minimum 100 characters).",
    )
    filename: str = Field(
        default="",
        description="Optional source filename for fallback pattern matching.",
    )
    config: MetadataExtractorConfigModel | None = Field(
        default=None,
        description="Optional metadata extractor configuration.",
    )


class RegulatoryMetadataExtractResponse(BaseModel):
    circular_no: str | None = Field(
        default=None,
        description="Authoritative circular or notification reference number.",
    )
    department: str | None = Field(
        default=None,
        description="Authoritative issuing department name.",
    )
    subject: str | None = Field(
        default=None,
        description="Extracted subject line or directive caption.",
    )
    date_issued: date | None = Field(
        default=None,
        description="Official publication or notification issue date.",
    )
    signoff_officer: str | None = Field(
        default=None,
        description="Issuing officer signature name and designation.",
    )
    extracted_fields_count: int = Field(
        default=0,
        description="Total non-null metadata fields extracted.",
    )
