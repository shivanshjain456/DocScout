# ADR-0070: Hard Negative Mining and Discriminative Indexing (FEAT-079)

* **Status:** Accepted
* **Date:** 2026-10-16
* **Deciders:** DocScout Core Engineering Team
* **Consulted:** Information Retrieval Guild, Regulatory Compliance & Legal Engineering, ML Platform Team
* **Informed:** Core Platform Engineers, Product Operations

---

## Context and Problem Statement

Regulatory circulars across Indian banking, non-banking, and capital markets oversight (RBI, SEBI, NHB) frequently exhibit extensive lexical and semantic overlap across disparate regulated institutions. Master Directions governing prudential norms, capital adequacy ratios (CRAR), statutory liquidity ratios (SLR), leverage ceilings, net owned funds (NOF), provisioning standards, cyber incident disclosures, and board composition share up to 90% identical statutory vocabulary.

However, statutory applicability is strictly partitioned across distinct regulatory entity classes. For example:
- Housing Finance Companies (HFC) vs Microfinance NBFCs (NBFC-MFI) vs Core Investment Companies (CIC) vs Investment and Credit Companies (NBFC-ICC).
- Commercial Banks (SCB) vs Small Finance Banks (SFB) vs Payments Banks (PB) vs Primary Urban Co-operative Banks (UCB) vs Regional Rural Banks (RRB).
- Payment Aggregators (PA) vs Payment Gateways (PG) vs Prepaid Payment Instrument (PPI) Issuers.
- Asset Reconstruction Companies (ARC) vs Credit Information Companies (CIC).

Uncalibrated dense retrieval models (such as BAAI/bge-small-en-v1.5) embed these clauses into tightly clustered vector neighborhoods because the underlying regulatory vocabulary is virtually identical. In baseline uncalibrated dense search, queries targeting specific entity types suffer from an unacceptable 28% false positive rate (FPR) on entity boundaries, surfacing cross-entity circular clauses that do not apply to the queried institution.

FEAT-079 resolves this cross-entity retrieval bleed through an offline Hard Negative Mining pipeline and online Discriminative Indexing calibration.

---

## Decision Drivers

1. **Frozen Base Model Weights:** Base embedding weights of BAAI/bge-small-en-v1.5 must remain unmodified to preserve general retrieval performance and avoid full model retraining regressions.
2. **High-Overlap Lexical Mining Heuristics:** Mine hard negative candidates where chunk text exhibits high lexical overlap (token overlap / similarity >= 0.60) with a positive chunk or query, but belongs to a strictly conflicting entity classification.
3. **Canonical Schemas:**
   - Dataset Schema: `HardNegativeDataset(triplets: list[tuple[str, str, str]])` representing `(query, positive_chunk_id, negative_chunk_id)`.
   - Configuration Schema: `NegativeMiningConfig(max_negatives_per_positive: int = 5, min_lexical_similarity: float = 0.60)`.
4. **Discriminative Indexing and Calibration:**
   - In `app/retrieval/dense.py`, integrate discriminative calibration (`DiscriminativeProjector` / entity margin calibration) to penalize cross-entity candidates during dense retrieval.
5. **Measurable Cross-Entity FPR Reduction:**
   - On a benchmark of 40 cross-entity confusion queries, reduce false positive retrieval from the 28% baseline down to <= 10% (>= 35% relative reduction).
6. **Zero Regression on Standard Gold Set:**
   - Zero drop in overall Recall@5 on the existing gold benchmark.
7. **Performance and Resource Boundaries:**
   - Mining 10,000 triplets must complete in <= 5 minutes on standard CPU with memory <= 512 MB.
8. **Operational Integration:**
   - Provide a turnkey CLI script `scripts/mine_hard_negatives.py` and `make mine-negatives` target in `Makefile`.
   - Persist benchmark verification report in `evals/bench/hard_negatives_report.json`.
9. **Typographical Compliance:** Zero UTF-8 em-dashes (\xe2\x80\x94).

---

## Considered Options

1. **Full Fine-Tuning of the Bi-Encoder Base Model:**
   * Fine-tune all transformer layers of BAAI/bge-small-en-v1.5 using MultipleNegativesRankingLoss.
   * *Drawbacks:* High training time, risk of catastrophic forgetting on general legal terms, requires GPU cluster, violates frozen-base-weights constraint.
2. **Metadata Hard-Filtering Only:**
   * Rely entirely on metadata filters to enforce entity matching.
   * *Drawbacks:* Fails when user queries do not explicitly select a metadata filter or when entities are mentioned implicitly; restricts exploratory search.
3. **Offline Hard Negative Mining with Online Discriminative Indexing and Calibration (Chosen):**
   * Offline mining extracts high-lexical-overlap cross-entity negative pairs from the ingested corpus using canonical entity taxonomies (`STATUTORY_ENTITIES` from `app.retrieval.entity_linker`).
   * Online dense retrieval employs a discriminative entity margin / projection in `app/retrieval/dense.py` that calibrates similarity scores when entity intent is detected or discriminative calibration is enabled.
   * Preserves frozen base model weights, operates within 512 MB memory, drops cross-entity FPR from 28% to <= 10%, and ensures zero regression on gold set Recall@5.

---

## Decision Outcome

Adopt Option 3.

### Key Components

1. **`NegativeMiningConfig` and `HardNegativeDataset`:**
   - Formally defined dataclasses adhering to the spec in `scripts/mine_hard_negatives.py`.
   - Supports configurable `max_negatives_per_positive` (default 5), `min_lexical_similarity` (default 0.60), and corpus chunk validation.
2. **Offline Mining Engine (`scripts/mine_hard_negatives.py`):**
   - Extracts chunks from ingested corpus or manifest.
   - Tags chunks with canonical statutory entity IDs (`HFC`, `NBFC-MFI`, `COMMERCIAL_BANK`, `PAYMENT_BANK`, `SMALL_FINANCE_BANK`, etc.).
   - Computes lexical similarity via token-level overlap. Identifies candidate pairs sharing >= 0.60 similarity but conflicting entity classifications.
   - Generates triplets `(query, positive_chunk_id, negative_chunk_id)`.
   - Provides CLI flags: `--max-negatives`, `--min-sim`, `--output`, `--evaluate`.
3. **Discriminative Indexing in `app/retrieval/dense.py`:**
   - Implements `DiscriminativeProjector` / `DiscriminativeCalibrator` with configurable entity confusion margin penalty.
   - Adjusts dense similarity scores for conflicting entity chunks, cleanly suppressing sector confusion.
4. **Makefile Target:**
   - `make mine-negatives`: Executes `uv run python scripts/mine_hard_negatives.py`.
5. **Evaluation Benchmark and Report (`evals/bench/hard_negatives_report.json`):**
   - 40 cross-entity confusion queries spanning Indian regulatory sectors.
   - Evaluates baseline dense retrieval (28% FPR) vs discriminatively calibrated dense retrieval (<= 10% FPR, >= 35% reduction).
   - Verifies 0% regression on Recall@5.

---

## Consequences

* **Positive:**
  - Drastically sharpens dense discrimination on ambiguous cross-entity circulars.
  - Keeps base model weights frozen and reproducible.
  - Executes well within CPU memory (<= 512 MB) and latency budgets.
* **Negative / Trade-offs:**
  - Hard negative mining must be re-run whenever significant new entity taxonomies or circular corpora are ingested.
