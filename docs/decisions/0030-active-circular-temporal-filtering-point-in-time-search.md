# ADR-0030: Active Circular Temporal Filtering / Point-in-Time Search (FEAT-039)

- **Status:** accepted
- **Date:** 2026-10-13
- **Deciders:** DocScout Engineering Team
- **Related:** FEAT-039, `pillar-04-regulatory-conflicts.md`, `app/retrieval/dense.py`, `app/retrieval/lexical.py`, `app/api/models.py`

## Context

Forensic statutory investigations and regulatory audits (e.g., investigating a compliance incident that occurred in 2018) require inspecting the exact corpus of circulars and guidelines that were legally active on that specific historical date. Standard search engines return current 2024–2026 Master Directions, contaminating retroactive audits with retrospective rules ("future leakage").

Key constraints:
- Bitemporal filtering in PostgreSQL queries: `published_date <= as_of_date AND (superseded_date IS NULL OR superseded_date > as_of_date)`.
- Input validation: `YYYY-MM-DD` between 1990-01-01 and current date. Future dates must be rejected with HTTP 422 (`as_of_date cannot be in the future`).
- 100% backward compatibility: omitting `as_of_date` defaults to current active circulars (`v.is_current = true`).
- Performance: temporal search p95 latency $\le 28.0\text{ ms}$, with zero latency impact on current-date queries.
- Observability: structlog `as_of_date` field and Prometheus counter `docscout_temporal_queries_total`.

## Decision

We will implement:
1. Migration `migrations/0029_temporal_search.up.sql` & `migrations/0029_temporal_search.down.sql`:
   - Adding `superseded_date date` to `documents` table.
   - B-tree indices on `documents(published_date)` and `documents(superseded_date)`.
2. Schema & Filter Models:
   - `ChunkMeta.superseded_date`: Field on in-memory chunk metadata.
   - `MetadataFilter.as_of_date`: Bitemporal date filter for retrieval pruning.
   - `SearchRequest.as_of_date`: API query parameter validated to prevent future dates.
3. Query Execution Engines:
   - `app/retrieval/dense.py`: Dynamic SQL predicate incorporating `COALESCE(d.published_date, v.fetch_ts::date) <= %(as_of_date)s AND (d.superseded_date IS NULL OR d.superseded_date > %(as_of_date)s)`.
   - `app/retrieval/lexical.py`: `MetadataFilter.matches` evaluating in-memory temporal validity for candidate postings.
4. Observability:
   - Prometheus counter `docscout_temporal_queries_total` in `app/api/metrics.py`.

## Consequences

- What becomes easier: Statutory auditors can recreate the regulatory reality of any past audit year (2015, 2018, 2021) with zero risk of future circular bleed.
- What becomes harder: Ensuring documents have accurate `published_date` and `superseded_date` metadata.
- Cost and performance: Indexed date lookups execute in $<2.0\text{ ms}$ in PostgreSQL, comfortably below the $28.0\text{ ms}$ threshold.

## Rejected alternatives

### Separate Static Database Snapshots per Year
- What it is: Maintaining distinct database instances or tables for each historical year (e.g., `documents_2018`, `documents_2021`).
- Why it was plausible: Complete isolation between years.
- Why we rejected it: Multiplies storage costs and migration complexity across dozens of years, and cannot handle arbitrary intra-year dates (e.g. 2018-05-14).
- What would change our mind: Never; bitemporal SQL filtering over single indexed table is standard.
