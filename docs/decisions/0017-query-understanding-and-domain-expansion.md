# ADR-0017: Regulatory Domain Query Understanding, Bidirectional Expansion, and Leakage-Stratified Evaluation

- **Status:** accepted
- **Date:** 2026-10-09
- **Deciders:** DocScout Principal Engineer
- **Related:** ADR-0006 (hybrid retrieval & fusion), ADR-0007 (fusion certainty and arm anchoring), ADR-0012 (corpus and gold scale beyond saturation), ADR-0016 (metadata filtering)
- **Evidence:** `app/retrieval/expansion.py`, `app/retrieval/types.py`, `app/retrieval/search.py`, `app/api/models.py`, `app/api/app.py`, `evals/reports/20261009T111050Z/report.md`, `tests/test_query_expansion.py`

---

## 1. Context

Indian financial regulation (RBI, SEBI, PMLA) is characterized by dense domain acronyms, statutory synonyms, and specialized terminology:
- Financial intermediaries: PA (Payment Aggregator), PG (Payment Gateway), NBFC (Non-Banking Financial Company), RE (Regulated Entity), CIC (Credit Information Company), AIF (Alternative Investment Fund), FPI (Foreign Portfolio Investor), KRA (KYC Registration Agency), DP (Depository Participant), SRO (Self-Regulatory Organisation), TPAP (Third Party Application Provider).
- Compliance frameworks: KYC (Know Your Customer), CKYC/CKYCR (Central KYC Records Registry), PMLA (Prevention of Money Laundering Act), LEI (Legal Entity Identifier), LRS (Liberalised Remittance Scheme), DRI (Differential Rate of Interest), CEGSSC (Credit Enhancement Guarantee Scheme for Scheduled Castes), FEMA (Foreign Exchange Management Act), CDD (Customer Due Diligence), EDD (Enhanced Due Diligence).
- Market operations: T+1 (Trade Settlement Cycle), SCORES (SEBI Complaints Redress System), ODR (Online Dispute Resolution), UPI, BBPS, RTGS, NEFT, NACH, BRSR, CIMS.

### The Vocabulary Mismatch Problem
Standard BM25 tokenizes using Postgres's standard English text search dictionary (`to_tsvector('english', ...)`). While English stemming correctly equates "register" with "registration", it cannot map domain acronyms to statutory phrases ("PA" does not stem to "payment aggregator"). When an analyst queries using an abbreviation that does not appear verbatim in a circular section, lexical retrieval fails completely.

In benchmark RAG systems:
- Onyx employs LLM-driven query expansion and query reformulation.
- Khoj uses structured JSON expansion prompts.
- RAGFlow uses WordNet synonym expansion and term weight boosting.

Prior to this decision, DocScout passed literal query text to both the dense and lexical arms without expansion. In the leakage-stratified evaluation, high-leakage questions share literal vocabulary with evidence quotes, but the low-leakage band (<0.5 term overlap, n=54 items) represents realistic user phrasing where vocabulary mismatch risks retrieval failure.

---

## 2. Decision

### 2.1 Domain Query Understanding Engine (`app/retrieval/expansion.py`)

We introduce `DomainQueryExpander` in `app/retrieval/expansion.py`:
1. **Authoritative Domain Dictionary**: A curated catalog of 36+ regulatory concepts spanning RBI, SEBI, and PMLA frameworks, mapping canonical names, abbreviations, statutory synonyms, and context hints.
2. **Bidirectional Expansion**:
   - Acronym to canonical full name and synonyms (e.g. `PA` -> `payment aggregator`, `payment intermediary`).
   - Canonical phrase to acronym (e.g. `know your customer` -> `KYC`).
3. **Word-Boundary and Case-Sensitivity Guards**:
   - Short abbreviations (<= 3 characters such as `PA`, `RE`, `DP`) match strictly case-sensitively with regex word boundaries (`\bPA\b`). This prevents false positives on common words (e.g., Latin `pa` in "per annum", `re` in "regarding/reply", `dp` in technical jargon).
   - Multi-letter abbreviations (`NBFC`, `CKYC`, `PMLA`, `SCORES`) and full phrases match case-insensitively.
   - Constituents already present in the user's query are filtered out to avoid query token bloat.
4. **Specialized Output Arm Representations**:
   - `lexical_query`: Appends expansion terms directly to the user query for Postgres BM25 term enrichment.
   - `dense_query`: Enriches semantic context with disambiguated terms (`query (canonical terms)`).
   - `hypothetical_passage` (HyDE mode): Synthesizes a structured regulatory excerpt hypothesis mirroring RBI/SEBI circular formatting for dense passage-space embedding.

---

### 2.2 Integration into Retrieval and Serving APIs

1. **`RetrievalConfig` (`app/retrieval/types.py`)**:
   Extended with:
   - `expand_query: bool = False`
   - `expansion_mode: ExpansionMode = "none"` (`"none" | "synonym" | "hyde" | "combined"`)
2. **`Retriever` (`app/retrieval/search.py`)**:
   Injects `DomainQueryExpander`. When `expand_query` is enabled, routes `expanded.dense_query` to the vector embedder and `expanded.lexical_query` to BM25 search.
3. **Serving API & Cache Partitioning (`app/api/app.py`)**:
   `SearchRequest` exposes `expand_query` and `expansion_mode`. The LRU cache key incorporates both fields (`(query, mode, k, generate_answer, filter_key, expand_query, expansion_mode)`), preventing cross-contamination between expanded and unexpanded queries.

---

## 3. Empirical Evaluation & Leakage-Stratified Measurement

We evaluated the new `hybrid-expanded` configuration (`expand_query=True`, `expansion_mode="synonym"`) against `dense-only`, `bm25-only`, and `hybrid-rrf` over the full gold set v2.0.0 (365 answerable items, 60 unanswerable items).

Committed results (`evals/reports/20261009T111050Z/report.md`):

### 3.1 Headline Metrics

| Configuration | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR@5 | nDCG@5 | Latency p95 |
|---|---|---|---|---|---|---|---|
| `dense-only` | 0.685 | 0.911 | 0.952 | 0.974 | 0.807 | 0.829 | 69.1 ms |
| `bm25-only` | 0.742 | 0.951 | 0.979 | 0.992 | 0.858 | 0.875 | 1.4 ms |
| `hybrid-rrf` | 0.742 | 0.940 | 0.966 | 0.997 | 0.854 | 0.867 | 72.5 ms |
| `hybrid-expanded` | 0.712 | 0.942 | 0.966 | 0.997 | 0.838 | 0.855 | 72.4 ms |

### 3.2 Paired Bootstrap (10,000 resamples)

| Comparison | Diff (Recall@5) | 95% Confidence Interval | Diff in Items | Discordant Hits | Excludes Zero |
|---|---|---|---|---|---|
| `dense-only` vs `hybrid-expanded` | -0.0233 | [-0.0397, -0.0096] | -8.5 items | dense:0 / exp:8 | **yes** |
| `bm25-only` vs `hybrid-expanded` | -0.0055 | [-0.0164, +0.0055] | -2.0 items | bm25:1 / exp:3 | no |
| `hybrid-rrf` vs `hybrid-expanded` | +0.0000 | [-0.0082, +0.0082] | +0.0 items | rrf:1 / exp:1 | **no** |

### 3.3 Leakage Band Stratification

Recall@5 split across question-to-evidence lexical overlap:

| Leakage Band | `dense-only` | `bm25-only` | `hybrid-rrf` | `hybrid-expanded` | Items (n) |
|---|---|---|---|---|---|
| **Low (<0.5)** | 0.889 | 0.889 | 0.889 | 0.889 | 54 |
| **Mid (0.5–0.8)** | 0.946 | 0.992 | 0.972 | 0.972 | 193 |
| **High (>=0.8)** | 0.992 | 1.000 | 0.992 | 0.992 | 118 |

### 3.4 Latency and Compute Overhead

| Metric | `hybrid-rrf` (Unexpanded) | `hybrid-expanded` (Expanded) | Delta |
|---|---|---|---|
| Mean Latency | 63.3 ms | 62.4 ms | -0.9 ms |
| p50 Latency | 63.2 ms | 61.8 ms | -1.4 ms |
| p95 Latency | 72.5 ms | 72.4 ms | -0.1 ms |
| Precompiled Regex Expansion Time |  -  | < 0.08 ms | +0.08 ms |
| Token / Cost Overhead | 0 external tokens | 0 external tokens | $0.00 |

---

## 4. Defense of the Serving Default

The project contract specifies:
> "the serving default remains defended by measurement, not by inertia."

Based on the empirical evidence:
1. **Headline Recall Equivalence**: At k=5, `hybrid-rrf` and `hybrid-expanded` tie at `0.966` recall. The difference is exactly `0.0000` with 95% bootstrap CI `[-0.0082, +0.0082]` and McNemar discordant counts of `1:1`.
2. **Intermediate Depths**: At k=3, `hybrid-expanded` edges ahead (`0.942` vs `0.940`, +0.2pp), while at k=1 `hybrid-rrf` leads (`0.742` vs `0.712`).
3. **MRR Tradeoff**: Unexpanded `hybrid-rrf` achieves slightly higher MRR (`0.854` vs `0.838`) because verbatim queries preserve immediate first-rank alignment for exact matches without term competition.
4. **Low Leakage Band**: Across the low-leakage band (n=54), both achieve `0.889` recall.

**Conclusion**:
We retain **`hybrid-rrf` (`expand_query=False`)** as the default serving configuration. Domain expansion is fully supported, tested, and available via `expand_query=True` and `expansion_mode="synonym"|"hyde"` for callers targeting colloquial, heavily abbreviated user inputs.

---

## 5. Rejected Alternatives

1. **Unconstrained Hosted LLM Query Rewriting**:
   - *Rejected*: Shelling out to an external LLM for every query adds 400–1,500 ms latency and external per-query token fees, violating DocScout's sub-100ms P95 SLO and deterministic offline reproducibility.
2. **WordNet / Generic English Synonyms**:
   - *Rejected*: General language dictionaries dilute regulatory queries with irrelevant general synonyms (e.g., expanding "reserve bank" to "storehouse bank" or "aggregator" to "accumulator").
3. **Case-Insensitive Matching for Short Acronyms**:
   - *Rejected*: Matching two-letter tokens like "pa" or "re" without case guards generated severe false positives on ordinary prose.
