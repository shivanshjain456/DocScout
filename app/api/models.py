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
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

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
