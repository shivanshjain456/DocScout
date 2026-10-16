# ADR-0028: Semantic Terminology Drift Tracker (FEAT-037)

- **Status:** accepted
- **Date:** 2026-10-13
- **Deciders:** DocScout Engineering Team
- **Related:** FEAT-037, `pillar-04-regulatory-conflicts.md`, `app/compliance/drift_tracker.py`, `app/api/admin_ontology.py`

## Context

Statutory terms in banking and financial regulations evolve significantly over multi-year circular iterations. For example, concepts such as "Critical IT Infrastructure", "Significant Beneficial Owner", and "Material Outsourcee" undergo substantive expansions or contractions across successive RBI, SEBI, and PMLA Master Directions. Treating historical and amended definitions as static synonyms blinds compliance officers to shifting audit obligations and expands regulatory exposure.

Key constraints:
- Drift calculation latency budget $\le 5.0\text{ ms}$ per term across 5 historical versions.
- Memory footprint $\le 8\text{ MB}$.
- Pure Python mathematical execution and deterministic fallback capabilities.
- 100% detection of major definition revisions ($>0.20$ semantic distance).
- Zero false-positive drift alarms on identical definitions across reprint gazettes.
- Authorization: Protected admin/compliance endpoint `GET /v1/admin/ontology/drift/{term_id}`.

## Decision

We will implement:
1. `app/compliance/drift_tracker.py`:
   - `HistoricalDef`: Dataclass and Pydantic model capturing `version_date: date`, `doc_id: str`, `definition_text: str`.
   - `DriftConfig`: Configuration schema with `alert_threshold_distance: float = 0.25`.
   - `TermDriftReport`: Report containing `term_id`, `canonical_term`, `historical_definitions`, `semantic_distance_from_origin`, `key_diff_tokens`, and `drift_alert`.
   - `TerminologyDriftTracker`: Core engine providing:
     - Multi-version definition collation from statutory lineage registry, taxonomy, and staged ontology entries.
     - Cosine distance calculation over normalized vectors using `Embedder` (BGE-small-en-v1.5) with caching and high-speed pure-python vector fallback.
     - Token diff extraction (`key_diff_tokens`) isolating newly introduced or pruned domain keywords, filtering stop words.
     - Single-definition handling (`semantic_distance = 0.0`) and exact-reprint invariance ($0.0$ distance).
2. Observability:
   - Prometheus counter `docscout_terminology_drifts_flagged_total` in `app/api/metrics.py`.
3. Admin API endpoint:
   - `GET /v1/admin/ontology/drift/{term_id}` in `app/api/admin_ontology.py`.

## Consequences

- What becomes easier: Regulatory auditors and engineering teams can track definition evolution and immediately identify when an amended circular expands the scope of compliance obligations.
- What becomes harder: Maintaining historical definition timelines for newly classified terms.
- Cost and performance: Pre-embedding and cached vector calculations execute in $<1.0\text{ ms}$, comfortably within the $5.0\text{ ms}$ SLA, with zero external API calls.

## Rejected alternatives

### Runtime LLM Diff Generation
- What it is: Prompting an LLM on every query to compare two circular text definitions.
- Why it was plausible: Rich conversational explanation of semantic nuances.
- Why we rejected it: High latency ($>1.5\text{ s}$ vs $5.0\text{ ms}$), high token costs, and non-deterministic numerical drift metrics.
- What would change our mind: If explanations are requested on-demand in human review dashboards rather than automated audit pipelines.

### Pure Levenshtein Edit Distance
- What it is: Calculating character or word edit distance directly between definition strings.
- Why it was plausible: Extremely fast string comparison.
- Why we rejected it: Rephrasing or syntactic restructuring with identical semantic meaning causes massive false positive drift alarms, violating the precision and zero-FP reprint requirements.
- What would change our mind: Never for semantic divergence; character distance does not capture regulatory meaning.
