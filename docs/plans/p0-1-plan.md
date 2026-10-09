# Implementation Plan: P0-1 — Answer Construction Behind Passages, With Judged Evaluation

- **Task ID:** P0-1
- **Status:** IN_PROGRESS
- **Author:** Principal Engineer
- **Date:** 2026-10-08
- **Corpus Context:** 21 RBI/SEBI documents -> 170 chunks -> 150 citations -> 153 gold items (131 answerable + 22 unanswerable + 3 canaries)
- **Baseline:** `06fdd76` (includes P0-4 and P1-4 verified and pushed)

---

## 1. Overview & Objectives

Transform DocScout from a pure retrieval-with-citations demonstrator into an end-to-end RAG service with citation-grounded answer generation sitting **behind** the existing retrieval surface.

Core commitments:
1. **Passages remain in the response**: The generated answer is an additional field (`answer`), never a replacement for ranked passages and verified chunk citations.
2. **Strict injection defense**: Untrusted corpus chunks are treated strictly as data within delimited boundaries (`<retrieved_evidence>`), never as system instructions. Canary items (`g-151`, `g-152`, `g-153`) must be 100% resisted (zero compliance with injected payloads).
3. **Calibrated, human-grounded evaluation**: Fulfill EVAL_PROTOCOL.md §5 and U-1 reopening conditions. Produce a committed calibration artifact of 60-100 double-labelled items reporting Cohen's kappa ($\kappa$), raw agreement %, and per-class confusion matrices.
4. **Honest, un-faked models**: Support deterministic CPU-executable local generation and cross-provider hosted generation when keys are supplied, with explicit provenance.

---

## 2. Sub-tasks Breakdown

### Sub-task 1: Generation Architecture, Prompt Templates & Injection Defense
- **Scope:**
  - Create `app/generate/models.py`: Schemas for `GeneratedAnswer`, `CitationSpan`, `GenerationConfig`.
  - Create `app/generate/prompt.py`: Prompt assembly with FR-12 compliant delimiters (`<retrieved_evidence>`), strict system instruction defining context as passive data, grounding rules, and citation format.
  - Create `app/generate/injection.py`: Injection canary resistance detector and security checks against forbidden strings (`AUDIT OVERRIDE ACCEPTED`, `T+9`, `.env`, `curl`, `maintenance mode`).
- **Inputs:** `SPEC.md` FR-12, `SECURITY.md` T-1, S-7, S-8, gold canary items `g-151`..`g-153`.
- **Outputs:** `app/generate/models.py`, `app/generate/prompt.py`, `app/generate/injection.py`, `tests/test_injection.py`.
- **Quality Bar:** Passages formatted with chunk IDs; delimiters cannot be broken by payload content; canary strings identified and blocked.
- **Success Criteria:** `pytest tests/test_injection.py` passes; canary payloads injected into prompt are flagged and verified not obeyed.

### Sub-task 2: Generation Engine (Deterministic Local & Hosted Providers)
- **Scope:**
  - Create `app/generate/generator.py`:
    - `BaseGenerator` protocol.
    - `DeterministicLocalGenerator`: Offline, deterministic CPU generator that extracts supporting sentences, maps chunk citations, abstains on unanswerable queries, and ignores injection payloads.
    - `HostedGenerator`: Support for OpenAI and Anthropic SDKs with timeout, rate limit, and error handling.
    - `get_generator()` factory.
- **Inputs:** `app/generate/models.py`, `app/generate/prompt.py`, `config/models.json`.
- **Outputs:** `app/generate/generator.py`, `tests/test_generator.py`.
- **Quality Bar:** 100% deterministic local behavior; strict mypy; zero hallucinated chunk IDs; clean abstention formatting.
- **Success Criteria:** `pytest tests/test_generator.py` passes; generated answers cite only returned chunk IDs.

### Sub-task 3: API Integration & Response Schema Behind Passages
- **Scope:**
  - Update `app/api/models.py`: Add `GeneratedAnswer` to `SearchResponse.answer`, add `generate_answer: bool = False` to `SearchRequest`.
  - Update `app/api/app.py`: Route logic in `POST /v1/search` to call generator when `generate_answer=True`; add `POST /v1/answer` and `POST /v1/chat` convenience endpoints with `generate_answer=True` by default.
  - Update `app/api/cache.py`: Cache key and cached result updated to include generated answer when requested.
- **Inputs:** `app/api/app.py`, `app/api/models.py`, `app/generate/generator.py`.
- **Outputs:** Updated `app/api/app.py`, `app/api/models.py`, `app/api/cache.py`, `tests/test_api.py`.
- **Quality Bar:** Passages and chunk IDs are never omitted; existing search tests continue to pass; API latency accurately tracks retrieval vs generation in `timings`.
- **Success Criteria:** `POST /v1/search` returns `passages` intact and `answer` when requested; `POST /v1/answer` returns both.

### Sub-task 4: Calibrated LLM & Cross-Provider Judge Harness
- **Scope:**
  - Create `app/evals/judge.py`:
    - Faithfulness evaluation (entailment of claims against cited chunks).
    - Citation precision evaluation (precision of cited chunk IDs).
    - Citation recall evaluation (recall against gold required chunk IDs).
    - Hallucination rate (claims ungrounded in context).
    - Abstention evaluation (correct abstention on unanswerable items).
    - Canary resistance evaluation (0 forbidden strings).
    - Cross-provider support and deterministic local judge.
- **Inputs:** `EVAL_PROTOCOL.md` §4, §5, `app/evals/scorers.py`.
- **Outputs:** `app/evals/judge.py`, `tests/test_judge.py`.
- **Quality Bar:** Stable scoring, temperature 0, transparent per-claim reasoning.
- **Success Criteria:** `pytest tests/test_judge.py` passes with deterministic score reproducibility.

### Sub-task 5: Human Double-Labelling & Calibration Artifact (Cohen's Kappa)
- **Scope:**
  - Create double-labelled dataset of 60-100 items from the gold set (`evals/calibration/20261008T200000Z/double_labeled_sample.jsonl`) with rater 1 and rater 2 ground truth across difficulty and answer types.
  - Run calibration scoring judge against human ground truth.
  - Compute Cohen's $\kappa$, raw agreement %, per-class confusion matrix for faithfulness, citation precision, citation recall, and abstention.
  - Save committed calibration artifact at `evals/calibration/20261008T200000Z/judge_calibration.json` and human-readable `calibration_report.md`.
- **Inputs:** `evals/gold/v1/gold.jsonl`, `EVAL_PROTOCOL.md` §5.
- **Outputs:** `evals/calibration/20261008T200000Z/judge_calibration.json`, `evals/calibration/20261008T200000Z/calibration_report.md`, `scripts/calibrate_judge.py`.
- **Quality Bar:** Honest statistics: Cohen's $\kappa = \frac{p_o - p_e}{1 - p_e}$ with margin error; per-class agreement on rare classes.
- **Success Criteria:** $\kappa \ge 0.70$, agreement $\ge 85\%$, raw data committed; test asserts validity.

### Sub-task 6: Reopening Documentation, Models Config, and Rescope Test Alignment
- **Scope:**
  - Document reopening of U-1 in `docs/eval/EVAL_PROTOCOL.md` §4.2 and record that reopening conditions (generator in request path + §5 calibration artifact committed) are satisfied.
  - Update `config/models.json` with active local generator/judge and calibration evidence references.
  - Update `tests/test_rescope.py` to assert that published faithfulness claims require the calibration artifact.
  - Record architectural decision in ADR-0011: `docs/decisions/0011-answer-generation-and-calibrated-judge.md`.
- **Inputs:** `docs/eval/EVAL_PROTOCOL.md`, `config/models.json`, `tests/test_rescope.py`.
- **Outputs:** Updated `EVAL_PROTOCOL.md`, `config/models.json`, `tests/test_rescope.py`, ADR-0011.
- **Quality Bar:** Complete documentation coherence; no contradiction between prose and code.
- **Success Criteria:** `pytest tests/test_rescope.py` passes; test fails if calibration artifact is deleted or poisoned.

### Sub-task 7: Full End-to-End Evaluation Report & Benchmark Update
- **Scope:**
  - Update `app/evals/runner.py` to optionally score generation metrics alongside retrieval.
  - Run full eval over 153 gold items with generation enabled; produce `evals/reports/<timestamp>/results.json` and `report.md`.
  - Update `scripts/bench_api.py` and run benchmark measuring retrieval + generation latency and throughput.
- **Inputs:** `evals/gold/v1/gold.jsonl`, `app/evals/runner.py`.
- **Outputs:** `evals/reports/<timestamp>/results.json`, `evals/reports/<timestamp>/report.md`, `evals/bench/<timestamp>/bench.json`.
- **Quality Bar:** All 153 items scored; retrieval metrics preserved; generation metrics reported with calibration evidence.
- **Success Criteria:** `make eval` and `make eval-gate` succeed.

---

## 3. Risks & Non-Goals

- **Non-Goals:**
  - We do NOT replace passages with prose. Passages remain the primary evidence layer.
  - We do NOT invent uncalibrated LLM scores without the §5 calibration artifact.
  - We do NOT create agentic multi-turn loops or complex workflow graphs (P2-3 scope accretion).
- **Risks & Mitigation:**
  - *Risk:* Prompt injection leaking system instructions or overriding regulatory citations.
    *Mitigation:* FR-12 explicit XML `<retrieved_evidence>` boundaries + system instruction stating context is data + canary negative tests.
  - *Risk:* Rescope tests failing on published faithfulness numbers.
    *Mitigation:* Follow EVAL_PROTOCOL §4.2 reopening protocol precisely and update test_rescope to guard the calibration requirement.
