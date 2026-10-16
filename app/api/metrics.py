"""Prometheus instrumentation for the serving API.

RED  -  Rate, Errors, Duration  -  is the framework for a request-driven service, so those
three are what the HTTP metrics here measure. Two RAG-specific signals are added because
they are the ones that actually explain this service's latency: the cache hit ratio and
the per-mode retrieval time.

Cardinality is the thing that kills a Prometheus deployment, so every label here was
enumerated before it was added:

* ``route`` is the **matched route template** (``/v1/search``), never ``request.url.path``.
  Raw paths are the most common cardinality explosion in HTTP services; for this API they
  would be bounded anyway, but a future path parameter would silently turn one series into
  one per value. Unmatched requests collapse to the literal ``"unmatched"`` rather than
  echoing whatever a scanner probed, which would otherwise be an attacker-controlled label.
* ``method`` is bounded by HTTP itself.
* ``status`` is the full code rather than a class. The enumeration is small and known  -
  200, 401, 422, 429, 500  -  and the distinction between 401 and 429 is exactly what an
  operator needs. Collapsing both to ``4xx`` would hide a rate-limited caller behind an
  unauthenticated one.
* ``mode`` is the three values of the retrieval mode literal.

Nothing per-request is a label. Query text, API keys, key fingerprints and request ids are
all absent by construction: that detail belongs in the structured log, which carries the
request id, and the two are joined there rather than in the time-series database.

Bucket boundaries are taken from measurements of this service rather than from a default
ladder, because `histogram_quantile` interpolates inside a bucket and a p95 that lands in a
5s–10s bucket is a meaningless number. Measured on 2 vCPU: cache hit p95 2.11 ms, cold p95
48.11 ms. NFR-1's budget is p95 < 3 s. Buckets are therefore dense below 100 ms, where the
real distribution lives, and place an exact boundary at 3 s so SLO compliance is a bucket
ratio rather than an interpolation.

The default registry is used, which also exposes the ``process_*`` and ``python_*``
collectors. That is correct for one worker and wrong for several  -  a multi-process
deployment needs ``PROMETHEUS_MULTIPROC_DIR``  -  and matches the ``single_process: true``
that ``/healthz`` already reports.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import Lock
from typing import Any

import structlog
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

logger = structlog.get_logger("docscout.metrics")

#: Latency buckets in seconds, sized to the measured distribution and the NFR-1 budget.
#: 0.001-0.005 covers cache hits, 0.01-0.1 covers cold retrieval, 3.0 is the SLO boundary,
#: and 10.0 catches a pathological tail without inventing resolution that does not exist.
LATENCY_BUCKETS = (
    0.001,
    0.0025,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    3.0,
    10.0,
)

#: Label value used when a request matched no route, so a scanner probing random paths
#: cannot create one time series per probe.
UNMATCHED_ROUTE = "unmatched"

REQUESTS = Counter(
    "docscout_http_requests_total",
    "HTTP requests handled, by route, method and status code.",
    ("method", "route", "status"),
)

REQUEST_DURATION = Histogram(
    "docscout_http_request_duration_seconds",
    "End-to-end HTTP request duration in seconds.",
    ("method", "route"),
    buckets=LATENCY_BUCKETS,
)

IN_FLIGHT = Gauge(
    "docscout_http_requests_in_flight",
    "Requests currently being handled. Saturation signal for a single worker.",
)

RETRIEVAL_DURATION = Histogram(
    "docscout_retrieval_duration_seconds",
    "Retrieval time in seconds, excluding HTTP overhead, by mode.",
    ("mode",),
    buckets=LATENCY_BUCKETS,
)

CACHE_EVENTS = Counter(
    "docscout_cache_events_total",
    "Result-cache lookups by outcome. hit/(hit+miss) is the hit ratio.",
    ("result",),
)

CACHE_HITS_TOTAL = Counter(
    "docscout_cache_hits_total",
    "Total search cache hits by tier (tier1, tier2, semantic).",
    ("tier",),
)

CACHE_MISSES_TOTAL = Counter(
    "docscout_cache_misses_total",
    "Total search cache misses across all tiers.",
)

RATE_LIMITED = Counter(
    "docscout_rate_limited_total",
    "Requests rejected by the per-key rate limiter.",
)

GAR_INVOCATIONS = Counter(
    "docscout_gar_invocations_total",
    "Total invocations of Graph-Augmented Retrieval (GAR).",
)

GAR_TRAVERSAL_DURATION = Histogram(
    "docscout_gar_traversal_duration_seconds",
    "Duration of knowledge graph traversals in seconds.",
    buckets=LATENCY_BUCKETS,
)

ENTITIES_LINKED = Counter(
    "docscout_entities_linked_total",
    "Entities linked in user queries by entity type.",
    ("entity_type",),
)

TRI_ARM_FUSIONS = Counter(
    "docscout_tri_arm_fusions_total",
    "Total tri-arm reciprocal rank fusions computed.",
)

CORPUS_CHUNKS = Gauge(
    "docscout_corpus_chunks",
    "Chunks currently retrievable, i.e. belonging to a current document version.",
)

CORPUS_LAST_CHECKED = Gauge(
    "docscout_corpus_last_checked_timestamp_seconds",
    "Unix timestamp when the regulatory corpus was last checked or refreshed.",
)

CORPUS_STALE_HOURS = Gauge(
    "docscout_corpus_stale_hours",
    "Hours elapsed since the regulatory corpus was last checked or refreshed.",
)

CORPUS_STALENESS_BUDGET_HOURS = Gauge(
    "docscout_corpus_staleness_budget_hours",
    "Configured staleness budget in hours before corpus health is degraded.",
)

CORPUS_IS_STALE = Gauge(
    "docscout_corpus_is_stale",
    "1 if elapsed stale hours exceeds the staleness budget, 0 otherwise.",
)

CORPUS_VERSIONS_CURRENT = Gauge(
    "docscout_corpus_versions_current",
    "Count of currently active document versions in the corpus.",
)

CORPUS_VERSIONS_SUPERSEDED = Gauge(
    "docscout_corpus_versions_superseded",
    "Count of superseded document versions retained in the corpus (FR-4).",
)

MANIFEST_CHANGED = Counter(
    "docscout_manifest_changed_total",
    "Count of detected manifest or document changes during corpus refresh.",
)

CACHE_INVALIDATIONS = Counter(
    "docscout_cache_invalidations_total",
    "Count of cache invalidation events triggered on supersession or admin action.",
    ("reason",),
)
CACHE_INVALIDATIONS_TOTAL = CACHE_INVALIDATIONS

AGENT_RESEARCH_TOTAL = Counter(
    "docscout_agent_research_total",
    "Research requests executed by the agent loop.",
    ("status",),
)

AGENT_RESEARCH_DURATION = Histogram(
    "docscout_agent_research_duration_seconds",
    "End-to-end research agent execution time in seconds.",
    buckets=LATENCY_BUCKETS,
)

CORPUS_GENERATION = Gauge(
    "docscout_corpus_generation",
    "Monotonically increasing corpus generation counter for the in-memory cache and indices.",
)

RETRIEVAL_AUDITS = Counter(
    "docscout_retrieval_audits_total",
    "Count of durable retrieval audit log entries recorded.",
    ("status",),
)

CITATIONS_EXTRACTED_TOTAL = Counter(
    "docscout_citations_extracted_total",
    "Total circular citations extracted from regulatory documents.",
)

UNRESOLVED_CITATIONS_TOTAL = Gauge(
    "docscout_unresolved_citations_total",
    "Current count of extracted citations not resolved to an internal document ID.",
)

RELATIONSHIP_QUERIES_TOTAL = Counter(
    "docscout_relationship_queries_total",
    "Count of search queries filtered by relationship (FEAT-008).",
    ("relation",),
)

CENTRALITY_BOOSTED_QUERIES_TOTAL = Counter(
    "docscout_centrality_boosted_queries_total",
    "Count of search queries where graph degree centrality boosting was applied (FEAT-009).",
    ("query_type",),
)

ONTOLOGY_CANDIDATES_DISCOVERED = Counter(
    "docscout_ontology_candidates_discovered_total",
    "Total regulatory terms discovered and staged for ontology inclusion (FEAT-010).",
)

ONTOLOGY_CANDIDATES_REVIEWED = Counter(
    "docscout_ontology_candidates_reviewed_total",
    "Total ontology candidate terms reviewed by human administrators (FEAT-010).",
    ("action",),
)

TOKENS_DISAMBIGUATED_TOTAL = Counter(
    "docscout_tokens_disambiguated_total",
    "Count of polysemous tokens disambiguated pre-retrieval (FEAT-011).",
    ("token", "resolved_sense"),
)

DISAMBIGUATION_LATENCY = Histogram(
    "docscout_disambiguation_latency_seconds",
    "Latency of query token disambiguation in seconds (FEAT-011).",
    buckets=LATENCY_BUCKETS,
)

ACRONYMS_EXPANDED_TOTAL = Counter(
    "docscout_acronyms_expanded_total",
    "Count of acronyms expanded in search queries (FEAT-012).",
    ("acronym",),
)

QUERIES_BY_INTENT_TOTAL = Counter(
    "docscout_queries_by_intent_total",
    "Count of queries classified by diagnostic intent (FEAT-013).",
    ("intent_id",),
)

INTENT_ROUTING_LATENCY = Histogram(
    "docscout_intent_routing_latency_seconds",
    "Latency of query diagnostic intent routing in seconds (FEAT-013).",
    buckets=LATENCY_BUCKETS,
)

HYDE_INVOCATIONS_TOTAL = Counter(
    "docscout_hyde_invocations_total",
    "Count of HyDE hypothetical passage generations (FEAT-014).",
)

HYDE_GENERATION_SECONDS = Histogram(
    "docscout_hyde_generation_seconds",
    "Latency of HyDE hypothetical passage generation in seconds (FEAT-014).",
    buckets=LATENCY_BUCKETS,
)

TAGS_EXTRACTED_TOTAL = Counter(
    "docscout_tags_extracted_total",
    "Count of taxonomy domain tags extracted from search queries (FEAT-016).",
    ("tag",),
)

COREFERENCES_RESOLVED_TOTAL = Counter(
    "docscout_coreferences_resolved_total",
    "Count of coreference resolutions in multi-turn chat (FEAT-017).",
    ("status",),
)

TYPOS_CORRECTED_TOTAL = Counter(
    "docscout_typos_corrected_total",
    "Count of typos corrected in search queries (FEAT-018).",
    ("term",),
)

SUGGESTIONS_TOTAL = Counter(
    "docscout_suggestions_total",
    "Count of search query suggestion requests (FEAT-019).",
    ("has_suggestions",),
)

SUGGESTION_LATENCY = Histogram(
    "docscout_suggestion_latency_seconds",
    "Latency of search query suggestion generation in seconds (FEAT-019).",
    buckets=LATENCY_BUCKETS,
)

PERSONA_QUERIES_TOTAL = Counter(
    "docscout_persona_queries_total",
    "Count of search queries evaluated under specific persona profiles (FEAT-020).",
    ("persona_id",),
)

FORMULAS_CALCULATED_TOTAL = Counter(
    "docscout_formulas_calculated_total",
    "Count of compliance formulas evaluated (FEAT-021).",
    ("formula_id",),
)

FORMULA_CALC_LATENCY = Histogram(
    "docscout_formula_calc_latency_seconds",
    "Latency of formula evaluations in seconds (FEAT-021).",
    ("formula_id",),
    buckets=LATENCY_BUCKETS,
)

FORMULAS_EXTRACTED_TOTAL = Counter(
    "docscout_formulas_extracted_total",
    "Count of statutory mathematical formulas extracted from documents (FEAT-022).",
)

DOCUMENTS_WITH_FORMULAS_TOTAL = Gauge(
    "docscout_documents_with_formulas_total",
    "Count of ingested documents containing extracted compliance formulas (FEAT-022).",
)

VALIDATIONS_PERFORMED_TOTAL = Counter(
    "docscout_validations_performed_total",
    "Count of statutory boundary validations performed (FEAT-023).",
    ("status",),
)

BOUNDARY_BREACHES_TOTAL = Counter(
    "docscout_boundary_breaches_total",
    "Count of statutory boundary breaches detected (FEAT-023).",
    ("ratio_name",),
)

SIMULATION_REQUESTS_TOTAL = Counter(
    "docscout_simulation_requests_total",
    "Count of compliance what-if sensitivity simulations executed (FEAT-024).",
    ("formula_id",),
)

SIMULATION_DURATION_SECONDS = Histogram(
    "docscout_simulation_duration_seconds",
    "Latency of sensitivity simulations in seconds (FEAT-024).",
    ("formula_id",),
    buckets=LATENCY_BUCKETS,
)

STANDARD_FORMULA_LINKS_TOTAL = Counter(
    "docscout_standard_formula_links_total",
    "Total formulas linked to regulatory standards (FEAT-025).",
    ("standard_id", "status"),
)

STANDARD_LINKING_DURATION_SECONDS = Histogram(
    "docscout_standard_linking_duration_seconds",
    "Latency of standard formula linking in seconds (FEAT-025).",
    buckets=[0.0001, 0.0005, 0.001, 0.005, 0.01],
)

STATUTORY_PARAMETERS_EXTRACTED_TOTAL = Counter(
    "docscout_statutory_parameters_extracted_total",
    "Total statutory quantitative parameters extracted from circulars (FEAT-026).",
    ("parameter_type", "normalized_unit"),
)

STATUTORY_EXTRACTION_DURATION_SECONDS = Histogram(
    "docscout_statutory_extraction_duration_seconds",
    "Latency of quantitative regulatory parameter extraction in seconds (FEAT-026).",
    buckets=[0.0005, 0.001, 0.005, 0.01, 0.05, 0.1],
)

CONSISTENCY_AUDITS_TOTAL = Counter(
    "docscout_consistency_audits_total",
    "Total mathematical sanity and consistency audits performed (FEAT-027).",
    ("return_code", "status"),
)

CONSISTENCY_ANOMALIES_DETECTED_TOTAL = Counter(
    "docscout_consistency_anomalies_detected_total",
    "Total mathematical and consistency anomalies flagged (FEAT-027).",
    ("anomaly_type", "severity"),
)

CONSISTENCY_AUDIT_DURATION_SECONDS = Histogram(
    "docscout_consistency_audit_duration_seconds",
    "Latency of mathematical sanity auditing in seconds (FEAT-027).",
    buckets=[0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05],
)

UNIT_NORMALIZATIONS_TOTAL = Counter(
    "docscout_unit_normalizations_total",
    "Total financial unit normalizations executed (FEAT-028).",
    ("currency", "scale"),
)

UNIT_EQUIVALENCE_CHECKS_TOTAL = Counter(
    "docscout_unit_equivalence_checks_total",
    "Total unit equivalence comparisons performed (FEAT-028).",
    ("result",),
)

UNIT_NORMALIZATION_DURATION_SECONDS = Histogram(
    "docscout_unit_normalization_duration_seconds",
    "Latency of unit normalization in seconds (FEAT-028).",
    buckets=[0.00005, 0.0001, 0.0005, 0.001, 0.005],
)

DEPENDENCY_GRAPHS_BUILT_TOTAL = Counter(
    "docscout_dependency_graphs_built_total",
    "Total formula dependency graphs constructed (FEAT-029).",
    ("domain",),
)

GRAPH_EVALUATIONS_TOTAL = Counter(
    "docscout_graph_evaluations_total",
    "Total multi-stage formula graph cascade evaluations executed (FEAT-029).",
    ("graph_id", "status"),
)

GRAPH_BUILD_DURATION_SECONDS = Histogram(
    "docscout_graph_build_duration_seconds",
    "Latency of dependency graph construction in seconds (FEAT-029).",
    buckets=[0.0001, 0.0005, 0.001, 0.005, 0.01],
)

FORMULA_VERSIONS_RESOLVED_TOTAL = Counter(
    "docscout_formula_versions_resolved_total",
    "Total historical formula resolutions performed (FEAT-030).",
    ("formula_id", "status"),
)

FORMULA_VERSION_DIFFS_TOTAL = Counter(
    "docscout_formula_version_diffs_total",
    "Total formula version comparison diffs executed (FEAT-030).",
    ("change_type",),
)

VERSION_RESOLUTION_DURATION_SECONDS = Histogram(
    "docscout_version_resolution_duration_seconds",
    "Latency of historical formula resolution in seconds (FEAT-030).",
    buckets=[0.00005, 0.0001, 0.0005, 0.001, 0.005],
)

STATUTORY_DEPRECATIONS_CHECKED_TOTAL = Counter(
    "docscout_statutory_deprecations_checked_total",
    "Total statutory text deprecation checks executed (FEAT-031).",
    ("has_findings",),
)

STATUTORY_DEPRECATIONS_DETECTED_TOTAL = Counter(
    "docscout_statutory_deprecations_detected_total",
    "Total deprecated items detected in documents by severity (FEAT-031).",
    ("regulator", "severity"),
)

DEPRECATION_SCAN_DURATION_SECONDS = Histogram(
    "docscout_deprecation_scan_duration_seconds",
    "Latency of deprecation and supersession text scanning in seconds (FEAT-031).",
    buckets=[0.0001, 0.0005, 0.001, 0.005, 0.02],
)

SUPERSESSION_CHAINS_RESOLVED_TOTAL = Counter(
    "docscout_supersession_chains_resolved_total",
    "Total circular supersession chains resolved (FEAT-031).",
    ("root_instrument",),
)

CIRCULAR_CONFLICTS_CHECKED_TOTAL = Counter(
    "docscout_circular_conflicts_checked_total",
    "Total clause conflict scans executed (FEAT-032).",
    ("has_conflicts",),
)

CIRCULAR_CONFLICTS_DETECTED_TOTAL = Counter(
    "docscout_circular_conflicts_detected_total",
    "Total inter-circular conflicts detected by type and severity (FEAT-032).",
    ("conflict_type", "severity"),
)

CONFLICT_SCAN_DURATION_SECONDS = Histogram(
    "docscout_conflict_scan_duration_seconds",
    "Latency of pairwise clause conflict scanning in seconds (FEAT-032).",
    buckets=[0.0001, 0.0005, 0.001, 0.005, 0.02],
)

ANTIPATTERN_SCANS_TOTAL = Counter(
    "docscout_antipattern_scans_total",
    "Total antipattern document scans executed (FEAT-033).",
    ("has_findings",),
)

ANTIPATTERNS_DETECTED_TOTAL = Counter(
    "docscout_antipatterns_detected_total",
    "Total technical and regulatory antipatterns detected by domain and severity (FEAT-033).",
    ("domain", "severity"),
)

ANTIPATTERN_SCAN_DURATION_SECONDS = Histogram(
    "docscout_antipattern_scan_duration_seconds",
    "Latency of antipattern document scanning in seconds (FEAT-033).",
    buckets=[0.0001, 0.0005, 0.001, 0.005, 0.02],
)

REMEDIATIONS_GENERATED_TOTAL = Counter(
    "docscout_remediations_generated_total",
    "Total prescriptive remediations generated (FEAT-034).",
    ("flaw_type", "has_remediation"),
)

REMEDIATION_LOOKUP_DURATION_SECONDS = Histogram(
    "docscout_remediation_lookup_duration_seconds",
    "Latency of prescriptive remediation lookups in seconds (FEAT-034).",
    buckets=[0.0001, 0.0003, 0.0005, 0.001, 0.005],
)

UPCOMING_DEADLINES_COUNT = Gauge(
    "docscout_upcoming_deadlines_count",
    "Current count of upcoming regulatory deadlines by urgency level (FEAT-035).",
    ("urgency",),
)

DEADLINE_ALERTS_SENT_TOTAL = Counter(
    "docscout_deadline_alerts_sent_total",
    "Total regulatory cutover and deadline alerts dispatched (FEAT-035).",
    ("channel", "urgency"),
)

DEADLINE_EXTRACTION_DURATION_SECONDS = Histogram(
    "docscout_deadline_extraction_duration_seconds",
    "Latency of transition deadline and cutover extraction in seconds (FEAT-035).",
    buckets=[0.0001, 0.0005, 0.001, 0.002, 0.005],
)

GRANDFATHERED_CLAUSES_EXTRACTED_TOTAL = Counter(
    "docscout_grandfathered_clauses_extracted_total",
    "Total regulatory clauses classified as grandfathered exemptions (FEAT-036).",
    ("scope",),
)

SCOPE_CLASSIFICATION_DURATION_SECONDS = Histogram(
    "docscout_scope_classification_duration_seconds",
    "Latency of chunk grandfathering and exemption scope classification in seconds (FEAT-036).",
    buckets=[0.00005, 0.0001, 0.0002, 0.0005, 0.001],
)

TERMINOLOGY_DRIFTS_FLAGGED_TOTAL = Counter(
    "docscout_terminology_drifts_flagged_total",
    "Total regulatory terms flagged with significant semantic drift across circular versions (FEAT-037).",
)

OPEN_COMPLIANCE_DEBT_ITEMS = Gauge(
    "docscout_open_compliance_debt_items",
    "Current count of active compliance debt items by tenant and severity (FEAT-038).",
    ("tenant_id", "severity"),
)

TEMPORAL_QUERIES_TOTAL = Counter(
    "docscout_temporal_queries_total",
    "Total point-in-time search queries executed with as_of_date filtering (FEAT-039).",
)

SCORECARDS_GENERATED_TOTAL = Counter(
    "docscout_scorecards_generated_total",
    "Total audit risk scorecards generated by executive grade (FEAT-040).",
    ("grade",),
)

SCORECARD_DURATION_SECONDS = Histogram(
    "docscout_scorecard_duration_seconds",
    "End-to-end latency of compliance scorecard generation in seconds (FEAT-040).",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

STANDARDS_QUERIED_TOTAL = Counter(
    "docscout_standards_queried_total",
    "Total standards queries performed by standard ID (FEAT-041).",
    ("standard_id",),
)

STANDARDS_QUERY_DURATION_SECONDS = Histogram(
    "docscout_standards_query_duration_seconds",
    "Lookup duration of standards queries in seconds (FEAT-041).",
    buckets=[0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1],
)

CROSSWALK_QUERIES_TOTAL = Counter(
    "docscout_crosswalk_queries_total",
    "Total cross-framework control mapping queries (FEAT-042).",
    ("source", "target"),
)

CROSSWALK_QUERY_DURATION_SECONDS = Histogram(
    "docscout_crosswalk_query_duration_seconds",
    "Query execution latency for cross-framework control mapping in seconds (FEAT-042).",
    buckets=[0.0005, 0.001, 0.002, 0.0035, 0.005, 0.01, 0.025],
)

HARMONIZATIONS_PERFORMED_TOTAL = Counter(
    "docscout_harmonizations_performed_total",
    "Total multi-jurisdiction compliance harmonizations performed (FEAT-043).",
    ("delta_classification", "topic"),
)

HARMONIZATION_DURATION_SECONDS = Histogram(
    "docscout_harmonization_duration_seconds",
    "Latency of harmonization analysis in seconds (FEAT-043).",
    buckets=[0.001, 0.005, 0.01, 0.02, 0.05, 0.1],
)

STANDARD_CONSTRAINED_QUERIES_TOTAL = Counter(
    "docscout_standard_constrained_queries_total",
    "Total search queries constrained by a standard or framework filter (FEAT-044).",
    ("standard",),
)

STANDARD_MENTIONS_EXTRACTED_TOTAL = Counter(
    "docscout_standard_mentions_extracted_total",
    "Total external standard mentions extracted from regulatory text (FEAT-046).",
    ("standard_id",),
)

AUDIT_PACKAGES_EXPORTED_TOTAL = Counter(
    "docscout_audit_packages_exported_total",
    "Total audit evidence packages exported by format (FEAT-047).",
    ("format",),
)

AUDIT_PACKAGE_EXPORT_DURATION_SECONDS = Histogram(
    "docscout_audit_package_export_duration_seconds",
    "End-to-end latency of audit package export generation in seconds (FEAT-047).",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 3.0],
)

TELEMETRY_EVENTS_INGESTED_TOTAL = Counter(
    "docscout_telemetry_events_ingested_total",
    "Total continuous compliance telemetry events ingested by check result (FEAT-048).",
    ("check_result",),
)

TELEMETRY_WINDOW_CALC_DURATION_SECONDS = Histogram(
    "docscout_telemetry_window_calc_duration_seconds",
    "Latency of continuous compliance observation window calculation in seconds (FEAT-048).",
    buckets=[0.0005, 0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25],
)

VENDOR_CONTRACTS_AUDITED_TOTAL = Counter(
    "docscout_vendor_contracts_audited_total",
    "Total third-party vendor contracts evaluated by overall risk level (FEAT-049).",
    ("risk_level",),
)

VENDOR_AUDIT_DURATION_SECONDS = Histogram(
    "docscout_vendor_audit_duration_seconds",
    "Latency of vendor contract statutory risk evaluation in seconds (FEAT-049).",
    buckets=[0.005, 0.01, 0.02, 0.04, 0.06, 0.1, 0.25, 0.5],
)

ALGO_ASSESSMENTS_COMPLETED_TOTAL = Counter(
    "docscout_algo_assessments_completed_total",
    "Total algorithmic and AI impact assessments completed by model type and status (FEAT-050).",
    ("model_type", "status"),
)

ALGO_ASSESSMENT_DURATION_SECONDS = Histogram(
    "docscout_algo_assessment_duration_seconds",
    "Latency of algorithmic impact assessment evaluation in seconds (FEAT-050).",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5],
)

PLAYBOOK_RUNS_STARTED_TOTAL = Counter(
    "docscout_playbook_runs_started_total",
    "Total playbook workflow runs instantiated by playbook_id (FEAT-051).",
    ("playbook_id",),
)

ACTIVE_PLAYBOOKS_COUNT = Gauge(
    "docscout_active_playbooks_count",
    "Total currently active compliance playbooks by domain (FEAT-051).",
    ("domain",),
)

PLAYBOOK_STAGE_TRANSITIONS_TOTAL = Counter(
    "docscout_playbook_stage_transitions_total",
    "Total playbook stage promotions by outcome (FEAT-051).",
    ("playbook_id", "outcome"),
)

MILESTONES_COMPLETED_TOTAL = Counter(
    "docscout_milestones_completed_total",
    "Total statutory playbook milestones marked complete by playbook_id and stage (FEAT-052).",
    ("playbook_id", "stage"),
)

STAGE_PROMOTIONS_ATTEMPTED_TOTAL = Counter(
    "docscout_stage_promotions_attempted_total",
    "Total playbook stage promotion attempts by validation status (FEAT-053).",
    ("status",),
)

TASKS_DISPATCHED_TOTAL = Counter(
    "docscout_tasks_dispatched_total",
    "Total playbook tasks dispatched or routed by statutory taxonomy role (FEAT-054).",
    ("role",),
)

ACTIVE_CRISIS_INCIDENTS = Gauge(
    "docscout_active_crisis_incidents",
    "Current count of active regulatory cyber crisis incidents (FEAT-055).",
)

INCIDENT_MILESTONES_MET_TOTAL = Counter(
    "docscout_incident_milestones_met_total",
    "Total regulatory incident action items or milestones completed (FEAT-055).",
)

RELEASES_CERTIFIED_TOTAL = Counter(
    "docscout_releases_certified_total",
    "Total release candidate verification decisions by status (FEAT-056).",
    ("status",),
)

PQC_READINESS_SCORE = Gauge(
    "docscout_pqc_readiness_score",
    "Post-quantum cryptographic readiness score percentage (FEAT-057).",
    ("tenant_id",),
)

PQC_ASSETS_INVENTORIED_TOTAL = Counter(
    "docscout_pqc_assets_inventoried_total",
    "Total cryptographic endpoint assets inventoried by classification (FEAT-057).",
    ("classification",),
)

DORA_ASSESSMENTS_COMPLETED_TOTAL = Counter(
    "docscout_dora_assessments_completed_total",
    "Total DORA operational resilience assessments executed (FEAT-058).",
    ("tenant_id",),
)

RESILIENCE_TESTS_RECORDED_TOTAL = Counter(
    "docscout_resilience_tests_recorded_total",
    "Total operational resilience stress tests logged by outcome (FEAT-058).",
    ("status",),
)

CUSTOM_PLAYBOOKS_CREATED_TOTAL = Counter(
    "docscout_custom_playbooks_created_total",
    "Total custom compliance playbooks authored and validated (FEAT-060).",
    ("tenant_id",),
)

CHUNKS_CREATED_TOTAL = Counter(
    "docscout_chunks_created_total",
    "Total document chunks created across strategies (FEAT-061).",
    ("strategy",),
)

CHUNK_TOKEN_COUNT = Histogram(
    "docscout_chunk_token_count",
    "Token count distribution of ingested chunks (FEAT-061).",
    buckets=(16, 32, 64, 128, 256, 384, 512),
)

TABLES_EXTRACTED_TOTAL = Counter(
    "docscout_tables_extracted_total",
    "Total tables extracted from documents (FEAT-062).",
    ("strategy", "status"),
)

TABLE_EXTRACTION_DURATION_SECONDS = Histogram(
    "docscout_table_extraction_duration_seconds",
    "Duration of table extraction in seconds (FEAT-062).",
    ("strategy",),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

COORDINATE_MAPPINGS_CREATED_TOTAL = Counter(
    "docscout_coordinate_mappings_created_total",
    "Total chunk coordinate mappings created (FEAT-063).",
    ("status",),
)

OCR_MEAN_PAGE_CONFIDENCE = Gauge(
    "docscout_ocr_mean_page_confidence",
    "Average confidence score of processed OCR pages (FEAT-064).",
)

OCR_DEGRADED_PAGES_ROUTED_TOTAL = Counter(
    "docscout_ocr_degraded_pages_routed_total",
    "Total degraded OCR pages routed to preprocessing and fallback OCR (FEAT-064).",
    ("status",),
)

FURNITURE_TOKENS_STRIPPED_TOTAL = Counter(
    "docscout_furniture_tokens_stripped_total",
    "Total furniture tokens stripped from regulatory texts (FEAT-065).",
)

ANNEXURES_LINKED_TOTAL = Counter(
    "docscout_annexures_linked_total",
    "Total regulatory annexures, schedules, and FAQs linked by relationship type (FEAT-066).",
    ["type"],
)

CHUNKS_REUSED_TOTAL = Counter(
    "docscout_chunks_reused_total",
    "Total unchanged chunks reused during incremental circular re-ingestion (FEAT-067).",
)

DEVANAGARI_CHARACTERS_NORMALIZED_TOTAL = Counter(
    "docscout_devanagari_characters_normalized_total",
    "Total Unicode Devanagari characters normalized during ingestion (FEAT-068).",
)

METADATA_FIELDS_EXTRACTED_TOTAL = Counter(
    "docscout_metadata_fields_extracted_total",
    "Total regulatory metadata fields extracted into structured columns (FEAT-069).",
    ["field_name"],
)

DUPLICATE_DOCUMENTS_DETECTED_TOTAL = Counter(
    "docscout_duplicate_documents_detected_total",
    "Total duplicate documents and circular reprints detected during ingestion (FEAT-070).",
    ["match_type"],
)

RERANK_DURATION_SECONDS = Histogram(
    "docscout_rerank_duration_seconds",
    "Duration of cross-encoder candidate reranking in seconds (FEAT-071).",
    buckets=[0.005, 0.010, 0.020, 0.030, 0.040, 0.050, 0.075, 0.100, 0.200],
)

RERANK_CIRCUIT_BREAKER_TRIPS_TOTAL = Counter(
    "docscout_rerank_circuit_breaker_trips_total",
    "Total times the cross-encoder rerank circuit breaker tripped due to timeout or error (FEAT-071).",
)

CONTEXT_TOKEN_UTILIZATION_RATIO = Gauge(
    "docscout_context_token_utilization_ratio",
    "Ratio of packed context tokens to maximum budget ceiling (FEAT-073).",
)

CONTEXT_PACKS_COMPLETED_TOTAL = Counter(
    "docscout_context_packs_completed_total",
    "Total context packing runs completed (FEAT-073).",
    ["status"],
)

ARM_LEADERS_ANCHORED_TOTAL = Counter(
    "docscout_arm_leaders_anchored_total",
    "Total times an arm top-1 leader was anchored into final results (FEAT-074).",
    ["arm_name"],
)

SECTION_EXPANSIONS_TOTAL = Counter(
    "docscout_section_expansions_total",
    "Total section-aware context window expansions performed (FEAT-075).",
    ["status"],
)

SECTION_EXPANSION_DURATION_SECONDS = Histogram(
    "docscout_section_expansion_duration_seconds",
    "Duration of section-aware context window expansion in seconds (FEAT-075).",
    buckets=[0.0005, 0.001, 0.002, 0.0025, 0.005, 0.01, 0.025],
)

CROSS_LINGUAL_QUERIES_TOTAL = Counter(
    "docscout_cross_lingual_queries_total",
    "Total cross-lingual queries processed by language (FEAT-076).",
    ["lang"],
)

ABSTENTION_EVENTS_TOTAL = Counter(
    "docscout_abstention_events_total",
    "Total abstention gate events by confidence level (FEAT-077).",
    ["level"],
)

CONFIDENCE_SCORES = Histogram(
    "docscout_confidence_scores",
    "Distribution of evidence coverage confidence scores (FEAT-077).",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.65, 0.7, 0.8, 0.85, 0.9, 1.0],
)

SPANS_HIGHLIGHTED_TOTAL = Counter(
    "docscout_spans_highlighted_total",
    "Total count of sub-sentence evidence spans highlighted (FEAT-078).",
    ["source"],
)

MEAN_ANSWER_FAITHFULNESS_SCORE = Gauge(
    "docscout_mean_answer_faithfulness_score",
    "Running mean faithfulness score of generated regulatory answers (FEAT-081).",
)

UNFAITHFUL_ANSWERS_REJECTED_TOTAL = Counter(
    "docscout_unfaithful_answers_rejected_total",
    "Total generated answers rejected due to unfaithful or hallucinated claims (FEAT-081).",
)

CITATIONS_VALIDATED_TOTAL = Counter(
    "docscout_citations_validated_total",
    "Total citations validated by status (valid, invalid, ungrounded, sanitized) (FEAT-082).",
    ("status",),
)

SECURITY_THREATS_BLOCKED_TOTAL = Counter(
    "docscout_security_threats_blocked_total",
    "Total adversarial security threats and prompt injections blocked (FEAT-083).",
    ("threat_type",),
)

CANARY_AUDIT_RUNS_TOTAL = Counter(
    "docscout_canary_audit_runs_total",
    "Total canary token leakage assertion runs (FEAT-084).",
)

CANARY_LEAKAGE_DETECTED = Gauge(
    "docscout_canary_leakage_detected",
    "Binary indicator of canary leakage detection in production responses (FEAT-084).",
)

EVAL_ECE_SCORE = Gauge(
    "docscout_eval_ece_score",
    "Expected Calibration Error (ECE) of retrieval confidence scores (FEAT-085).",
)

CLAIM_SUPPORT_RATIO = Gauge(
    "docscout_claim_support_ratio",
    "Real-time ratio of supported claims to total claims across served responses (FEAT-089).",
)

UNSUPPORTED_CLAIM_ALERTS = Gauge(
    "docscout_unsupported_claim_alerts",
    "Current status of unsupported claim alert (1 = firing, 0 = normal) (FEAT-089).",
    ["severity"],
)

UNSUPPORTED_CLAIM_ALERTS_TOTAL = Counter(
    "docscout_unsupported_claim_alarm_events_total",
    "Total alarms triggered when supported claim ratio drops below threshold (FEAT-089).",
    ["severity"],
)

TOTAL_CLAIMS_EVALUATED_TOTAL = Counter(
    "docscout_claims_evaluated_total",
    "Total factual claims evaluated for grounding across served responses (FEAT-089).",
    ["status"],
)

CANARY_EVALUATIONS_TOTAL = Counter(
    "docscout_canary_evaluations_total",
    "Total automated canary analysis deployment evaluations (FEAT-091).",
    ["decision"],
)


def record_canary_evaluation(decision: str) -> None:
    """Record an automated canary analysis deployment evaluation (FEAT-091)."""
    CANARY_EVALUATIONS_TOTAL.labels(decision=decision).inc()


ERROR_BUDGET_REMAINING_RATIO = Gauge(
    "docscout_error_budget_remaining_ratio",
    "Remaining 30-day error budget ratio [0.0, 1.0] (FEAT-092).",
    ["slo"],
)

ERROR_BUDGET_BURN_RATE = Gauge(
    "docscout_error_budget_burn_rate",
    "Error budget burn rate multiplier across observation window (FEAT-092).",
    ["window"],
)

ERROR_BUDGET_DEPLOYMENT_FROZEN = Gauge(
    "docscout_error_budget_deployment_frozen",
    "Binary indicator: 1 if deployments are frozen due to consumed error budget, 0 otherwise (FEAT-092).",
)


def update_error_budget_metrics(
    budget_remaining_ratio: float,
    burn_rate_1h: float,
    burn_rate_6h: float,
    is_frozen: bool,
    slo: str = "availability",
) -> None:
    """Update Prometheus error budget gauges (FEAT-092)."""
    ERROR_BUDGET_REMAINING_RATIO.labels(slo=slo).set(max(0.0, min(1.0, budget_remaining_ratio)))
    ERROR_BUDGET_BURN_RATE.labels(window="1h").set(max(0.0, burn_rate_1h))
    ERROR_BUDGET_BURN_RATE.labels(window="6h").set(max(0.0, burn_rate_6h))
    ERROR_BUDGET_DEPLOYMENT_FROZEN.set(1.0 if is_frozen else 0.0)


BULKHEAD_ACTIVE_CONCURRENCY = Gauge(
    "docscout_bulkhead_active_concurrency",
    "Active requests currently executing per bulkhead pool (FEAT-093).",
    ["pool"],
)

BULKHEAD_QUEUE_DEPTH = Gauge(
    "docscout_bulkhead_queue_depth",
    "Queued requests waiting for admission per bulkhead pool (FEAT-093).",
    ["pool"],
)

BULKHEAD_SHED_REQUESTS_TOTAL = Counter(
    "docscout_bulkhead_shed_requests_total",
    "Total requests shed due to bulkhead saturation or latency breach (FEAT-093).",
    ["pool", "reason"],
)


def record_bulkhead_admission(pool: str, active: int, queued: int) -> None:
    """Record active concurrency and queued depth for a bulkhead pool (FEAT-093)."""
    BULKHEAD_ACTIVE_CONCURRENCY.labels(pool=pool).set(active)
    BULKHEAD_QUEUE_DEPTH.labels(pool=pool).set(queued)


def record_bulkhead_shed(pool: str, reason: str = "queue_wait_timeout") -> None:
    """Record a shed request under adaptive load shedding (FEAT-093)."""
    BULKHEAD_SHED_REQUESTS_TOTAL.labels(pool=pool, reason=reason).inc()


# Initialize AI assurance gauges to healthy defaults so Prometheus scrapers see them immediately
CLAIM_SUPPORT_RATIO.set(1.0)
UNSUPPORTED_CLAIM_ALERTS.labels(severity="critical").set(0.0)
ERROR_BUDGET_REMAINING_RATIO.labels(slo="availability").set(1.0)
ERROR_BUDGET_REMAINING_RATIO.labels(slo="latency").set(1.0)
ERROR_BUDGET_BURN_RATE.labels(window="1h").set(0.0)
ERROR_BUDGET_BURN_RATE.labels(window="6h").set(0.0)
ERROR_BUDGET_DEPLOYMENT_FROZEN.set(0.0)
ABSTENTION_EVENTS_TOTAL.labels(level="LOW")
ABSTENTION_EVENTS_TOTAL.labels(level="MEDIUM")
ABSTENTION_EVENTS_TOTAL.labels(level="HIGH")

for _p in ("query", "ingest", "eval", "internal"):
    BULKHEAD_ACTIVE_CONCURRENCY.labels(pool=_p).set(0.0)
    BULKHEAD_QUEUE_DEPTH.labels(pool=_p).set(0.0)


@dataclass
class ClaimObservation:
    timestamp: float
    supported: int
    total: int


class HallucinationTelemetryTracker:
    """Thread-safe real-time rolling window tracker for claim support ratio and alarms (FEAT-089)."""

    def __init__(
        self,
        window_seconds: float = 300.0,
        alarm_threshold: float = 0.98,
        min_claims_for_alert: int = 1,
    ) -> None:
        self.window_seconds = window_seconds
        self.alarm_threshold = alarm_threshold
        self.min_claims_for_alert = min_claims_for_alert
        self._lock = Lock()
        self._observations: deque[ClaimObservation] = deque(maxlen=20000)
        self._running_supported: int = 0
        self._running_total: int = 0
        self._alert_active: bool = False
        self._alert_listeners: list[Callable[[float, float, int], None]] = []

    def add_alert_listener(self, listener: Callable[[float, float, int], None]) -> None:
        """Register callback invoked whenever alarm fires."""
        with self._lock:
            self._alert_listeners.append(listener)

    def reset(self) -> None:
        """Reset observations for testing."""
        with self._lock:
            self._observations.clear()
            self._running_supported = 0
            self._running_total = 0
            self._alert_active = False
            CLAIM_SUPPORT_RATIO.set(1.0)
            UNSUPPORTED_CLAIM_ALERTS.labels(severity="critical").set(0.0)

    def record_claim_evaluation(
        self,
        supported_claims: int,
        total_claims: int,
        timestamp: float | None = None,
    ) -> float:
        """Record a claim evaluation outcome and update telemetry gauges and alarms.

        Overhead is <= 0.02 ms. Fail-open on any exception.
        """
        if total_claims < 0 or supported_claims < 0:
            return 1.0

        now = time.time() if timestamp is None else timestamp
        with self._lock:
            self._observations.append(
                ClaimObservation(timestamp=now, supported=supported_claims, total=total_claims)
            )
            self._running_supported += supported_claims
            self._running_total += total_claims

            # Evict entries outside the sliding window
            cutoff = now - self.window_seconds
            while self._observations and self._observations[0].timestamp < cutoff:
                evicted = self._observations.popleft()
                self._running_supported = max(0, self._running_supported - evicted.supported)
                self._running_total = max(0, self._running_total - evicted.total)

            window_supported = self._running_supported
            window_total = self._running_total

            ratio = (window_supported / window_total) if window_total > 0 else 1.0
            ratio = round(ratio, 4)

            CLAIM_SUPPORT_RATIO.set(ratio)
            TOTAL_CLAIMS_EVALUATED_TOTAL.labels(status="supported").inc(supported_claims)
            unsupported = max(0, total_claims - supported_claims)
            if unsupported > 0:
                TOTAL_CLAIMS_EVALUATED_TOTAL.labels(status="unsupported").inc(unsupported)

            is_breached = window_total >= self.min_claims_for_alert and ratio < self.alarm_threshold
            if is_breached:
                if not self._alert_active:
                    self._alert_active = True
                    UNSUPPORTED_CLAIM_ALERTS_TOTAL.labels(severity="critical").inc()
                UNSUPPORTED_CLAIM_ALERTS.labels(severity="critical").set(1.0)
                listeners = list(self._alert_listeners)
            else:
                self._alert_active = False
                UNSUPPORTED_CLAIM_ALERTS.labels(severity="critical").set(0.0)
                listeners = []

        for listener in listeners:
            try:
                listener(ratio, self.alarm_threshold, window_total)
            except Exception as exc:
                logger.debug("telemetry.listener_error", error=str(exc))

        return ratio

    def get_current_ratio(self) -> float:
        with self._lock:
            return (
                (self._running_supported / self._running_total) if self._running_total > 0 else 1.0
            )

    def is_alerting(self) -> bool:
        with self._lock:
            return self._alert_active


_TELEMETRY_TRACKER: HallucinationTelemetryTracker | None = None


def get_telemetry_tracker() -> HallucinationTelemetryTracker:
    global _TELEMETRY_TRACKER
    if _TELEMETRY_TRACKER is None:
        from app.config import metrics_config

        cfg = metrics_config()
        _TELEMETRY_TRACKER = HallucinationTelemetryTracker(
            window_seconds=cfg.hallucination_alarm_window_seconds,
            alarm_threshold=cfg.hallucination_alarm_threshold,
        )
    return _TELEMETRY_TRACKER


def record_claim_telemetry(supported_claims: int, total_claims: int) -> float:
    """Public fail-open entry point to record operational claim evaluation telemetry (FEAT-089)."""
    try:
        from app.config import metrics_config

        cfg = metrics_config()
        if not cfg.enable_ai_assurance_metrics:
            return 1.0
        return get_telemetry_tracker().record_claim_evaluation(supported_claims, total_claims)
    except Exception as exc:
        logger.warning("metrics.claim_telemetry_failed", error=str(exc))
        return 1.0


ATTESTATIONS_VERIFIED_TOTAL = Counter(
    "docscout_attestations_verified_total",
    "Total SLSA cryptographic attestations verified at startup or ingest",
    ["status"],
)

AUTH_SUCCESSES_TOTAL = Counter(
    "docscout_auth_successes_total",
    "Total successful authentications partitioned by scope",
    ["scope"],
)

AUTH_FAILURES_TOTAL = Counter(
    "docscout_auth_failures_total",
    "Total authentication failures partitioned by failure reason",
    ["reason"],
)

QUERY_COST_USD_TOTAL = Counter(
    "docscout_query_cost_usd_total",
    "Total computed query and inference cost in USD",
    ["tenant_id", "cache_outcome"],
)

QUERY_TOKENS_TOTAL = Counter(
    "docscout_query_tokens_total",
    "Total tokens processed across queries and passages",
    ["tenant_id", "cache_outcome"],
)


def route_label(request_scope: Mapping[str, Any]) -> str:
    """The matched route template, or a fixed placeholder.

    Starlette puts the matched ``APIRoute`` in the ASGI scope once routing has run. Its
    ``path`` is the template (``/v1/search``), which is what keeps this label bounded.

    Typed as a Mapping rather than a dict because that is what the ASGI scope actually is;
    narrowing it to dict made mypy reject every real call site.
    """
    route = request_scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else UNMATCHED_ROUTE


def render() -> tuple[bytes, str]:
    """Serialise the default registry. Returns (body, content type)."""
    return generate_latest(), CONTENT_TYPE_LATEST
