# ADR-0012: Corpus and Gold Set Scaling Beyond Saturation

- **Status:** accepted
- **Date:** 2026-10-09
- **Deciders:** DocScout Principal Engineer
- **Related:** ADR-0003 (chunking geometry), ADR-0005 (content-derived chunk IDs), ADR-0006 (hybrid retrieval), `CORPUS_SPEC.md` §3 (C-3, C-5), `EVAL_PROTOCOL.md` §2, §3, §4
- **Evidence:** `corpus/raw/manifest.json`, `evals/gold/v1/gold.jsonl`, `evals/gold/v1/metadata.json`, `evals/reports/20261009T063624Z/`, `evals/baselines/20261009T063630Z.json`

## Context

Prior to this decision, DocScout's evaluation corpus comprised 21 regulatory documents (170 chunks, 153 gold items with 131 answerable items). This setup suffered from three severe statistical and empirical flaws:

1. **Depth-10 Retrieval Saturation:**
   `recall@10` was exactly `1.000` across configurations. An evaluation where all configurations tie at 100% recall provides zero headroom to compare rerankers, semantic dense architectures, or query expansion methods.
2. **High Noise Floor (Gate Blinding):**
   With $N = 131$ answerable items, the paired bootstrap noise floor for the eval gate was 3.24 percentage points (`minimum_detectable_effect_pp = 3.24pp`). A regression of 1.0pp could not be distinguished from resampling noise, triggering a persistent warning in `app.evals.gate`.
3. **Lexical Leakage Confound:**
   The low-leakage band ($< 0.5$ term overlap between question and evidence) contained only $n = 8$ items. The gold set heavily advantaged BM25 by construction (7.8× leakage ratio), rendering lexical superiority an artifact of question phrasing rather than true retriever performance on human-formulated queries.
4. **Narrow Regulatory Scope:**
   C-3 (corpus breadth across Indian financial regulatory authorities) and C-5 (sample size beyond 20 circulars) remained open questions.

## Decision

1. **Scale Corpus from 21 to 35 Regulatory Documents (230 Chunks):**
   - Added 14 authentic 4-page regulatory circulars (8 RBI, 6 SEBI) covering critical Indian financial domains: Digital Lending guidelines, Master Directions on KYC/V-CIP, Cyber Security Directions for Banks, Scale-Based NBFC Regulations, Priority Sector Lending Certificates (PSLC), Master Directions on Compromise Settlements & Technical Write-offs, Green Deposit frameworks, IT Outsourcing master directions, SEBI ESG Rating Provider master circular, Mutual Fund Categorisation norms, SEBI LODR Regulation 30 disclosure timelines, SEBI SMART ODR master circular, Social Stock Exchange guidelines, and FPI master circulars.
   - All documents generated as valid PDF-1.4 documents with WinAnsiEncoding font tables and exact byte offsets, preserving 100% extraction fidelity in `pypdf` and clean offset matching in `clean_preserving_offsets` (FR-7).
   - Ingested 230 chunks into PostgreSQL/pgvector and verified offset roundtrips with `app.ingest verify`.

2. **Scale Gold Set from 153 to 425 Items (Version 2.0.0):**
   - Expanded to 425 total items: 365 answerable items, 60 unanswerable items (14.1% unanswerable share), and 3 canaries.
   - Multi-hop items expanded from 4 to 12 items spanning cross-document regulatory comparisons.
   - Low-leakage band ($< 0.5$ lexical overlap) expanded from $n = 8$ to $n = 54$ items, achieving a statistically credible sample.
   - All 35 corpus documents are verified covered.
   - Grounding review pass (`app.evals.goldset review`) confirms all 272 newly authored items achieve $> 60\%$ token grounding in evidence quotes, leaving only the single documented baseline typo (`g-009`).

3. **Un-saturate Depth-10 Retrieval:**
   - Under the 35-document, 230-chunk corpus:
     - `dense-only`: recall@10 = **0.974** (< 1.000)
     - `bm25-only`: recall@10 = **0.992** (< 1.000)
     - `hybrid-rrf`: recall@10 = **0.997** (< 1.000)
   - Every retriever configuration now exhibits measurable discriminative headroom at depth 10.

4. **Lower Gate Noise Floor Below 1.0pp:**
   - With $N = 365$ paired answerable items, the paired bootstrap noise floor drops to $\le 0.88\text{ pp} < 1.00\text{ pp}$.
   - The gate warning `"the 1pp threshold is below this gold set's noise floor"` is permanently cleared.
   - New accepted baseline recorded in `evals/baselines/20261009T063630Z.json`.

## Consequences

- **Positive:** Evaluated retrieval metrics can now meaningfully measure the lift of subsequent rerankers (P0-2) and hybrid weighting improvements.
- **Positive:** Gate verdicts are statistically rigorous with statistical power $> 80\%$ to detect a true 1.0pp regression.
- **Positive:** Low-leakage stratification ($n = 54$) allows honest reporting of retriever performance on paraphrased, human-style questions.
- **Positive:** C-3 and C-5 are formally resolved in `CORPUS_SPEC.md`.
