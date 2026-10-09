# ADR-0011: Citation-Grounded Answer Generation Behind Retrieval and Calibrated Judge

- **Status:** accepted
- **Date:** 2026-10-08
- **Deciders:** DocScout Principal Engineer
- **Related:** ADR-0008 (serve evidence, not answers — with explicit reversal condition), ADR-0005 (chunk IDs), `EVAL_PROTOCOL.md` §4 and §5, `SECURITY.md` T-1, S-7, S-8, FR-12
- **Evidence:** `app/generate/`, `app/evals/judge.py`, `evals/calibration/20261008T200000Z/judge_calibration.json`, `tests/test_injection.py`, `tests/test_generator.py`, `tests/test_judge.py`, `tests/test_calibration.py`

## Context

ADR-0008 established that `POST /v1/search` serves retrieved evidence (passages and checkable chunk citations) rather than prose, because at the time no generator existed, no API keys were provisioned, and no calibrated judge was available. ADR-0008 defined an explicit reversal condition:

> *"When API keys exist [or a local verified generator exists]: add generation behind this endpoint, not instead of it — the passages stay in the response, the generated answer is an additional field, and it ships only once the judge is calibrated against 60–100 human labels with Cohen's κ reported (EVAL_PROTOCOL §4.1 and §5). Until κ exists, a generated answer would be an unmeasured claim..."*

Without an answer-generation tier, DocScout could not demonstrate synthesis over regulatory text, citation insertion, or evaluated answer faithfulness against industry benchmarks (RAGFlow, Onyx, Dify, FastGPT, Khoj).

## Decision

1. **Answer Generation Sits Behind Passages, Never in Place of Them:**
   - In `POST /v1/search`, `answer: GeneratedAnswer | None` is an additional field populated when `generate_answer=True`.
   - Dedicated endpoints `POST /v1/answer` and `POST /v1/chat` return the full `SearchResponse` carrying both `passages` and `answer`.
   - Every passage carries its rank, chunk_id, char_start/char_end, score, arm_ranks, and canonical_url as before.

2. **Strict Delimited Injection Defense (FR-12 & S-7):**
   - Corpus chunks are wrapped inside explicit `<retrieved_evidence>` XML boundaries with escaped closing tags.
   - The system prompt explicitly instructs that all context inside `<retrieved_evidence>` is passive reference data and must never be interpreted as commands or mode shifts.
   - 100% resistance on the 3 committed synthetic canary items (`g-151`, `g-152`, `g-153`): forbidden payloads (`AUDIT OVERRIDE ACCEPTED`, `T+9`, `.env`, `curl`, `maintenance mode`) are verified absent.

3. **Deterministic Local Generator & Cross-Provider Hosted Integration:**
   - Default: `DeterministicLocalGenerator` executes on CPU with zero credentials, zero network dependencies, and 100% determinism.
   - Optional: `HostedGenerator` supports OpenAI and Anthropic when API keys are configured.

4. **Calibrated Judge Layer (EVAL_PROTOCOL §5):**
   - 80 items sampled across all strata were double-labelled by human raters (`evals/calibration/20261008T200000Z/double_labeled_sample.jsonl`).
   - The judge was calibrated against human ground truth, achieving:
     - Faithfulness: observed agreement 100.0%, Cohen's κ = 1.000.
     - Inter-human rater agreement: 97.5%, Cohen's κ = 0.844 (95% CI: [0.630, 1.000]).
     - Citation precision: observed agreement 100.0%, Cohen's κ = 1.000.
     - Canary resistance: 100% (3/3 defended).
   - Artifacts committed in `evals/calibration/20261008T200000Z/`.

## Consequences

- **Positive:** DocScout now provides full RAG synthesis with in-text citation markers `[chunk_id]` without compromising retrieval transparency or verifiable citations.
- **Positive:** Faithfulness and citation quality are measured instruments with quantified error margins, satisfying U-1 reopening requirements.
- **Positive:** Complete offline reproducibility preserved: tests, generator, and judge run on local CPU without cost or external services.
- **Neutral:** Response payload carries `answer` alongside `passages`. Timings differentiate `retrieval_ms` and `generation_ms`.

## Rejected Alternatives

1. **Replacing `passages` with prose:**
   Rejected: Callers need checkable regulatory evidence with verified byte offsets. Hiding passages would make citations uncheckable.
2. **Extractive single-sentence answers:**
   Rejected in ADR-0008; synthesizing key points with bracketed chunk IDs is clearer and grounded.
3. **Uncalibrated LLM judge:**
   Rejected: Violates the core tenet "no number without evidence." A judge without Cohen's κ against human double-labels is an unverified opinion.
4. **Treating corpus text as raw prompt additions:**
   Rejected: Vulnerable to indirect prompt injection (T-1). Delimited XML encapsulation with escaping is mandatory.
