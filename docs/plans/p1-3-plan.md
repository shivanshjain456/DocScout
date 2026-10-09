# Plan: P1-3 — Query Understanding Expansion

## Context and Problem Statement
- **Retrieval & Vocabulary Mismatch (§3.6)**:
  - Regulatory text from RBI and SEBI is heavily laden with domain acronyms, statutory synonyms, and specialized phrases (e.g. "PA" vs "Payment Aggregator" vs "Intermediary", "FPI" vs "Foreign Portfolio Investor", "RE" vs "Regulated Entity", "KYC" vs "Know Your Customer", "T+1" vs "Settlement Cycle").
  - BM25 uses standard English stemming (`to_tsvector('english', ...)`), which stem words like "register" -> "regist" but cannot map acronyms or synonyms. When a query uses an abbreviation that does not appear verbatim in the statute, the lexical arm yields zero score.
  - In our leakage-stratified evaluation, high-leakage questions share literal vocabulary with evidence quotes, but low-leakage questions (<0.5 term overlap) represent realistic user phrasing where vocabulary mismatch causes retrieval failures.
  - Prior to this task, DocScout passes the literal query text to both dense embeddings and the BM25 analyzer without expansion, synonym handling, or hypothetical formulation.
- **Goal**:
  1. Implement a specialized domain query understanding and expansion engine in `app/retrieval/expansion.py`:
     - Acronym and canonical concept expansion for RBI/SEBI regulatory terms.
     - Bidirectional expansion (acronym -> full expansion, full term -> acronym).
     - Optional HyDE (Hypothetical Document Embeddings) formulation for semantic density.
  2. Integrate expansion into `RetrievalConfig` (`expansion: Literal["none", "synonym", "hyde", "combined"] = "none"`, `expand_query: bool = False`) and `Retriever` in `app/retrieval/search.py`.
  3. Wire expansion into the evaluation runner (`app/evals/runner.py`) as a formal comparison configuration (`hybrid-expanded`).
  4. Measure performance across the leakage bands (specifically `<0.5` low leakage band), reporting paired bootstrap confidence intervals, McNemar discordant pairs, latency overhead, and token cost.
  5. Author ADR-0017 documenting the expansion strategy, leakage band results, and defending the serving default.
  6. Write tests in `tests/test_query_expansion.py` validating expansion accuracy, token safety, and zero regression.

---

## Technical Design

### 1. Regulatory Domain Expander (`app/retrieval/expansion.py`)
- High-precision domain dictionary covering RBI and SEBI regulatory vocabulary:
  - Financial entities: PA/Payment Aggregator, NBFC, RE/Regulated Entity, CIC, AIF, KRA, DP.
  - Compliance frameworks: KYC/Know Your Customer, CKYC, PMLA, FATCA, CRS, LEI, LRS.
  - Market operations: FPI, T+1/settlement cycle, ODR, SCRR, SCRA, ESG, SRO, PPI.
- Word boundary regex matching (`\bPA\b`, `\bKYC\b`) prevents substring false positives (e.g. "company" matching "PA").
- Returns:
  - `lexical_query`: original query appended with canonical synonyms/abbreviations for BM25 term enrichment.
  - `dense_query`: semantically enriched query for vector embedding.
  - `metadata`: record of matched terms and applied expansions.

### 2. Retrieval Configuration (`app/retrieval/types.py`)
- Add `expand_query: bool = False` and `expansion_mode: str = "none"` to `RetrievalConfig`.
- Provenance records expansion parameters for eval reporting (E-14).

### 3. Retrieval Execution (`app/retrieval/search.py`)
- In `Retriever.retrieve()`:
  - If expansion is enabled, pass expanded queries to the dense and lexical arms respectively.
  - Compute latency delta.

### 4. Evaluation Harness Integration (`app/evals/runner.py`)
- Include `RetrievalConfig(name="hybrid-expanded", mode="hybrid", expand_query=True, ...)` in `BASELINE_CONFIGS`.
- Report low-leakage band recall, bootstrap CI, and latency trade-off.

---

## Verification & Quality Gates
1. Unit and integration tests in `tests/test_query_expansion.py`.
2. Full test suite (485+ tests) green.
3. `uv run python -m app.evals.runner` generates updated `report.md` with leakage band comparisons.
4. `uv run python -m app.evals.gate` passes regression check.
5. All linters (`ruff check`, `ruff format`, `mypy`) clean.
