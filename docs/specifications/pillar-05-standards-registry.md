# Pillar 5 Specification: Multi-Standard Cross-Walk & Governance Registry
*DocScout Enterprise Regulatory Intelligence Engine*

---

## FEAT-041: Unified Standards Registry & Authority Engine
- **Objective:** Ingest and index all 53 standards from `term-taxonomy.json.standardsRegistry` (ISO 27001, NIST SP 800-53, PCI-DSS 4.0, SOC 2, EU DORA, NIS2, DO-178C, FedRAMP, RBI Master Directions) into a unified relational authority database.
- **In-scope behavior:** Modeling standards, governing bodies, domains, control families, and statutory hierarchies; exposing standard metadata via REST API; linking standard controls to ingested circular clauses.
- **Excluded behavior:** Ingesting proprietary full-text copyrighted standard books without open-metadata license.
- **Implementation boundaries:** `migrations/0014_standards_registry.up.sql`, `app/compliance/standards_registry.py`, `app/api/app.py` (`GET /v1/standards`).
- **Integration points:** API endpoint `/v1/standards`; OpenAPI specification; search filter integration.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`standardsRegistry`), `app/compliance/standards_registry.py`.
- **Supported inputs:** Standard ID `standard_id: str`, domain filter `domain: Optional[str]`.
- **Input validation rules:** `standard_id` must match known standard identifier pattern `^[A-Z0-9\-\.\/ ]+$`.
- **Output schema:** `StandardMetadata(id: str, name: str, body: str, domain: str, note: str, control_count: int, mapped_circulars_count: int)`.
- **Configuration schema:** `StandardsConfig(auto_sync_registry: bool = True)`.
- **Default values:** `auto_sync_registry = True`.
- **Dependencies:** PostgreSQL table `standards_registry`.
- **Compatibility requirements:** Fully relational PostgreSQL design with GIN index on `control_families` JSONB.
- **Authorization rules:** Publicly readable for all authenticated callers (`search:read`).
- **Data isolation rules:** Public standards metadata only; completely stateless.
- **Error behavior:** Unrecognized standard ID returns HTTP 404 with list of available standard IDs.
- **Fallback behavior:** Returns standard error details per RFC-7807.
- **Observability requirements:** Counter `docscout_standards_queried_total{standard_id}`, route duration tracking.
- **Performance limits:** Lookup latency $\le 1.0\text{ ms}$ p95.
- **Resource limits:** Memory allocation $\le 4\text{ MB}$ for in-memory standards index.
- **Acceptance criteria:** 100% of the 53 standards from `term-taxonomy.json` successfully queryable with verified control schemas.
- **Evaluation dataset:** All 53 taxonomy standards.
- **Evaluation baseline:** 0% standards registry capability in baseline.
- **Required improvement threshold:** 100% data fidelity against `term-taxonomy.json.standardsRegistry`.
- **Regression limits:** Zero database migration errors across native and containerized databases.
- **Completion criteria:** Database migration applied and verified in `tests/test_standards_registry.py`.

---

## FEAT-042: Cross-Framework Control Mapping Matrix
- **Objective:** Establish bidirectional mapping between RBI/SEBI technical circular clauses and global security frameworks (e.g. mapping RBI Master Direction on Cyber Security Section 4.2 to NIST CSF PR.AC and ISO 27001 A.9).
- **In-scope behavior:** Mapping table joining statutory circular clauses with equivalent ISO/NIST controls; computing framework coverage percentages; allowing callers to query: "What RBI circular clause fulfills ISO 27001 A.12.1.2?"
- **Excluded behavior:** Arbitrary speculative mapping of non-security clauses.
- **Implementation boundaries:** `app/compliance/control_mapper.py`, `app/api/app.py` (`GET /v1/standards/crosswalk`).
- **Integration points:** API endpoint `/v1/standards/crosswalk`; UI Crosswalk viewer.
- **Source-of-truth files:** `app/compliance/control_mapper.py`, `do not commit!/term-taxonomy.json` (`standardsRegistry`).
- **Supported inputs:** `source_framework: str`, `target_framework: str`, `control_id: Optional[str]`.
- **Input validation rules:** Framework strings must exist in `standards_registry`.
- **Output schema:** `CrosswalkResponse(source_control: str, target_controls: list[MappedControl(framework: str, control_id: str, title: str, equivalence_level: Literal["EXACT", "SUBSET", "SUPERSET"])], citation_spans: list[str])`.
- **Configuration schema:** `CrosswalkConfig(cache_ttl_seconds: int = 86400)`.
- **Default values:** `cache_ttl_seconds = 86400`.
- **Dependencies:** Relational mapping table `framework_control_crosswalk`.
- **Compatibility requirements:** Sub-5ms database join response.
- **Authorization rules:** Requires authenticated caller with `compliance:read`.
- **Data isolation rules:** Public governance cross-walk data.
- **Error behavior:** Unmapped control returns HTTP 200 with empty mapping list `[]` and "No direct mapping established".
- **Fallback behavior:** Returns empty mapping rather than false positive links.
- **Observability requirements:** Counter `docscout_crosswalk_queries_total{source, target}`.
- **Performance limits:** Query execution latency $\le 3.5\text{ ms}$ p95.
- **Resource limits:** Database index size $\le 10\text{ MB}$.
- **Acceptance criteria:** Successfully maps 100% of core cybersecurity controls between RBI Cyber Security Framework, ISO 27001:2022, and NIST CSF 2.0.
- **Evaluation dataset:** 50 benchmark cybersecurity controls evaluated across all 3 frameworks.
- **Evaluation baseline:** 0% cross-framework mapping in baseline (requiring manual spreadsheet cross-referencing).
- **Required improvement threshold:** Mapping accuracy $\ge 98\%$ verified against regulatory harmonization standards.
- **Regression limits:** Zero database foreign key violations.
- **Completion criteria:** Passes `tests/test_control_mapper.py`.

---

## FEAT-043: Multi-Jurisdiction Compliance Harmonizer
- **Objective:** Comparative analysis engine identifying where Indian regulations impose stricter obligations than international baselines (e.g., local data localization mandates vs GDPR transfer rules; 6-hour incident reporting vs 72 hours).
- **In-scope behavior:** Comparative semantic analysis between regulatory frameworks; tagging statutory deltas as `STRICTER`, `EQUIVALENT`, or `LENIENT`; highlighting unique local statutory carve-outs.
- **Excluded behavior:** Automated legal opinion generation on cross-border litigation.
- **Implementation boundaries:** `app/compliance/harmonizer.py`, `app/api/app.py`.
- **Integration points:** API endpoint `/v1/compliance/harmonize`; UI Harmonizer tab.
- **Source-of-truth files:** `app/compliance/harmonizer.py`.
- **Supported inputs:** `HarmonizeRequest(topic: str, jurisdiction_a: str, jurisdiction_b: str)`.
- **Input validation rules:** `jurisdiction_a` and `jurisdiction_b` must be valid jurisdiction codes (e.g. `IN_RBI`, `EU_DORA`, `US_NIST`).
- **Output schema:** `HarmonizationReport(topic: str, jurisdiction_a: str, jurisdiction_b: str, delta_classification: Literal["STRICTER_A", "EQUIVALENT", "STRICTER_B"], comparative_analysis: str, localized_mandates: list[str])`.
- **Configuration schema:** `HarmonizerConfig(min_confidence: float = 0.85)`.
- **Default values:** `min_confidence = 0.85`.
- **Dependencies:** BGE-small embeddings, comparative prompt templates.
- **Compatibility requirements:** Stateless REST API execution.
- **Authorization rules:** Requires caller with `compliance:read`.
- **Data isolation rules:** Public regulatory texts only.
- **Error behavior:** Unknown jurisdiction returns HTTP 422 with supported jurisdiction catalog.
- **Fallback behavior:** Returns standard RFC-7807 error.
- **Observability requirements:** Counter `docscout_harmonizations_performed_total`.
- **Performance limits:** Comparative analysis latency $\le 20.0\text{ ms}$ for cached/indexed topics.
- **Resource limits:** Memory allocation $\le 8\text{ MB}$.
- **Acceptance criteria:** Accurately highlights RBI's strict 6-hour cyber incident reporting window compared to GDPR's 72-hour window.
- **Evaluation dataset:** 10 major compliance topics compared between RBI, EU DORA, and US FedRAMP.
- **Evaluation baseline:** 0% multi-jurisdiction harmonization in baseline.
- **Required improvement threshold:** 100% accuracy on identifying stricter local statutory requirements.
- **Regression limits:** Zero false claims of regulatory equivalence where statutory mandates differ.
- **Completion criteria:** Verified in `tests/test_harmonizer.py`.

---

## FEAT-044: Standard-Constrained Search API Filtering
- **Objective:** Allow callers of `POST /v1/search` to specify `filter.standard="PCI DSS 4.0"` or `filter.framework="NIST SP 800-53"`, constraining retrieval to circulars and guidance mapped to that standard.
- **In-scope behavior:** SQL `JOIN` on `framework_control_crosswalk` during vector and BM25 candidate generation; enforcing strict framework boundary isolation in retrieval results.
- **Excluded behavior:** Arbitrary un-indexed text filtering that bypasses the standards registry.
- **Implementation boundaries:** `app/api/models.py`, `app/retrieval/dense.py`, `app/retrieval/lexical.py`.
- **Integration points:** `SearchRequest.filter.standard` in `app/api/models.py`; `POST /v1/search`.
- **Source-of-truth files:** `app/api/models.py`, `app/retrieval/types.py`.
- **Supported inputs:** `filter.standard: Optional[str]` matching an ID in `standards_registry`.
- **Input validation rules:** Must match registered standard ID pattern or be `None`.
- **Output schema:** Standard `SearchResponse` containing only chunks verified to fulfill the specified standard.
- **Configuration schema:** Fully exposed via `SearchRequest` payload.
- **Default values:** `filter.standard = None` (unconstrained search).
- **Dependencies:** PostgreSQL index on `framework_control_crosswalk(standard_id, chunk_id)`.
- **Compatibility requirements:** 100% backward-compatible with existing search requests.
- **Authorization rules:** Standard search authorization (`search:read`).
- **Data isolation rules:** Standard filtering respects `is_synthetic` isolation.
- **Error behavior:** Unrecognized standard ID returns HTTP 422 with catalog of known standards.
- **Fallback behavior:** If standard join yields zero results, returns empty list with confidence 0.0.
- **Observability requirements:** Log `filter_standard` in structlog; metric `docscout_standard_constrained_queries_total{standard}`.
- **Performance limits:** Filtered query latency $\le 22.0\text{ ms}$ p95.
- **Resource limits:** DB join buffer $\le 8\text{ MB}$.
- **Acceptance criteria:** All returned passages map directly to the specified standard with 100% precision.
- **Evaluation dataset:** 30 standard-constrained test queries across PCI-DSS, SOC-2, and ISO 27001.
- **Evaluation baseline:** General search returning mixed cross-framework passages without standard grounding.
- **Required improvement threshold:** Standard filter precision = 1.000.
- **Regression limits:** Zero latency impact on unconstrained standard searches.
- **Completion criteria:** Unit tests pass in `tests/test_api_search.py`.

---

## FEAT-045: Regulatory Authority Hierarchy Resolver
- **Objective:** Encode statutory legal precedence: Constitution > Parliamentary Acts (PMLA, RBI Act) > Master Directions > Circulars > Guidelines > Press Releases / FAQs, resolving conflicting mandates automatically.
- **In-scope behavior:** Ingestion tagging of document authority tier (Tiers 1 to 5); ranking multiplier prioritizing higher-tier statutory instruments over subordinate FAQs during conflicting queries.
- **Excluded behavior:** Automatically declaring lower-tier administrative circulars void without judicial ruling.
- **Implementation boundaries:** `app/retrieval/authority.py`, `app/retrieval/search.py`.
- **Integration points:** Scoring phase in `Retriever.retrieve()`.
- **Source-of-truth files:** `app/retrieval/authority.py`, `corpus/raw/manifest.json`.
- **Supported inputs:** Ingested document metadata `document_class: str`.
- **Input validation rules:** `document_class` must be one of `{"ACT", "MASTER_DIRECTION", "CIRCULAR", "GUIDELINE", "FAQ"}`.
- **Output schema:** `AuthorityWeight(tier: int, boost_multiplier: float)`.
- **Configuration schema:** `AuthorityConfig(tier_multipliers: dict[str, float])`.
- **Default values:** `tier_multipliers = {"ACT": 1.25, "MASTER_DIRECTION": 1.15, "CIRCULAR": 1.05, "GUIDELINE": 1.0, "FAQ": 0.85}`.
- **Dependencies:** PostgreSQL column `documents(authority_tier)`.
- **Compatibility requirements:** Pure mathematical weight adjustment; monotonic score preservation.
- **Authorization rules:** Internal retrieval engine component.
- **Data isolation rules:** Public statutory authority hierarchy.
- **Error behavior:** Unknown document class defaults to neutral weight $1.0\times$.
- **Fallback behavior:** Standard unweighted fusion.
- **Observability requirements:** Log `applied_authority_tier` on top retrieved passages.
- **Performance limits:** Weight multiplication overhead $\le 0.05\text{ ms}$.
- **Resource limits:** Zero extra memory.
- **Acceptance criteria:** When statutory acts and informal FAQs discuss the same topic, the Master Direction/Act ranks higher $\ge 95\%$ of the time.
- **Evaluation dataset:** 20 queries targeting topics with both Master Direction rules and informal FAQ commentary.
- **Evaluation baseline:** Flat retrieval where informal FAQs frequently outranked formal Master Directions.
- **Required improvement threshold:** Authoritative source top-1 rank rate $\ge 95\%$.
- **Regression limits:** FAQs must still be retrievable when user explicitly queries for operational guidance.
- **Completion criteria:** Verified in `tests/test_authority_ranking.py`.

---

## FEAT-046: ISO/NIST Clause Cross-Citation Hyperlinking
- **Objective:** Detect mentions of external international standards in circular text (e.g. "as per ISO/IEC 27001 standard") and inject interactive links to the standard's control specification in DocScout.
- **In-scope behavior:** Ingestion-time entity extraction of standard mentions; creating relational links; rendering interactive badges in the React console document viewer.
- **Excluded behavior:** Modifying raw underlying circular text strings.
- **Implementation boundaries:** `app/ingest/standard_mention_extractor.py`, `ui/src/components/DocumentReader.tsx`.
- **Integration points:** Ingestion extraction chain; React console document reader.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`standardsRegistry`), `ui/src/components/DocumentReader.tsx`.
- **Supported inputs:** Circular text `text: str`, `doc_id: str`.
- **Input validation rules:** `text` non-empty.
- **Output schema:** `list[StandardMention(span: tuple[int, int], raw_text: str, standard_id: str, control_hint: Optional[str])]`.
- **Configuration schema:** `StandardMentionConfig(enabled: bool = True)`.
- **Default values:** `enabled = True`.
- **Dependencies:** Regex entity extractor, React router for deep linking.
- **Compatibility requirements:** Accessible client-side deep links (`/standards/{standard_id}`).
- **Authorization rules:** Available to all authenticated users.
- **Data isolation rules:** Public standards metadata.
- **Error behavior:** Extraction failure logs warning and displays text without hyperlinks.
- **Fallback behavior:** Clean unannotated text display.
- **Observability requirements:** Counter `docscout_standard_mentions_extracted_total{standard_id}`.
- **Performance limits:** Client-side link rendering $\le 2.0\text{ ms}$ for 20-page document view.
- **Resource limits:** Zero extra memory overhead.
- **Acceptance criteria:** Automatically hyperlinks 100% of explicit ISO, NIST, and PCI-DSS mentions across RBI circulars.
- **Evaluation dataset:** 10 circulars containing documented external standard references.
- **Evaluation baseline:** Static, non-interactive text strings requiring manual lookup.
- **Required improvement threshold:** Link detection precision $\ge 98\%$.
- **Regression limits:** Zero broken client-side hyperlinks.
- **Completion criteria:** Playwright E2E test `tests_e2e/test_standard_links.spec.ts` passes.

---

## FEAT-047: Audit Evidence Package Exporter
- **Objective:** One-click export bundling retrieved circular clauses, timestamped citations, applied control mappings, and cryptographic hashes into an audit-ready PDF/ZIP dossier.
- **In-scope behavior:** Bundling search results or workspace artifacts; compiling executive summary, clause verbatim quotes, and SHA-256 provenance hashes; generating signed PDF/ZIP download.
- **Excluded behavior:** Modifying or manipulating cited text spans.
- **Implementation boundaries:** `app/compliance/exporter.py`, `app/api/app.py` (`POST /v1/compliance/export-evidence`).
- **Integration points:** API endpoint `/v1/compliance/export-evidence`; Export button in React search console.
- **Source-of-truth files:** `app/compliance/exporter.py`, `ui/src/components/ExportModal.tsx`.
- **Supported inputs:** `ExportEvidenceRequest(query: str, passage_ids: list[str], format: Literal["PDF", "ZIP", "MARKDOWN"], audit_reference_id: str)`.
- **Input validation rules:** $1 \le \text{len}(passage_ids) \le 50$; valid audit reference string.
- **Output schema:** `ExportResponse(download_url: str, file_sha256: str, expires_at: datetime, items_included: int)`.
- **Configuration schema:** `ExporterConfig(download_expiry_minutes: int = 60, enable_digital_signature: bool = True)`.
- **Default values:** `download_expiry_minutes = 60`, `enable_digital_signature = True`.
- **Dependencies:** WeasyPrint / ReportLab, zipfile, cryptography for digital signature.
- **Compatibility requirements:** Conforms to ISO 19005-1 (PDF/A) for long-term document archiving.
- **Authorization rules:** Requires authenticated caller with `audit:export` scope.
- **Data isolation rules:** Packages generated in tenant's isolated temporary storage and purged after expiry.
- **Error behavior:** Export failure returns HTTP 500 with error log and cleans up temporary files.
- **Fallback behavior:** Returns raw Markdown export if PDF rendering engine times out.
- **Observability requirements:** Counter `docscout_audit_packages_exported_total{format}`, duration histogram.
- **Performance limits:** Package generation completed in $\le 3.0\text{ seconds}$ for 50 passages.
- **Resource limits:** Memory allocation $\le 128\text{ MB}$ during PDF compilation.
- **Acceptance criteria:** Produces professional, court-admissible audit dossier with verified cryptographic hash stamps.
- **Evaluation dataset:** 10 simulated audit requests with multi-clause evidence sets.
- **Evaluation baseline:** 0% automated evidence export capability in baseline.
- **Required improvement threshold:** 100% SHA-256 provenance integrity match on exported artifacts.
- **Regression limits:** Zero disk accumulation of expired export files.
- **Completion criteria:** Verified in `tests/test_audit_exporter.py`.

---

## FEAT-048: Continuous Compliance Observation Window Tracker
- **Objective:** Replaces point-in-time penetration testing (deprecated in `term-taxonomy.json`) with continuous compliance logging and scheduled telemetry gathering across the audit period.
- **In-scope behavior:** Ingestion of continuous security and operational telemetry; calculating compliance operating window; generating timestamped evidence trails for SOC-2 Type II and PCI-DSS 4.0 audits.
- **Excluded behavior:** Modifying telemetry timestamps or retroactively injecting logs.
- **Implementation boundaries:** `migrations/0014_compliance_telemetry.up.sql`, `app/compliance/observation_tracker.py`.
- **Integration points:** API endpoint `POST /v1/compliance/telemetry/ingest`; Observation Window dashboard.
- **Source-of-truth files:** `app/compliance/observation_tracker.py`, `migrations/0014_compliance_telemetry.up.sql`.
- **Supported inputs:** `TelemetryBatch(tenant_id: str, control_id: str, observation_timestamp: datetime, check_result: Literal["PASS", "FAIL"], evidence_hash: str)`.
- **Input validation rules:** `observation_timestamp` must be within last 24 hours (prevents back-dating); valid control ID.
- **Output schema:** `ObservationStatus(control_id: str, observation_window_days: int, compliance_percentage: float, unbroken_streak_days: int)`.
- **Configuration schema:** `ObservationConfig(min_window_days: int = 90)`.
- **Default values:** `min_window_days = 90` (standard 3-month audit observation window).
- **Dependencies:** PostgreSQL timeseries partitioned table `compliance_telemetry_events`.
- **Compatibility requirements:** Sub-millisecond telemetry ingestion.
- **Authorization rules:** Requires `telemetry:write` API key.
- **Data isolation rules:** Strictly partitioned by `tenant_id` via PostgreSQL Row-Level Security.
- **Error behavior:** Schema validation failure returns HTTP 422 and rejects invalid telemetry batch.
- **Fallback behavior:** Telemetry rejected with audit log entry.
- **Observability requirements:** Counter `docscout_telemetry_events_ingested_total{check_result}`.
- **Performance limits:** Ingestion throughput $\ge 1,000\text{ events/sec}$.
- **Resource limits:** Database table auto-partitioned monthly.
- **Acceptance criteria:** Accurately maintains observation window statistics satisfying PCI-DSS 4.0 continuous evidence mandates.
- **Evaluation dataset:** 10,000 simulated continuous compliance telemetry events across 90 days.
- **Evaluation baseline:** Deprecated annual point-in-time checklists.
- **Required improvement threshold:** 100% timestamped audit trail integrity across 90-day window.
- **Regression limits:** Zero database performance degradation on search path.
- **Completion criteria:** Database and API tests pass in `tests/test_observation_tracker.py`.

---

## FEAT-049: Third-Party Vendor Risk Assessment Engine
- **Objective:** Evaluate SaaS and IT vendor contracts against RBI Outsourcing Guidelines and SEBI Cloud Framework mandates, identifying missing audit rights and offshore data risks.
- **In-scope behavior:** Parsing uploaded vendor contracts; checking for required statutory clauses (e.g. RBI audit access rights, Indian data localization, business continuity testing, sub-contracting approval); flagging non-compliant clauses.
- **Excluded behavior:** Auto-signing or modifying legal vendor contracts.
- **Implementation boundaries:** `app/compliance/vendor_risk.py`, `app/api/app.py` (`POST /v1/compliance/vendor-audit`).
- **Integration points:** API endpoint `/v1/compliance/vendor-audit`; UI Vendor Risk tab.
- **Source-of-truth files:** `app/compliance/vendor_risk.py`.
- **Supported inputs:** Vendor contract text `contract_text: str`, vendor category `vendor_type: Literal["CLOUD", "SAAS", "PAYMENT_SWITCH", "DATACENTER"]`.
- **Input validation rules:** `contract_text` length between 100 and 150,000 characters.
- **Output schema:** `VendorRiskReport(compliance_score: float, mandatory_clauses_present: list[str], missing_clauses: list[MissingClause(clause_name: str, statutory_requirement: str, rbi_circular_citation: str, risk_level: str)])`.
- **Configuration schema:** `VendorRiskConfig(strict_localization: bool = True)`.
- **Default values:** `strict_localization = True`.
- **Dependencies:** BGE-small embedding model, statutory clause checklist.
- **Compatibility requirements:** Stateless REST API execution.
- **Authorization rules:** Requires `compliance:audit` or `compliance:admin` scope.
- **Data isolation rules:** Contract text processed in-memory; zero disk retention.
- **Error behavior:** Parse failure returns HTTP 422 with descriptive error.
- **Fallback behavior:** Returns standard error details per RFC-7807.
- **Observability requirements:** Counter `docscout_vendor_contracts_audited_total{risk_level}`.
- **Performance limits:** Complete contract audit completed in $\le 60\text{ ms}$ for 30-page agreement.
- **Resource limits:** Memory allocation $\le 32\text{ MB}$.
- **Acceptance criteria:** Detects missing regulatory clauses (e.g. missing RBI unconditional inspection clause) with $\ge 95\%$ accuracy.
- **Evaluation dataset:** 15 sample IT vendor contracts with known compliance gaps against RBI Outsourcing Directions.
- **Evaluation baseline:** 0% automated vendor contract review in baseline.
- **Required improvement threshold:** Missing clause detection recall $\ge 95\%$, precision $\ge 90\%$.
- **Regression limits:** Zero false-positive gap flags on compliant contract terms.
- **Completion criteria:** Unit and integration tests pass in `tests/test_vendor_risk.py`.

---

## FEAT-050: Algorithmic & AI Impact Assessment Framework
- **Objective:** Operationalize the taxonomy's `Algorithmic Impact Assessment` and SEBI Algorithmic Trading / Credit AI compliance checklists to evaluate automated trading algorithms and AI models for regulatory conformity.
- **In-scope behavior:** Evaluating algorithmic system documentation against statutory checklists (explainability, model validation, bias auditing, kill switch validation, audit trail retention); outputting conformity scores.
- **Excluded behavior:** Dynamic real-time code auditing of high-frequency trading C++ binaries.
- **Implementation boundaries:** `app/compliance/algo_impact.py`, `app/api/app.py`.
- **Integration points:** API endpoint `/v1/compliance/algo-assessment`; React console AI Governance tab.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`ai-ml-llm-assurance`), `app/compliance/algo_impact.py`.
- **Supported inputs:** `AlgoAssessmentRequest(system_name: str, model_type: str, system_spec_text: str)`.
- **Input validation rules:** `system_spec_text` length between 100 and 50,000 characters.
- **Output schema:** `AlgoAssessmentResponse(conformity_score: float, passed_controls: list[str], failed_controls: list[FailedControl(control_id: str, title: str, regulation_ref: str, remedy: str)], audit_certificate_id: str)`.
- **Configuration schema:** `AlgoImpactConfig(strict_kill_switch_required: bool = True)`.
- **Default values:** `strict_kill_switch_required = True`.
- **Dependencies:** Pure Python rule engine, Jinja2 for certificate generation.
- **Compatibility requirements:** Stateless REST API execution.
- **Authorization rules:** Requires `compliance:admin` scope.
- **Data isolation rules:** System specifications processed ephemerally; encrypted audit logs.
- **Error behavior:** Schema failure returns HTTP 422 with validation errors.
- **Fallback behavior:** Returns descriptive failure schema.
- **Observability requirements:** Counter `docscout_algo_assessments_completed_total`.
- **Performance limits:** Assessment completed in $\le 25\text{ ms}$ p95.
- **Resource limits:** Memory allocation $\le 16\text{ MB}$.
- **Acceptance criteria:** Accurately flags missing kill-switch mechanisms and unverified model drift monitoring per SEBI algorithmic guidelines.
- **Evaluation dataset:** 10 algorithmic trading system specification documents.
- **Evaluation baseline:** 0% automated algorithmic impact assessment in baseline.
- **Required improvement threshold:** 100% detection of critical regulatory non-conformities.
- **Regression limits:** Zero false failures on compliant system specifications.
- **Completion criteria:** Verified in `tests/test_algo_impact.py`.
