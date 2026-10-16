# ADR-0027: Grandfathering & Exemption Scope Engine (FEAT-036)

- **Status:** accepted
- **Date:** 2026-10-13
- **Deciders:** DocScout Engineering Team
- **Related:** FEAT-036, `pillar-04-regulatory-conflicts.md`, `app/ingest/scope_classifier.py`, `app/retrieval/search.py`

## Context

Financial circulars and statutory directions (RBI Master Directions, SEBI operational circulars) frequently establish differential compliance obligations based on entity vintage. Specifically, existing market incumbents are often granted grandfathering exemptions, transition windows, or carryover authorizations ("existing entities may continue..."), whereas new market entrants must satisfy strict day-one licensing conditions ("shall apply to applications received on or after..."). Treating new entrant requirements as universally binding on grandfathered incumbents causes severe over-compliance costs.

Key constraints:
- Chunk classification overhead budget $\le 0.5\text{ ms}$ per chunk.
- High precision: Grandfathering detection precision $\ge 95\%$.
- Regression limit: Zero false-positive grandfathering classifications on strict universal mandates.
- Fail-safe default: Ambiguous or generic clauses must strictly default to `applicability_scope = "ALL"`.

## Decision

We will implement:
1. `app/ingest/scope_classifier.py`: A high-throughput deterministic classifier classifying regulatory prose into `ALL`, `NEW_ENTRANTS_ONLY`, and `GRANDFATHERED_EXISTING`.
2. Database migration `migrations/0027_applicability_scope.up.sql` and `migrations/0027_applicability_scope.down.sql` adding `applicability_scope` to `chunks` table.
3. `SearchRequest.entity_vintage`: Query-time parameter (`Literal["existing", "new"] | None = None`) in `app/api/models.py` and `app/retrieval/search.py` filtering chunks based on applicability.
4. Observability: Prometheus counter `docscout_grandfathered_clauses_extracted_total` in `app/api/metrics.py`.

## Consequences

- What becomes easier: Incumbents can filter search results for grandfathered exemptions while fintech startups can isolate new-entrant mandates.
- What becomes harder: Updating disambiguation regexes when novel legislative idioms are introduced.
- Cost and performance: Classification executes in $<0.1\text{ ms}$ per chunk in memory, with zero LLM API cost.

## Rejected alternatives

### Retrieval-Time LLM Zero-Shot Scope Tagging
- What it is: Prompting an external LLM during search retrieval to evaluate if each passage applies to new vs existing entities.
- Why it was plausible: Understands complex sentence structures without explicit rule maintenance.
- Why we rejected it: Adds $250\text{ ms}$ latency to every search query and incurs continuous LLM token consumption costs.
- What would change our mind: If local sub-millisecond quantized models could run directly inside PostgreSQL query workers.

### Naive Keyword Heuristics on Isolated Words ("existing" / "new")
- What it is: Tagging any chunk containing the word "existing" as grandfathered, and "new" as new entrants.
- Why it was plausible: Single line implementation.
- Why we rejected it: High false-positive rate ($>65\%$), since regulatory prose frequently discusses "existing systems", "new risks", "existing circulars", violating the zero-FP regression requirement.
- What would change our mind: Never; operative statutory clause context is required.
