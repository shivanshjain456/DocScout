# ADR-0032: Unified Standards Registry & Authority Engine (FEAT-041)

## Status
Accepted

## Date
2026-10-13

## Context
Enterprise regulatory compliance and statutory intelligence require seamless cross-referencing between national regulations (RBI Master Directions, SEBI Circulars, PMLA rules) and international technical standards (ISO/IEC 27001, NIST SP 800-53, PCI DSS 4.0, SOC 2, EU DORA, DO-178C, FedRAMP). Previously, DocScout maintained partial static lists without unified relational authority modeling, structured control families, or standardized public REST endpoints for standards discovery.

Enterprise-100 specification `pillar-05-standards-registry.md` (FEAT-041) mandates:
1. Indexing 100% of the 53 canonical standards from `term-taxonomy.json.standardsRegistry` plus core Indian banking and capital frameworks into a unified relational authority database.
2. Modeling standards, governing bodies, domains, control families (JSONB), control counts, and statutory hierarchies.
3. Exposing standards via authenticated REST APIs:
   - `GET /v1/standards` (with domain, governing_body, and search query filters).
   - `GET /v1/standards/{standard_id}` (with control families, counts, and RFC-7807 404 listing available standard IDs when unmapped).
4. Relational database schema with GIN index on `control_families` JSONB.
5. High-speed in-memory indexing delivering lookup latency $\le 1.0\text{ ms}$ p95.
6. Prometheus observability tracking `docscout_standards_queried_total{standard_id}`.

## Decision
1. **Catalog Completeness & Alias Resolution**:
   - Canonicalize all 53 standards from `term-taxonomy.json.standardsRegistry`, ensuring exact ID resolution for every single taxonomy standard identifier (including compound IDs like `DO-331 / DO-332 / DO-333`).
   - Augment with standard control families, estimated control counts, and circular mapping placeholders.
   - Support case-insensitive and normalized alias lookups.
2. **Relational Database Migration (`0030_standards_control_families`)**:
   - Add `control_families JSONB DEFAULT '[]'::jsonb`, `control_count INT DEFAULT 0`, and `mapped_circulars_count INT DEFAULT 0` to `standards_registry`.
   - Create GIN index `idx_standards_control_families_gin` for fast JSONB querying.
3. **API Contract & Schema**:
   - Define `StandardMetadata` and `StandardsListResponse` in `app/api/models.py`.
   - Add routes `GET /v1/standards` and `GET /v1/standards/{standard_id}` in `app/api/app.py`.
   - On 404 for unknown standard IDs, return a detailed RFC-7807 problem payload providing available standard IDs and closest matches.
4. **Metrics**:
   - Register `STANDARDS_QUERIED_TOTAL = Counter("docscout_standards_queried_total", "Number of standards queried", ["standard_id"])`.

## Consequences
- **Positive**: 100% data fidelity against canonical term-taxonomy; sub-millisecond retrieval of all global security and banking standards; clear foundational schema for cross-framework control mapping (FEAT-042) and standard-constrained retrieval (FEAT-044).
- **Negative**: Minor memory overhead ($\le 4\text{ MB}$) for in-memory registry caches.
