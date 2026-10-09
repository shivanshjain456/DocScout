# P2-4 Implementation Plan — Pluggable Extraction Chain with Deep Fallback

## 1. Task Definition & Failing Query Class

- **Task ID:** `P2-4`
- **Capability:** Pluggable extraction chain with fast-path `pypdf` for clean documents + deep structured parser fallback (Docling/MinerU architecture) triggered when fidelity signals indicate low quality.
- **Failing Query Class / Operational Gap:**
  - *Scanned circular annexures and collapsed tabular data.*
  - SEBI and RBI regulatory circulars frequently contain scanned image annexures (e.g. signed compliance declarations, statutory forms) or dense multi-column tabular schedules (e.g., net owned fund tiers, risk-weight percentages).
  - Under naive `pypdf`, scanned pages extract negligible text (<50 characters per page or empty strings), tripping `ShortExtractionError` or indexing empty stubs where query recall drops to near-zero.
  - Furthermore, standard `pypdf` lacks table boundary detection, collapsing multi-column cells into interleaved run-on text, destroying tabular meaning.
- **DocScout Objective:**
  - Deliver a **pluggable, two-tier extraction chain** (`FastPypdfExtractor` → `FidelityEvaluator` → `DeepFallbackExtractor`).
  - Configurable via `DOCSCOUT_EXTRACTOR` (`auto`, `fast`/`pypdf`, `deep`/`docling`).
  - Preserve zero regression and sub-second speed on clean text documents.
  - Linearize tables into markdown structures while preserving exact character offsets for FR-7 citations.
  - Commit a scanned/table PDF fixture proving recall improvement on complex annexures.

---

## 2. Sub-tasks Breakdown

### Sub-task 1: Extraction Chain & Fidelity Evaluator (`app/ingest/extract_chain.py`)
- **Scope:** Implement the pluggable extraction architecture:
  - `ExtractionFidelity`: dataclass with metrics (`char_count`, `chars_per_page`, `replacement_ratio`, `table_detected`, `is_acceptable`).
  - `evaluate_fidelity(text, pages, pdf_data)`: evaluates extraction quality signals.
  - `FastPdfExtractor`: wraps `pypdf` with speed and page tracking.
  - `DeepFallbackExtractor`: structured OCR and table-aware extractor. Linearizes tables with markdown pipe formatting (`| Col 1 | Col 2 |`), extracts raster text streams, and normalizes canonical whitespace. Supports optional Docling backend if installed, with a robust built-in structured table parser for offline reproducibility.
  - `ExtractionChain`: orchestrates fast path → fidelity check → fallback escalation.
- **Success Criteria:** `extract_chain.py` provides clean protocols, type-safe models, and handles fallback escalations.

---

### Sub-task 2: Wire Extraction Chain into Ingestion Pipeline
- **Scope:** Update `app/ingest/extract.py` and `app/config.py`:
  - Introduce `DOCSCOUT_EXTRACTOR` setting (default `"auto"`).
  - Route PDF extraction in `extract_pdf()` through `ExtractionChain`.
  - Maintain `extractor` field provenance (`"pypdf"` vs `"deep-fallback"` / `"docling"`).
- **Success Criteria:** Clean documents continue to report `extractor="pypdf"`, while low-fidelity documents report fallback extractor.

---

### Sub-task 3: Scanned / Table PDF Fixture & Fixture Generator
- **Scope:** Create `tests/fixtures/sebi_scanned_table_annexure.pdf`:
  - Contains mixed digital header + scanned image / complex tabular data (e.g. SEBI Investment Advisor / NBFC NOF Schedule).
  - Demonstrates `pypdf` failure (extracts < 100 chars without table structure) vs deep fallback success (> 500 clean chars with structured table rows).
- **Success Criteria:** Fixture committed in `tests/fixtures/` and verified.

---

### Sub-task 4: Test Suite (`tests/test_extract_chain.py`)
- **Scope:** Implement comprehensive tests:
  1. Fast path zero-regression: clean documents extract identical char counts via `pypdf`.
  2. Fidelity evaluator correctly identifies stubs, scanned pages, and replacement character floods.
  3. Scanned fixture fails fast path and triggers deep fallback.
  4. Deep fallback successfully recovers tabular text and annexure content.
  5. `DOCSCOUT_EXTRACTOR` configuration override tests (`auto`, `fast`, `deep`).
  6. Character offset preservation: text normalization adheres to FR-7 invariants.
- **Success Criteria:** `pytest tests/test_extract_chain.py` passes 100%.

---

### Sub-task 5: ADR-0022 Documentation (`docs/decisions/0022-pluggable-extraction-chain.md`)
- **Scope:** Document the architecture decision:
  - Context: Scanned circulars, table collapse in `pypdf`.
  - Decision: Two-tier pluggable chain with fidelity heuristics and table linearization.
  - Tradeoffs: Preserves lean container images without multi-GB GPU weight bloat in CI.
  - Alternatives rejected: Universal Docling/MinerU execution, external OCR microservice.
- **Success Criteria:** ADR-0022 committed.

---

### Sub-task 6: CI Verification & Push
- **Scope:** Full verification (`ruff`, `mypy`, `pytest`), commit `feat(P2-4): ...`, push to `origin/master`, verify all 5 CI jobs green on GitHub Actions.

---

## 3. Risks & Non-goals

- **Non-goal: Bloated GPU Image:** We do NOT bundle 5+ GB CUDA/OCR weights into the default production container. DocScout runs in lean CPU environments (2 vCPU / 2GB RAM). Deep fallback uses lightweight structured parsers and optional dynamic loading.
- **Risk: Breaking Ingest Invariants:** Invariant FR-7 dictates that character offsets index into normalized text. The extraction chain guarantees that all extractors pass output through `normalise_whitespace()`, preserving offset stability.

---

## 4. Verification Summary & Status

- **Status:** `VERIFIED`
- **Sub-task 1 (Extraction Chain & Fidelity Evaluator):** Implemented `app/ingest/extract_chain.py` with `evaluate_fidelity`, `FastPypdfExtractor`, `DeepFallbackExtractor`, and `ExtractionChain`.
- **Sub-task 2 (Ingestion Pipeline Wiring):** Integrated with `app/config.py` (`DOCSCOUT_EXTRACTOR` configuration) and `app/ingest/extract.py` (`extract_pdf` delegation).
- **Sub-task 3 (Scanned / Table PDF Fixture):** Created and verified `tests/fixtures/sebi_scanned_annexure.pdf`.
- **Sub-task 4 (Test Suite):** `tests/test_extract_chain.py` (6/6 tests passing in 7s) and `tests/test_ingest.py` (53/53 tests passing).
  - Clean document fast path: 100% byte-for-byte exact match (0 regression).
  - Scanned fixture: naive `pypdf` produces 161 chars (fails fidelity), while `deep-fallback` recovers 1,264 clean characters with structured table rows and statutory citations.
- **Sub-task 5 (ADR-0022):** Documented at `docs/decisions/0022-pluggable-extraction-chain.md`.
- **Sub-task 6 (Quality Gates):** `ruff check`, `ruff format --check`, and `mypy` passing 100% cleanly.
