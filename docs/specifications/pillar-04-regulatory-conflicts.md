# Pillar 4 Specification: Regulatory Conflict, Deprecation & Antipattern Auditing
*DocScout Enterprise Regulatory Intelligence Engine*

---

## FEAT-031: Statutory Deprecation & Supersession Engine
- **Objective:** Track superseded circulars, repealed guidelines, and outdated practices using the formal `deprecations` schema from `term-taxonomy.json` (`subject`, `status`, `reason`, `replacement`, `guidance`).
- **In-scope behavior:** Modeling statutory lifecycles in PostgreSQL; marking superseded circular versions; tagging retrieved passages from deprecated circulars with explicit warning banners; preventing silent reliance on dead law.
- **Excluded behavior:** Arbitrary legal interpretation of unadjudicated court stays.
- **Implementation boundaries:** `app/compliance/deprecation_engine.py`, `app/retrieval/search.py`, `migrations/0014_deprecations.up.sql`.
- **Integration points:** Injected into `Passage` model constructor in `app/api/models.py`; surfaced in React UI search result cards.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`deprecations`), `app/compliance/deprecation_engine.py`.
- **Supported inputs:** Document identifier `doc_id: str`, circular number `circular_no: str`, query date `as_of_date: Optional[date]`.
- **Input validation rules:** `doc_id` matches `^doc-[a-z0-9\-]+$`.
- **Output schema:** `DeprecationStatus(is_deprecated: bool, status: str, repealing_circular: Optional[str], reason: Optional[str], guidance: Optional[str])`.
- **Configuration schema:** `DeprecationConfig(warn_on_deprecated: bool = True, exclude_deprecated_from_answers: bool = True)`.
- **Default values:** `warn_on_deprecated = True`, `exclude_deprecated_from_answers = True`.
- **Dependencies:** PostgreSQL table `regulatory_deprecations`.
- **Compatibility requirements:** Fully integrated into existing `Passage` response schema via additive metadata field.
- **Authorization rules:** Available to all authenticated API consumers.
- **Data isolation rules:** Public regulatory supersession metadata.
- **Error behavior:** If deprecation table lookup fails, default to `is_deprecated = False` and log database warning.
- **Fallback behavior:** Passage returned without deprecation warning banner.
- **Observability requirements:** Counter `docscout_deprecated_passages_retrieved_total{doc_id}`, structlog warning.
- **Performance limits:** Deprecation check overhead $\le 0.4\text{ ms}$ per retrieved passage (cached).
- **Resource limits:** In-memory LRU cache $\le 2\text{ MB}$ for active deprecation catalog.
- **Acceptance criteria:** 100% of superseded circulars in test corpus trigger a prominent warning banner citing the repealing Master Direction.
- **Evaluation dataset:** 30 queries specifically targeting known repealed circulars (e.g. legacy Outsourcing guidelines superseded by Master Direction 2023).
- **Evaluation baseline:** 0% deprecation awareness in baseline (silent return of obsolete circulars as current law).
- **Required improvement threshold:** 100% detection and warning rate on superseded circulars.
- **Regression limits:** Zero false-positive deprecation warnings on currently active master directions.
- **Completion criteria:** Passes `tests/test_deprecation_engine.py` with full database integration.

---

## FEAT-032: Circular Clause Conflict Detector
- **Objective:** Automated semantic conflict analyzer comparing newly published circulars with active regulations to pinpoint unacknowledged contradictions, conflicting deadlines, or clashing mandates.
- **In-scope behavior:** Cross-document semantic similarity matching; contradiction classification using cross-encoder NLI model; generating comparative conflict diffs between clashing clauses.
- **Excluded behavior:** Resolving legal precedence automatically without human counsel review.
- **Implementation boundaries:** `app/compliance/conflict_detector.py`, `app/api/admin_conflicts.py`.
- **Integration points:** Ingestion post-discovery worker; Admin API `/v1/admin/conflicts`.
- **Source-of-truth files:** `app/compliance/conflict_detector.py`.
- **Supported inputs:** New circular document `new_doc_id: str`, target corpus sector `sector: str`.
- **Input validation rules:** `new_doc_id` must exist in `documents` table and be fully parsed into chunks.
- **Output schema:** `ConflictReport(conflicts_found: list[CircularConflict(new_clause_span: str, existing_circular_id: str, existing_clause_span: str, contradiction_score: float, conflict_type: Literal["TIMELINE", "THRESHOLD", "MANDATE"])])`.
- **Configuration schema:** `ConflictDetectorConfig(min_contradiction_score: float = 0.82, top_k_candidates: int = 15)`.
- **Default values:** `min_contradiction_score = 0.82`, `top_k_candidates = 15`.
- **Dependencies:** Cross-encoder NLI model (`cross-encoder/nli-deberta-v3-small` or local quantized equivalent).
- **Compatibility requirements:** Asynchronous background worker execution to prevent blocking real-time API.
- **Authorization rules:** Admin-only endpoint requiring `admin:write` Auth0 scope.
- **Data isolation rules:** Strictly internal administrative analysis; isolated staging table.
- **Error behavior:** Worker failure retries up to 3 times with exponential backoff before dead-letter logging.
- **Fallback behavior:** Flags document for manual legal team review.
- **Observability requirements:** Counter `docscout_circular_conflicts_detected_total{conflict_type}`, admin Slack/email webhook alerts.
- **Performance limits:** Conflict scan of a 20-page circular completed in $\le 12.0\text{ seconds}$.
- **Resource limits:** GPU/CPU memory allocation $\le 512\text{ MB}$ during inference.
- **Acceptance criteria:** Detects seeded regulatory contradictions (e.g. conflicting reporting deadlines of 15 days vs 30 days) with $\ge 90\%$ accuracy.
- **Evaluation dataset:** 20 pairs of synthetic regulatory clauses containing 10 explicit contradictions and 10 harmonious updates.
- **Evaluation baseline:** 0% automated conflict analysis in baseline.
- **Required improvement threshold:** Contradiction detection F1-score $\ge 0.88$.
- **Regression limits:** Zero false-positive conflict alarms on standard conforming amendments.
- **Completion criteria:** Verified in `tests/test_conflict_detector.py`.

---

## FEAT-033: Regulatory & Technical Antipattern Scanner
- **Objective:** Scan enterprise compliance manuals and technical architecture documents against the 30 formal antipatterns in `term-taxonomy.json` (e.g., "Checkbox compliance", "Blind retries as flake remedy", "Annual point-in-time pen-testing").
- **In-scope behavior:** Semantic and regex pattern matching of document prose against the 30 antipattern definitions; extracting matching text snippets; outputting regulatory consequence and risk severity.
- **Excluded behavior:** Modifying or auto-editing the user's uploaded policy document.
- **Implementation boundaries:** `app/compliance/antipattern_scanner.py`, `app/api/app.py` (`POST /v1/compliance/audit`).
- **Integration points:** API endpoint `/v1/compliance/audit`; Compliance Audit view in React console.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`antipatterns`), `app/compliance/antipattern_scanner.py`.
- **Supported inputs:** Policy document text `policy_text: str`, optional category filter `category: Optional[str]`.
- **Input validation rules:** `policy_text` length between 50 and 100,000 characters.
- **Output schema:** `AntipatternAuditResponse(findings_count: int, findings: list[AntipatternFinding(practice_name: str, matched_snippet: str, antipattern: str, consequence: str, instead: list[str], severity: str)])`.
- **Configuration schema:** `AntipatternScannerConfig(similarity_threshold: float = 0.78)`.
- **Default values:** `similarity_threshold = 0.78`.
- **Dependencies:** BGE-small embedder for semantic matching, compiled regex patterns for keyword matching.
- **Compatibility requirements:** Stateless execution; standard REST API response.
- **Authorization rules:** Requires authenticated caller with `compliance:audit` scope.
- **Data isolation rules:** Uploaded policy text processed strictly in memory; zero disk persistence.
- **Error behavior:** Unparseable text returns HTTP 422 with descriptive validation error.
- **Fallback behavior:** Returns empty findings list if no antipatterns clear similarity threshold.
- **Observability requirements:** Counter `docscout_antipatterns_detected_total{practice}`, histogram of audit duration.
- **Performance limits:** Audit of a 10,000-word policy document executed in $\le 45\text{ ms}$ p95.
- **Resource limits:** Memory allocation $\le 16\text{ MB}$.
- **Acceptance criteria:** Detects 100% of the 30 taxonomy antipatterns when present in synthetic policy manuals.
- **Evaluation dataset:** 30 synthetic policy excerpts each embedding one specific taxonomy antipattern.
- **Evaluation baseline:** 0% automated antipattern detection in baseline.
- **Required improvement threshold:** Antipattern detection recall $\ge 95\%$, precision $\ge 90\%$.
- **Regression limits:** Zero false-positive alerts on compliant, modern engineering policy text.
- **Completion criteria:** Unit and integration tests pass in `tests/test_antipattern_scanner.py`.

---

## FEAT-034: "Instead-Of" Prescriptive Remediation Engine
- **Objective:** Whenever a compliance antipattern or deprecated practice is detected, automatically output the sanctioned, compliant alternative practices (`instead` array from taxonomy).
- **In-scope behavior:** Mapping detected antipattern findings to their curated replacements; generating prescriptive remediation checklists; linking replacements to canonical circular and standard definitions.
- **Excluded behavior:** Generic, vague advice not anchored in the formal taxonomy.
- **Implementation boundaries:** `app/compliance/remediation_engine.py`.
- **Integration points:** Embedded within `AntipatternAuditResponse` and `DeprecationStatus`.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`antipatterns[].instead`, `deprecations[].replacement`).
- **Supported inputs:** Antipattern ID `antipattern_id: str` or Deprecation ID `deprecation_id: str`.
- **Input validation rules:** Must match valid taxonomy entry.
- **Output schema:** `RemediationPlan(identified_flaw: str, recommended_practices: list[PracticeRecommendation(name: str, definition: str, tier: str, implementation_steps: list[str])])`.
- **Configuration schema:** `RemediationConfig(include_implementation_steps: bool = True)`.
- **Default values:** `include_implementation_steps = True`.
- **Dependencies:** Relational join between `antipatterns` and `taxonomy_terms` tables.
- **Compatibility requirements:** Additive field on audit responses; 100% schema backward compatible.
- **Authorization rules:** Standard audit authorization (`compliance:audit`).
- **Data isolation rules:** Public taxonomy remediation knowledge.
- **Error behavior:** If no replacement mapped, returns empty list with informational log.
- **Fallback behavior:** Returns raw antipattern finding without remediation steps.
- **Observability requirements:** Metric `docscout_remediations_generated_total`.
- **Performance limits:** Remediation lookup $\le 0.5\text{ ms}$.
- **Resource limits:** Zero extra memory overhead.
- **Acceptance criteria:** Every detected antipattern produces at least 1 concrete, actionable replacement practice.
- **Evaluation dataset:** All 30 taxonomy antipatterns and 8 deprecations.
- **Evaluation baseline:** Pure diagnostic error messages without solution pathways.
- **Required improvement threshold:** 100% coverage of remediation mappings across known antipatterns.
- **Regression limits:** Zero broken links to replacement practice terms.
- **Completion criteria:** Verified in `tests/test_remediation_engine.py`.

---

## FEAT-035: Sunset Clause & Mandatory Cutover Alerting
- **Objective:** Ingestion-time extractor for transition windows and sunset dates, generating automated countdown alerts for compliance officers as hard regulatory cutovers approach.
- **In-scope behavior:** Regex and NLP parsing of future effective dates ("with effect from...", "shall transition by..."); storing milestone dates in `regulatory_deadlines` table; background cron job computing remaining days and dispatching webhook/email alerts.
- **Excluded behavior:** Guessing cutover dates when circular text specifies "to be notified separately".
- **Implementation boundaries:** `app/ingest/deadline_extractor.py`, `app/digests/deadline_notifier.py`.
- **Integration points:** Ingestion pipeline; Brevo email digest engine (`app/digests/engine.py`).
- **Source-of-truth files:** `app/ingest/deadline_extractor.py`, `migrations/0014_regulatory_deadlines.up.sql`.
- **Supported inputs:** Document text `text: str`, circular metadata `doc_id: str`.
- **Input validation rules:** `text` non-empty, length $\ge 100$ characters.
- **Output schema:** `list[RegulatoryDeadline(doc_id: str, mandate_description: str, effective_date: date, days_remaining: int, urgency_level: Literal["CRITICAL", "WARNING", "INFO"])]`.
- **Configuration schema:** `DeadlineAlertConfig(critical_threshold_days: int = 15, warning_threshold_days: int = 45)`.
- **Default values:** `critical_threshold_days = 15`, `warning_threshold_days = 45`.
- **Dependencies:** Python `dateutil.parser`, PostgreSQL date comparison queries.
- **Compatibility requirements:** Integrates seamlessly with existing Brevo email digest templates.
- **Authorization rules:** Internal ingestion and digest dispatch execution.
- **Data isolation rules:** Deadlines partitioned by circular; respects tenant subscription settings.
- **Error behavior:** Date parsing failure logs warning and skips ambiguous date strings.
- **Fallback behavior:** Circular indexed without automated calendar deadline alerts.
- **Observability requirements:** Gauge `docscout_upcoming_deadlines_count{urgency}`, counter `docscout_deadline_alerts_sent_total`.
- **Performance limits:** Deadline extraction $\le 2.0\text{ ms}$ per document; daily alert dispatch $\le 5\text{ seconds}$.
- **Resource limits:** Memory footprint $\le 4\text{ MB}$.
- **Acceptance criteria:** Accurately extracts statutory cutover dates from 100% of benchmark transition circulars (e.g. Card-on-File Tokenization cutover, T+1 settlement dates).
- **Evaluation dataset:** 15 transition circulars with explicit cutover dates.
- **Evaluation baseline:** 0% automated cutover calendar tracking in baseline.
- **Required improvement threshold:** Date extraction precision $\ge 95\%$, recall $\ge 90\%$.
- **Regression limits:** Zero false-positive historical dates tagged as future deadlines.
- **Completion criteria:** Unit and email integration tests pass in `tests/test_deadline_extractor.py`.

---

## FEAT-036: Grandfathering & Exemption Scope Engine
- **Objective:** Differentiate circular clauses that apply to existing entities under grandfathering provisions from clauses that apply strictly to new market entrants, preventing costly over-compliance.
- **In-scope behavior:** Semantic classification of grandfathering clauses ("existing entities may continue...", "shall apply to applications received on or after..."); tagging chunks with `applicability_scope: Literal["ALL", "NEW_ENTRANTS_ONLY", "GRANDFATHERED_EXISTING"]`.
- **Excluded behavior:** Determining individual company eligibility without legal entity incorporation records.
- **Implementation boundaries:** `app/ingest/scope_classifier.py`, `app/retrieval/search.py`.
- **Integration points:** Ingestion chunk tagging; `SearchRequest.entity_vintage` filtering.
- **Source-of-truth files:** `app/ingest/scope_classifier.py`, `app/retrieval/types.py`.
- **Supported inputs:** Chunk text `text: str`, optional query filter `entity_vintage: Literal["existing", "new"]`.
- **Input validation rules:** `text` non-empty.
- **Output schema:** `ScopeClassification(scope: str, confidence: float, operative_condition: str)`.
- **Configuration schema:** `ScopeConfig(enabled: bool = True)`.
- **Default values:** `enabled = True`.
- **Dependencies:** Pattern matching and text classification heuristics.
- **Compatibility requirements:** Stores scope tag in PostgreSQL `chunks(applicability_scope)` column.
- **Authorization rules:** Standard search authorization.
- **Data isolation rules:** Public regulatory applicability classifications.
- **Error behavior:** Ambiguous clauses default to `applicability_scope = "ALL"` (fail-safe).
- **Fallback behavior:** Universal applicability applied when scope is uncertain.
- **Observability requirements:** Counter `docscout_grandfathered_clauses_extracted_total`.
- **Performance limits:** Classification overhead $\le 0.5\text{ ms}$ per chunk.
- **Resource limits:** Zero extra memory.
- **Acceptance criteria:** Accurately identifies grandfathering exemptions in 100% of benchmark licensing circulars (e.g. Payment Aggregator net worth transition schedules).
- **Evaluation dataset:** 25 regulatory clauses containing known grandfathering terms.
- **Evaluation baseline:** Flat retrieval treating new-entrant rules as universally binding on existing players.
- **Required improvement threshold:** Grandfathering detection precision $\ge 95\%$.
- **Regression limits:** Zero false-positive grandfathering classifications on strict universal mandates.
- **Completion criteria:** Unit tests pass in `tests/test_scope_classifier.py`.

---

## FEAT-037: Semantic Terminology Drift Tracker
- **Objective:** Track how regulatory definitions drift across circular amendments (e.g. evolving definitions of "Critical IT Infrastructure" or "Significant Beneficial Owner") across time.
- **In-scope behavior:** Computing cosine distance and token diffs between definitions of identical statutory terms across sequential circular versions; alerting when semantic drift exceeds threshold.
- **Excluded behavior:** Semantic drift tracking on casual colloquial terms not formally defined in circulars.
- **Implementation boundaries:** `app/compliance/drift_tracker.py`, `app/api/admin_ontology.py`.
- **Integration points:** Post-ingestion ontology comparison worker; `/v1/admin/ontology/drift/{term_id}`.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`deprecations`), `app/compliance/drift_tracker.py`.
- **Supported inputs:** Target term identifier `term_id: str`.
- **Input validation rules:** `term_id` must exist in `taxonomy_terms`.
- **Output schema:** `TermDriftReport(term_id: str, canonical_term: str, historical_definitions: list[HistoricalDef(version_date: date, doc_id: str, definition_text: str)], semantic_distance_from_origin: float, key_diff_tokens: list[str])`.
- **Configuration schema:** `DriftConfig(alert_threshold_distance: float = 0.25)`.
- **Default values:** `alert_threshold_distance = 0.25`.
- **Dependencies:** BGE-small embedding model for semantic distance calculation.
- **Compatibility requirements:** Pure Python mathematical execution.
- **Authorization rules:** Requires `admin:read` or `compliance:audit` scope.
- **Data isolation rules:** Public statutory definitions.
- **Error behavior:** Term with single definition returns report with `semantic_distance = 0.0`.
- **Fallback behavior:** Returns static single-definition history.
- **Observability requirements:** Metric `docscout_terminology_drifts_flagged_total`.
- **Performance limits:** Drift calculation $\le 5.0\text{ ms}$ per term across 5 historical versions.
- **Resource limits:** Memory footprint $\le 8\text{ MB}$.
- **Acceptance criteria:** Accurately detects and quantifies definition shifts across known revised RBI master directions.
- **Evaluation dataset:** 10 regulatory terms with documented statutory definition changes.
- **Evaluation baseline:** 0% longitudinal definition tracking in baseline.
- **Required improvement threshold:** 100% detection of major definition revisions ($>0.20$ distance).
- **Regression limits:** Zero false-positive drift alarms on identical definitions across reprint gazettes.
- **Completion criteria:** Verified in `tests/test_drift_tracker.py`.

---

## FEAT-038: Enterprise Compliance Debt Register
- **Objective:** Database table, API, and UI console dashboard tracking active compliance exceptions, deprecated procedures, and remediation target dates across the enterprise.
- **In-scope behavior:** CRUD operations for compliance debt items; linking items to specific taxonomy antipatterns or deprecations; tracking remediation owners and target dates; calculating overall institutional debt score.
- **Excluded behavior:** Arbitrary untracked issue management unrelated to regulatory compliance.
- **Implementation boundaries:** `migrations/0014_compliance_debt.up.sql`, `app/compliance/debt_register.py`, `ui/src/components/DebtRegisterView.tsx`.
- **Integration points:** API endpoints `/v1/compliance/debt/*`; React console Compliance tab.
- **Source-of-truth files:** `migrations/0014_compliance_debt.up.sql`, `app/compliance/debt_register.py`.
- **Supported inputs:** `CreateDebtItemRequest(practice_name: str, deprecation_id: Optional[str], antipattern_id: Optional[str], owner_email: str, target_date: date, justification: str)`.
- **Input validation rules:** `owner_email` valid email; `target_date` future date; `justification` min 20 chars.
- **Output schema:** `ComplianceDebtItem(id: UUID, practice_name: str, severity: str, status: Literal["OPEN", "IN_REMEDIATION", "RESOLVED"], target_date: date, created_at: datetime)`.
- **Configuration schema:** `DebtRegisterConfig(allow_overdue_extensions: bool = False)`.
- **Default values:** `allow_overdue_extensions = False`.
- **Dependencies:** PostgreSQL tables `compliance_debt_register` and `audit_log`.
- **Compatibility requirements:** Multi-tenant support with strict `tenant_id` isolation.
- **Authorization rules:** Requires authenticated caller with `compliance:admin` or `compliance:write`.
- **Data isolation rules:** Strictly partitioned by `tenant_id` in PostgreSQL via Row-Level Security (RLS).
- **Error behavior:** Foreign key violation returns HTTP 400 with invalid antipattern/deprecation ID.
- **Fallback behavior:** Returns descriptive validation failure schema.
- **Observability requirements:** Gauge `docscout_open_compliance_debt_items{tenant_id, severity}`.
- **Performance limits:** API CRUD operations $\le 10.0\text{ ms}$ p95.
- **Resource limits:** DB connection pool connection limit $\le 4$.
- **Acceptance criteria:** Full lifecycle tracking (Create -> Assign -> Remediate -> Audit Close) functioning seamlessly in UI.
- **Evaluation dataset:** End-to-end integration test suite covering 20 debt lifecycle transitions.
- **Evaluation baseline:** Zero internal compliance debt tracking in baseline.
- **Required improvement threshold:** 100% adherence to multi-tenant isolation and audit logging.
- **Regression limits:** Zero database deadlock on concurrent status updates.
- **Completion criteria:** Playwright E2E and pytest tests pass in CI.

---

## FEAT-039: Active Circular Temporal Filtering (Point-in-Time Search)
- **Objective:** Add `as_of_date` parameter to search queries, filtering out circulars published after that date and reinstating circulars that were active at that point in time, enabling retroactive audits.
- **In-scope behavior:** Bitemporal filtering in SQL query (`published_date <= as_of_date AND (superseded_date IS NULL OR superseded_date > as_of_date)`); restoring historical ground truth for forensic investigations.
- **Excluded behavior:** Projecting future regulatory states beyond current date.
- **Implementation boundaries:** `app/api/models.py`, `app/retrieval/dense.py`, `app/retrieval/lexical.py`.
- **Integration points:** `SearchRequest.as_of_date` in `app/api/models.py`; SQL query builder.
- **Source-of-truth files:** `app/retrieval/dense.py`, `app/api/models.py`.
- **Supported inputs:** `as_of_date: Optional[datetime.date]`.
- **Input validation rules:** Date string format `YYYY-MM-DD`, between 1990-01-01 and current date.
- **Output schema:** Standard `SearchResponse` representing regulatory state as of the specified date.
- **Configuration schema:** Fully exposed via API request payload.
- **Default values:** `as_of_date = None` (defaults to current active regulations).
- **Dependencies:** PostgreSQL date indexes on `documents(published_date)` and `documents(superseded_date)`.
- **Compatibility requirements:** 100% backward-compatible; omitting date searches current active state.
- **Authorization rules:** Standard search authorization (`search:read`).
- **Data isolation rules:** Public circular corpus history; respects `is_synthetic` isolation.
- **Error behavior:** Future date returns HTTP 422 with "as_of_date cannot be in the future".
- **Fallback behavior:** Defaults to current date if parameter is invalid.
- **Observability requirements:** Log `as_of_date` in structlog; metric `docscout_temporal_queries_total`.
- **Performance limits:** Temporal query execution latency $\le 28.0\text{ ms}$ p95.
- **Resource limits:** Zero extra memory.
- **Acceptance criteria:** When querying for 2018 regulations, returns legacy circulars that were active in 2018 without leaking 2023 Master Directions.
- **Evaluation dataset:** 25 historical regulatory queries pinned to specific audit years (2015, 2018, 2021).
- **Evaluation baseline:** Current baseline returning 2023 regulations regardless of the historical audit period queried.
- **Required improvement threshold:** Historical temporal recall accuracy = 1.000 (zero future leak).
- **Regression limits:** Zero latency impact on standard current-date queries.
- **Completion criteria:** Database query tests pass in `tests/test_temporal_search.py`.

---

## FEAT-040: Regulatory Risk Scorecard Generator
- **Objective:** Automated audit report generator grading an organization's policy documents against DocScout's antipattern, deprecation, and standards catalogs, producing executive-ready PDF/Markdown scorecards.
- **In-scope behavior:** Aggregating antipattern findings, deprecation exposures, and missing mandatory standards; computing institutional risk score (0-100); generating structured PDF/Markdown report with remediation roadmap.
- **Excluded behavior:** Guaranteeing regulatory immunity or legal sign-off.
- **Implementation boundaries:** `app/compliance/scorecard.py`, `app/api/app.py` (`POST /v1/compliance/scorecard`).
- **Integration points:** API endpoint `/v1/compliance/scorecard`; React console Audit Export tab.
- **Source-of-truth files:** `app/compliance/scorecard.py`, `ui/src/components/ScorecardView.tsx`.
- **Supported inputs:** `ScorecardRequest(policy_document_texts: list[str], organization_type: str, include_pdf: bool = False)`.
- **Input validation rules:** At least 1 policy document text $\ge 100$ words; valid organization class.
- **Output schema:** `ScorecardResponse(overall_grade: Literal["A", "B", "C", "D", "F"], numerical_score: float, antipatterns_count: int, deprecations_count: int, critical_risks: list[str], remediation_timeline_days: int, pdf_download_url: Optional[str])`.
- **Configuration schema:** `ScorecardConfig(grading_rubric_weights: dict[str, float])`.
- **Default values:** `grading_rubric_weights = {"antipatterns": 0.4, "deprecations": 0.4, "standards_coverage": 0.2}`.
- **Dependencies:** ReportLab / WeasyPrint for PDF generation, Jinja2 for Markdown rendering.
- **Compatibility requirements:** Generated PDF must be valid PDF/A-1b compliant for long-term audit archiving.
- **Authorization rules:** Requires `compliance:admin` or `audit:export` scope.
- **Data isolation rules:** Scorecard stored in tenant's private audit workspace; encrypted at rest.
- **Error behavior:** Generation failure returns HTTP 500 with correlation ID and transaction rollback.
- **Fallback behavior:** Returns raw JSON scorecard if PDF rendering engine fails.
- **Observability requirements:** Counter `docscout_scorecards_generated_total{grade}`, duration histogram.
- **Performance limits:** Full scorecard and PDF generation completed in $\le 2.5\text{ seconds}$ for 50 pages.
- **Resource limits:** Memory allocation $\le 64\text{ MB}$ during PDF rendering.
- **Acceptance criteria:** Generates executive-ready PDF scorecard with visual risk radar, finding breakdowns, and direct circular citations.
- **Evaluation dataset:** 10 benchmark enterprise policy dossiers with varying levels of compliance maturity.
- **Evaluation baseline:** 0% automated scorecard generation in baseline.
- **Required improvement threshold:** 100% reproducible scoring across identical policy inputs.
- **Regression limits:** Zero memory leaks during repeated PDF generation cycles.
- **Completion criteria:** Verified in `tests/test_scorecard_generator.py`.
