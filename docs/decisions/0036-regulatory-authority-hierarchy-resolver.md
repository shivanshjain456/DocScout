# ADR-0036: Regulatory Authority Hierarchy Resolver (FEAT-045)

## Status
Accepted

## Context
In regulatory compliance and statutory interpretation, legal instruments possess a strict hierarchy of precedence:
1. Constitutional & Parliamentary Acts (e.g., Banking Regulation Act, Reserve Bank of India Act, PMLA) - Tier 1
2. Master Directions (Statutory subordinate legislation issued under Act powers) - Tier 2
3. Regulatory Circulars / Notifications - Tier 3
4. Guidelines / Technical Specifications - Tier 4
5. Administrative Clarifications, Press Releases & FAQs - Tier 5

When naive dense or lexical retrieval is executed against a unified compliance corpus, informational FAQs frequently outrank formal statutory Master Directions or Acts because FAQs use informal, user-friendly language closely matching natural language user search queries. This inversion poses compliance risk: operations teams might follow informal FAQ commentary that conflicts with binding Master Direction requirements.

## Decision
1. **Document Classification & Authority Tiering**:
   - Introduce `document_class` (`ACT`, `MASTER_DIRECTION`, `CIRCULAR`, `GUIDELINE`, `FAQ`) and `authority_tier` (1 to 5) in `documents`.
   - Implement `app/retrieval/authority.py` with `AuthorityConfig` defining tier multipliers:
     - `ACT`: 1.25x
     - `MASTER_DIRECTION`: 1.15x
     - `CIRCULAR`: 1.05x
     - `GUIDELINE`: 1.00x
     - `FAQ`: 0.85x
     - Unknown / neutral: 1.00x

2. **Retrieval Scoring Boost**:
   - In `Retriever.retrieve()`, candidate passages are evaluated through the authority resolver.
   - Boost multipliers are applied mathematically: `score * multiplier`.
   - Results are re-ordered maintaining deterministic tie-breaking.
   - Observability: `applied_authority_tier` is logged and embedded in `Retrieved` passage provenance.

3. **Performance & Invariance**:
   - Multiplication overhead <= 0.05ms per candidate.
   - Strict monotonic score preservation.
   - Informational FAQs remain retrievable when explicitly queried.

## Consequences
- Authoritative sources rank top-1 >= 95% of the time during conflicting queries.
- Operational teams receive binding legal instruments ahead of informal summaries.
- Zero extra memory or external model dependencies.
