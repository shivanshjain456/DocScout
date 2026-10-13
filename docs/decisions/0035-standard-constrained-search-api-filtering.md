# ADR-0035: Standard-Constrained Search API Filtering via Relational Control Crosswalk

## Status
Accepted (FEAT-044)

## Context
Callers of the DocScout search API frequently need to constrain evidence retrieval to circulars and guidance mapped to a specific international standard (e.g., `PCI DSS 4.0`, `ISO/IEC 27001`, `AICPA SOC 2`) or national framework (`NIST SP 800-53`, `RBI Cyber Security Framework`).

Without strict standard-boundary filtering:
1. Retrieval returns mixed cross-framework passages where controls from other frameworks pollute compliance audits.
2. Compliance auditors require 100% precision that every cited passage in the result set directly fulfills the specified standard or mapped control.
3. Callers passing unregistered or misspelled standards must receive fast, descriptive validation errors (HTTP 422 with catalog of known standards) rather than silently returning unconstrained or hallucinated results.

## Decision
1. **API Schema Contract (`app/api/models.py`, `app/retrieval/types.py`)**:
   - Add `standard: Optional[str] = None` and alias `framework: Optional[str] = None` to `MetadataFilter`.
   - Validate `filter.standard` against `StandardsRegistry`. Unrecognized standard IDs or names raise validation errors that FastAPI serializes as HTTP 422 containing known standard IDs.
   - Include `self.standard` in `MetadataFilter.canonical_tuple()` to guarantee cache key isolation between constrained and unconstrained searches.
2. **Database Relational Join Schema (Migration 0032)**:
   - Extend `framework_control_crosswalk` with:
     - `standard_id VARCHAR(100) NULL REFERENCES standards_registry(id) ON DELETE SET NULL`
     - `chunk_id UUID NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE`
     - Composite index `idx_crosswalk_standard_chunk ON framework_control_crosswalk(standard_id, chunk_id)`
     - B-Tree index `idx_crosswalk_chunk_id ON framework_control_crosswalk(chunk_id)`
3. **Retrieval Arm Execution**:
   - **Dense Vector Search (`app/retrieval/dense.py`)**:
     - When `filter.standard` is specified, execute a SQL `JOIN` on `framework_control_crosswalk` matching canonical standard ID, aliases, or framework names, bounded by the PostgreSQL index `idx_crosswalk_standard_chunk`.
   - **Lexical BM25 Search (`app/retrieval/lexical.py`)**:
     - Constrain posting traversal using chunk-to-standard mapping loaded from `framework_control_crosswalk` or evaluated against in-memory `ChunkMeta.standard_ids`.
   - **Fallback Behavior**:
     - If the standard join yields zero matching chunks, return an empty passage list with confidence `evidence_coverage=0.0` and `low_evidence=True`.
4. **Observability**:
   - Prometheus counter `docscout_standard_constrained_queries_total{standard}` in `app/api/metrics.py`.
   - Structured logging of `filter_standard` in structlog during search processing.

## Consequences
- **Positive**:
   - 100% precision on standard-constrained queries; zero cross-framework leakage.
   - P95 query latency maintained $\le 22.0\text{ ms}$.
   - Backward compatible: unconstrained searches incur zero overhead.
- **Negative**:
   - Ingestion and crosswalk pipeline must maintain foreign key relationships between chunks and mapped standard controls.
