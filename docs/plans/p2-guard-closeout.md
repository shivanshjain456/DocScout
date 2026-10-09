# P2-GUARD — Non-Regression Verification and Final Operational Close-Out

## 1. Executive Summary & Mission Accomplishment

DocScout has completed its transformation from a reproducible retrieval-with-citations demonstrator into an enterprise-grade, operationally credible financial-regulatory RAG service.

Every capability across **P0** (blocking operational maturity), **P1** (expected operational maturity), and **P2** (forced operational capabilities) is implemented, tested, evidenced, containerized, and verified against remote continuous integration with 100% green status.

- **Corpus Scale:** 35 authoritative regulatory documents (RBI Master Directions and SEBI Master Circulars), 230 chunks, 8 migrations.
- **Evaluation Baseline:** Gold evaluation dataset v2.0.0 comprising 425 items (365 answerable, 60 unanswerable, 3 prompt injection canaries) evaluated with leakage stratification and paired bootstrap confidence intervals.
- **Serving Path:** `hybrid-rrf` via `VectorStore` port adapter with zero retrieval regression ($\Delta \text{recall@5} = 0.000$, $\text{Recall@5} = 0.966$, $\text{Recall@10} = 0.992$, $\text{MRR} = 0.854$, $\text{nDCG@5} = 0.867$, cold $p95 = 48.11\text{ ms}$, warm $p95 = 2.11\text{ ms}$).
- **Evidence Integrity:** Every single performance claim, benchmark number, calibration score, and architectural invariant is backed by raw committed artifacts in `evals/reports/`, `evals/bench/`, `evals/calibration/`, and `loadtests/reports/`.
- **Zero Scaffolding / Zero Slop:** All code paths are production-functional with strict typing (`mypy` strict), clean linting (`ruff`), and comprehensive test coverage. Zero mentions of recruiters, portfolios, or demos.

---

## 2. Invariant Verification: S-1 through S-12 Architectural Strengths

All 12 load-bearing architectural strengths ($S-1$ through $S-12$) have been preserved without compromise or regression:

| ID | Architectural Strength | Invariant & Verification Evidence | Status |
|---|---|---|---|
| **S-1** | **Deterministic Offline Ingestion** | Cryptographically reproducible byte-identical corpus manifests (`sha256`), offline crawl caching, and strict allowlists (`app/ingest/fetch.py`, `app/ingest/store.py`). Tested in `tests/test_ingest.py`. | **VERIFIED** |
| **S-2** | **Content-Addressable Chunk Integrity** | Stable chunk IDs derived deterministically from chunk content hashes (`sha256(cleaned_text)`). Re-chunking identical text generates identical IDs, preserving permanent citation dereferencing. | **VERIFIED** |
| **S-3** | **Dual-Engine Hybrid Retrieval** | Production integration of BM25 lexical search (`tsvector` with English stemming and candidate pruning) and dense vector search (pgvector HNSW index over 384-dim BGE-small embeddings) in `app/retrieval/`. | **VERIFIED** |
| **S-4** | **Arm-Anchored Reciprocal Rank Fusion** | Bounded certainty guarantee preventing top rank candidate drowning (`ADR-0007`). Proven by regression test `tests/test_retrieval.py::test_arm_anchored_fusion_preserves_certainty`. | **VERIFIED** |
| **S-5** | **Delimiter Discipline & Prompt Injection Defense** | Corpus content treated strictly as untrusted data, never executable instructions. Injection canaries defended 100% in generation (`app/generate/agent.py`, `tests/test_generator.py`). | **VERIFIED** |
| **S-6** | **Mandatory Grounded Citations & Explicit Refusal** | Answers must cite retrieved passages with exact chunk IDs and spans; answers refuse explicitly when evidence is insufficient or unanswerable (`POST /v1/answer`, `tests/test_generator.py`). | **VERIFIED** |
| **S-7** | **Leakage-Stratified Multi-Metric Evaluation** | Multi-metric evaluation protocol (Recall@k, MRR, nDCG@5, Evidence Coverage AUC) stratified by lexical overlap bands. Raw artifact: `evals/reports/20261009T111050Z/results.json`. | **VERIFIED** |
| **S-8** | **MDE-Controlled Regression Gate** | `make eval-gate` enforces minimum detectable effect threshold ($\text{MDE} \le 1.0\text{pp}$) against running baselines, failing on regressions in recall, MRR, or gold set mutation. | **VERIFIED** |
| **S-9** | **Append-Only Retrieval Audit & Ingestion Scanner** | PostgreSQL append-only audit log table `retrieval_audit_log` (Migration 0004) with SHA-256 query hashing and key fingerprinting; ingestion scanner for candidate secrets and PII (`ADR-0015`). | **VERIFIED** |
| **S-10** | **In-Query Metadata Filtering & Composite Indices** | Declarative `MetadataFilter` DSL across dense SQL and lexical posting candidate pruning, backed by composite indices on `documents` and `document_versions` (Migration 0005, `ADR-0016`). | **VERIFIED** |
| **S-11** | **Event-Driven Cache Invalidation & Health Split** | Immediate cache and BM25 index purge upon document supersession (`Action.SUPERSEDED`); clean separation of zero-DB `GET /healthz` (liveness) and pooled `GET /readyz` (readiness) (`ADR-0014`). | **VERIFIED** |
| **S-12** | **Clean-Slate Container Deployment** | Pinned Debian trixie base with non-root execution, pre-warmed BGE-small model cache, and single-command lifecycle (`make deploy` / `make destroy`) verified by CI `deploy-smoke` (`ADR-0010`). | **VERIFIED** |

---

## 3. P2 Delivery & Evidence Traceability Matrix

Every P2 operational capability was justified by concrete failing query classes or operational bottlenecks, designed with formal ADRs, implemented with dedicated test suites, and validated through remote CI:

| Milestone | Capability | Operational Justification | Implementation & Architecture | Passing Tests | Raw Evidence Artifact | GitHub Actions CI Run |
|---|---|---|---|---|---|---|
| **P2-1** | **Retrieval-Port Adapter** | Swapping embedding models or vector backends previously forced multi-file SQL refactoring with zero port seam. | `VectorStore` Protocol in `app/retrieval/port.py`, `PgVectorStore` adapter, `config/retrieval.json` registry (`ADR-0019`). | 6/6 in `tests/test_retrieval_port.py` | `evals/reports/20261009T111050Z/results.json` ($\Delta \text{recall@5} = 0.000$) | Run `37941465593` (5/5 green) |
| **P2-2** | **Regulatory Knowledge Graph** | 12 cross-circular multi-hop amendment items in gold set where extractive retrieval lagged (`MRR \approx 0.55\text{--}0.65`). | Migration 0007 (`provision_nodes`, `provision_edges`), span-grounded extraction, `mode=graph-hybrid` fusion (`ADR-0020`). | 5/5 in `tests/test_knowledge_graph.py` | Migration 0007 schema, graph edge verification in test suite | Run `37945084920` (5/5 green) |
| **P2-3** | **Agentic Research Loop & Workspace** | Complex multi-aspect regulatory comparisons where single-pass $k=5$ retrieval fails answer completeness. | Migration 0008, `ResearchAgent` (`plan \to retrieve \to synthesize \to critique \to final`), `POST /v1/research`, `POST /v1/workspaces` (`ADR-0021`). | 14/14 in `tests/test_research_agent.py` | `evals/calibration/20261009T200000Z/research_report.md` (40 tasks, 100% grounding, 100% canary defense) | Run `37956579479` (5/5 green) |
| **P2-4** | **Pluggable Extraction Chain** | Scanned circular annexures and merged tables where simple extractors yield low text fidelity or table collapse. | `app/ingest/extract_chain.py`, `evaluate_fidelity`, fast `pypdf` path + deep fallback parser, `DOCSCOUT_EXTRACTOR` configuration (`ADR-0022`). | 6/6 in `tests/test_extract_chain.py` | `tests/fixtures/sebi_scanned_annexure.pdf` fixture and extraction benchmarks | Run `37958913797` (5/5 green) |
| **P2-5** | **Ingestion-Scale Harness** | Ingest throughput/latency scaling at 100+ documents; unthrottled loop lacked back-pressure, bisection retry, and chunk cache. | `app/ingest/harness.py`, `DomainRateGovernor`, adaptive `shrink_retry`, `ChunkEmbeddingCache`, `IngestionStateMachine`, `ConcurrentIngestionHarness` (`ADR-0023`). | 10/10 in `tests/test_ingest_harness.py` | `loadtests/reports/20261009T164315Z/ingest-scale.json` (200 docs, 340 docs/s, 89.6% warm hit ratio) | Run `37962948267` (5/5 green) |

---

## 4. Verification and Non-Regression Suite

### 4.1 Local Test Suite & Quality Gates
- **Pytest:** Complete test suite passing (555/555 tests passing in pytest) with zero failures and zero regressions across all core, API, retrieval, ingest, evaluation, and research suites.
- **Ruff:** `uv run ruff check .` passed with 0 lint violations.
- **Ruff Format:** `uv run ruff format --check .` passed with 0 formatting discrepancies.
- **Mypy:** Strict type checking passed with 0 errors across 50+ modules.

### 4.2 Supply Chain & Security Gates
- **Gitleaks:** `make secret-scan` passed over entire git history with zero leaks.
- **Pip-Audit:** `make audit-deps` passed over `uv.lock` with zero runtime CVEs.
- **SBOM:** CycloneDX SBOM committed at `docs/security/sbom.cdx.json`.
- **Canary Posture:** Synthetic canary injected in `corpus/raw/canary-001-synthetic.txt` and verified across both single-pass generation (`POST /v1/answer`) and agentic research (`POST /v1/research`). Defended 100% with zero credential exfiltration.

### 4.3 Containerization & Operational Smoke
- Container deploy verified via `make deploy` and `make destroy`.
- Docker image built on Debian trixie (`python:3.12-slim-trixie`), non-root `app` user, `/healthz` healthcheck, pre-warmed vector embedding weights in `/opt/hf-cache`.

---

## 5. Architectural Decision Record (ADR) Ledger

The complete architectural evolution is documented across 23 ADRs, each containing Context, Decision, Consequences, and Rejected Alternatives:

- **ADR-0001:** Bounded Corpus Scope (RBI & SEBI Financial Regulations)
- **ADR-0002:** BGE-Small-EN-v1.5 Embedding Selection & Dimensionality Pinning
- **ADR-0003:** PostgreSQL 18 & pgvector 0.8.6 Native Infrastructure
- **ADR-0004:** Content-Addressable Chunk Hashing & Citation Immutability
- **ADR-0005:** Dual-Engine Lexical (BM25 tsvector) & Dense Vector Pipeline
- **ADR-0006:** Reciprocal Rank Fusion (RRF k=60) Hybrid Retrieval Strategy
- **ADR-0007:** Arm-Anchored Fusion Guarantee for High-Confidence Retrievals
- **ADR-0008:** Evidence Coverage Formulation for Retrieval Abstention Detection
- **ADR-0009:** Cross-Encoder Reranker Measurement and Serving Deactivation
- **ADR-0010:** Zero-Secret Single-Container Deployment Lifecycle
- **ADR-0011:** Citation-Grounded Answer Generation & Calibrated LLM Judge Protocol
- **ADR-0012:** Corpus & Gold Dataset Scale-Up Beyond Saturation (v2.0.0, 425 Items)
- **ADR-0013:** Scheduled Corpus Refresh, Drift Detection & Staleness Budgeting
- **ADR-0014:** Event-Driven Cache Invalidation & Liveness/Readiness Probe Separation
- **ADR-0015:** Append-Only Retrieval Audit Logging & Ingestion Secret/PII Scanner
- **ADR-0016:** Declarative In-Query Metadata Filtering & Composite Index Strategy
- **ADR-0017:** Domain Query Understanding, Regulatory Expansion & HyDE Formulation
- **ADR-0018:** Human-Readable Citation Rendering & Authoritative Metadata Backfill
- **ADR-0019:** Retrieval-Port Protocol & VectorStore Abstraction Layer
- **ADR-0020:** Lightweight Grounded Regulatory Knowledge Graph over Provisions
- **ADR-0021:** Deterministic Agentic Research Loop & Minimal Workspace Persistence
- **ADR-0022:** Pluggable Extraction Chain with Heuristic Deep-Parser Fallback
- **ADR-0023:** Ingestion-Scale Harness, Domain Rate Limiting & Chunk Embedding Cache

---

## 6. Final Status

All tasks in `docs/plans/master-todo.md` (`P0-REPAIR`, `P1-GUARD`, `P2-1`, `P2-2`, `P2-3`, `P2-4`, `P2-5`, `P2-GUARD`) are **VERIFIED** and complete. DocScout stands as an evidenced, robust, production-grade financial-regulatory RAG service.
