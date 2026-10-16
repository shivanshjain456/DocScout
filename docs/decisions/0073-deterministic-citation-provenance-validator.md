# ADR-0073: Deterministic Citation Provenance Grounding Validator (FEAT-082)

* **Status:** Accepted
* **Date:** 2026-10-16
* **Deciders:** DocScout Core Engineering Team
* **Consulted:** AI Safety & Assurance Guild, Retrieval Engineering, Legal Compliance Engineering
* **Informed:** Core Platform Engineers, Product Operations

---

## Context and Problem Statement

In enterprise regulatory compliance (covering RBI Master Directions, SEBI regulations, and NHB mandates), answers delivered to auditors, compliance officers, and fintech engineers must have verifiable, tamper-evident provenance. As established in ADR-0008 ("Serve Evidence, Not Answers"), synthetic text is acceptable only when every single factual proposition is explicitly anchored to retrieved evidence chunks.

A common failure mode in generative compliance assistants is "citation drifting" or "unsourced extrapolation":
1. Sentences appear in the generated prose with no citation markers at all.
2. Citation markers refer to out-of-bounds indices (e.g., `[ID:8]` when only 5 passages were returned).
3. Citation markers reference chunk IDs that do not exist in the retrieved result set or database.
4. Factual propositions cite an evidence chunk whose textual premise does not cover or support the asserted statement.

FEAT-082 resolves this by providing a deterministic, offline Citation Provenance Grounding Validator that runs in sub-millisecond time (< 0.4ms) with zero external model dependencies.

---

## Decision Drivers

1. **Strict Provenance Verification:**
   Verify that every factual proposition contains an explicit `[ID:N]` marker (or valid chunk ID) mapping to a retrieved chunk ID that exists and covers the claim.
2. **Deterministic Index & UUID Validation:**
   Ensure all citation indices `N` in `[ID:N]` are valid 1-based integers `1 <= N <= len(passages)`. If chunk IDs are cited directly, verify their existence in the retrieved passages.
3. **Evidence Overlap Check:**
   Verify that the cited evidence passage actually covers the proposition via lexical/token overlap (>= `min_overlap_threshold`).
4. **Sanitization and Fallback Behavior:**
   In `strict_mode = True`, any ungrounded sentence triggers immediate sanitization: ungrounded sentences are stripped, retaining only strictly cited and grounded propositions. If no grounded sentences remain, fall back to suppressing the synthetic answer (ADR-0008 mode).
5. **Observability & Telemetry:**
   Export Prometheus counter `docscout_citations_validated_total` with status labels (`valid`, `invalid`, `ungrounded`, `sanitized`).
6. **Sub-millisecond Latency Budget:**
   Execution latency <= 0.4ms on multi-core CPU, with zero model downloads or API dependencies.
7. **Typographical Invariant:** Strict ASCII typographical compliance across all documentation and code.

---

## Decision Outcome

We implement `CitationValidator` in `app/evals/citation_validator.py` with:
- `CitationValidatorConfig(strict_mode: bool = True, min_overlap_threshold: float = 0.35)`
- `CitationValidationResult(is_grounded: bool, valid_citations_count: int, invalid_citations: list[str], ungrounded_sentences: list[str], sanitized_answer: str, total_sentences: int, grounded_sentences_count: int)`
- Post-generation validation filter in `app/api/app.py` before returning `SearchResponse`.
- Prometheus counter `CITATIONS_VALIDATED_TOTAL` in `app/api/metrics.py`.

---

## Pros and Cons of the Options

### Option 1: LLM-Based Citation Checker
* *Pros:* Can understand nuanced linguistic paraphrasing.
* *Cons:* Adds 400-1500ms latency, high token cost, non-deterministic, violates the 0.4ms budget.

### Option 2: Deterministic AST & Regex Lexical Validator (Chosen)
* *Pros:*
  * Sub-millisecond execution (< 0.1ms measured).
  * 100% deterministic and predictable.
  * Catches invalid indices, out-of-range citations, missing citations, and non-overlapping evidence passages.
  * Provides automatic sanitization to strip ungrounded statements while preserving verified claims.
* *Cons:* Requires structured citation conventions (`[ID:N]` or `[chunk_id]`).

---

## Validation and Testing

1. Unit tests covering citation parsing, out-of-bounds indices, missing citations, and span overlap validation in `tests/test_citation_validator.py`.
2. Sanitization tests verifying ungrounded sentence stripping.
3. Latency benchmark verifying execution time <= 0.4ms.
4. Prometheus metrics registration verification.
