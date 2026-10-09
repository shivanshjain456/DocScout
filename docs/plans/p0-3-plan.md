# Plan: P0-3 — Corpus and Gold Scale Beyond Saturation

**Status:** VERIFIED
**Owner:** Principal Engineer
**Target:** Transform DocScout from an artificially saturated 170-chunk demonstrator to an unsaturated, statistically discriminative regulatory RAG evaluation environment with MDE $\le 1.0\text{ pp}$.

---

## 1. Problem Statement & Baseline Deficiencies

1. **Depth-10 Retrieval Saturation:**
   - On the baseline corpus of 21 documents (170 chunks), both `hybrid-rrf` and `bm25-only` achieved `recall@10 = 1.000` (`evals/reports/20261002T124408Z/report.md`).
   - At 100% recall, no architecture or reranking strategy can be differentiated; headroom is invisible.
2. **Imprecise Ruler & Gate Noise Floor:**
   - With only 131 answerable items, 1 item represents 0.76pp.
   - The minimum detectable effect (MDE) half-width was **3.24pp**, which exceeds the project's **1.0pp** regression gate threshold. A 1pp drop was indistinguishable from bootstrap resampling noise.
3. **Lexical Leakage Confound:**
   - The gold questions heavily mirrored circular phrasing (victim 0.733 vs random 0.094, 7.8× advantage).
   - The low-leakage band ($<0.5$ term overlap) contained only **$n=8$ items**, too small for statistical credibility.
4. **Undecided Corpus Decisions:**
   - `CORPUS_SPEC.md` C-3 (date window) and C-5 (target size) remained unresolved since Phase 0.

---

## 2. Architecture Decisions & Scope Resolution

1. **ADR-0012 (`docs/decisions/0012-corpus-and-gold-scale-beyond-saturation.md`):**
   - **Resolution of C-3 (Date Window):** RBI and SEBI publications across FY 2024–2026, targeting Master Directions, Notifications, and Circulars across Banking Regulation, NBFCs, Digital Lending, Cyber Security, Securities Issuance, LODR, and ESG Rating Providers.
   - **Resolution of C-5 (Target Size):** Expand corpus from 21 documents / 170 chunks to 35 documents / 350+ chunks (~340,000+ characters), introducing genuine cross-document regulatory distractors.
2. **Gold Set Version Bump (`v2.0.0`):**
   - Bump `goldset_version` from `1.0.0` to `2.0.0` in `evals/gold/v1/metadata.json`.
   - Scale from 153 to 425 total items (365 answerable + 60 unanswerable, $\ge 14\%$ unanswerable share, 3 canaries).
   - Populate low-leakage band ($<0.5$ term overlap) with 60+ natural paraphrased questions ($n \ge 50$).
   - With $N = 365$ answerable paired items, standard error drops such that paired bootstrap CI half-width is $\le 1.0\text{ pp}$.

---

## 3. Sub-Tasks & Implementation Steps

### Sub-Task 1: Corpus Expansion (`corpus/raw/` & `manifest.json`)
- Add 14 authentic RBI & SEBI regulatory documents (Documents 21 to 34), bringing total documents to 35 (18 RBI, 16 SEBI, 1 Canary).
- Create corresponding `.txt` extracted content with clean characters $> 500$ and valid PDF/document files in `corpus/raw/`.
- Compute and verify sha256 digests and byte sizes.
- Update `corpus/raw/manifest.json` with all 35 documents, updating header metadata (`attempted: 35`, `extracted_over_500_chars: 35`, `passed: true`, `sources: {RBI: 18, SEBI: 16}`).
- Verify allowlist compliance (`app/ingest/allowlist.py`) and manifest loading (`app/ingest/source.py`).

### Sub-Task 2: Gold Set Scaling & Paraphrased Queries (`gold.jsonl` & `metadata.json`)
- Author 272 new gold items (expanding from 153 to 425 items: items `g-154` to `g-425`).
- Ensure all 35 documents are covered by at least one gold item.
- Author 60+ low-leakage questions with paraphrased vocabulary ("Can an NBFC outsource loan approvals?", "What is the capital requirement for small finance banks?").
- Ensure every answerable item has grounded quotes and valid expected key points.
- Run `python -m app.evals.goldset pin` to deterministically pin all `required_citation_chunk_ids`.
- Run `python -m app.evals.goldset lint` and `python -m app.evals.goldset review` to confirm zero violations.
- Update `evals/gold/v1/metadata.json` with new hash, version `2.0.0`, composition, and labelling disclosure.

### Sub-Task 3: Ingest & Offsets Verification
- Start local database via docker compose if needed.
- Run `python scripts/migrate.py up`.
- Run `python -m app.ingest run` to ingest all 35 documents into postgres.
- Run `python -m app.ingest verify` (FR-7 offset check on all chunks).

### Sub-Task 4: Evaluation Run, Baseline Recording & Gate Verification
- Run `python -m app.evals.runner` (`make eval`).
- Verify in `report.md`:
  - `recall@10 < 1.000` for at least one configuration (proving depth-10 headroom exists).
  - Low-leakage band $n \ge 50$.
- Run `python -m app.evals.gate --accept` to record the new accepted baseline under `goldset_version: 2.0.0`.
- Run `python -m app.evals.gate` (`make eval-gate`):
  - Confirm `eval gate: PASS`.
  - Confirm `minimum_detectable_effect_pp <= 1.0` in `gate.json`.

### Sub-Task 5: ADR-0012, Documentation & Unit Tests
- Create `docs/decisions/0012-corpus-and-gold-scale-beyond-saturation.md`.
- Update `docs/corpus/CORPUS_SPEC.md` resolving C-3 and C-5.
- Update `docs/eval/EVAL_PROTOCOL.md` and `CHANGELOG.md`.
- Run test suite (`pytest`) and verify `test_goldset.py`, `test_ingest.py`, `test_gate.py`.

### Sub-Task 6: Verification, Commit & Push
- Run `pre-commit run --all-files`, `ruff check`, `mypy app`.
- Commit atomically and push to `origin/master`.
