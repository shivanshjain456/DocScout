# ADR-0068: Confidence-Calibrated Selective Refusal (FEAT-077)

* **Status:** Accepted
* **Date:** 2026-10-15
* **Deciders:** DocScout Core Engineering Team
* **Consulted:** AI Safety and Hallucination Prevention Guild, Regulatory Legal Engineering
* **Informed:** Core Platform Engineers, Product Operations

---

## Context and Problem Statement

A compliance research assistant that returns confident citations for a question its regulatory corpus cannot answer is more dangerous than an outright refusal. If a user asks "What is the penalty for failing to register a payment aggregator within 90 days?" and the corpus contains general payment aggregator rules but no penalty clause, an uncalibrated LLM generation engine will often hallucinate plausible penalty figures or cite adjacent irrelevant sections.

Under regulatory compliance scrutiny, DocScout operates under the strict principle: "Every answer cites its source or it refuses to answer."

While the baseline evidence coverage heuristic (`app/retrieval/confidence.py`) identified when queries had low term overlap against retrieved chunks, it was merely an observational flag (`low_evidence = True`), never an active abstention gate. FEAT-077 upgrades the confidence assessment architecture into a confidence-calibrated selective refusal gate (Abstention Gate). When the coverage score falls below 0.65, the system asserts `is_refusal = True`, sets `level = "LOW"`, records structured refusal rationale, and completely suppresses speculative answer generation.

---

## Decision Drivers

1. **Selective Refusal Invariant:** Explicit refusal on all unanswerable or unsupported questions; zero hallucinated speculative answers when evidence coverage is low.
2. **Deterministic Coverage Metric:** Maintain an evidence coverage score based on normalized query term intersection across the top-5 retrieved passages.
3. **Calibrated Thresholds:**
   * High Confidence ($\ge 0.85$): Full answer generation permitted; high evidence density.
   * Medium Confidence ($0.65 \le \text{score} < 0.85$): Answer generation permitted with standard provenance citations.
   * Low Confidence / Refusal ($< 0.65$): Explicit refusal triggered; speculative answer generation completely suppressed.
4. **Sub-0.2 ms Execution Latency:** In-memory set intersection and calibration scoring executed in $\le 0.2\text{ ms}$ on CPU.
5. **Fail-Closed Fallback:** If confidence calculation encounters unexpected runtime exceptions, default conservatively to explicit refusal (`is_refusal = True`) to prevent hallucinations.
6. **Zero Memory Overhead:** Pure in-memory calculation with zero persistent storage requirements.
7. **Observability:** Track abstention events via `docscout_abstention_events_total{level}` counter and `docscout_confidence_scores` histogram.
8. **Strict Typographical Compliance:** Strict ASCII typographical compliance across all documentation and code.

---

## Considered Options

1. **Self-Consistency LLM Sampling (Temperature Sampling):**
   * Sample 5 completions and refuse if outputs disagree.
   * *Drawbacks:* Multiplies LLM inference cost and latency by 5x (adding 1.5 - 3.0s per request).
2. **Post-Generation Hallucination Classifier (NLI Judge):**
   * Run a secondary cross-encoder or NLI model over every claim.
   * *Drawbacks:* High latency overhead (100 - 300 ms) and fails to prevent generation upfront.
3. **Calibrated Evidence Coverage Abstention Gate (Chosen):**
   * Measure normalized query term coverage across top-5 retrieved chunks using set intersection.
   * Calibrate refusal threshold at 0.65, achieving high separation between answerable and unanswerable questions.
   * If coverage falls below 0.65, trigger structured refusal, set `is_refusal = True`, and suppress speculative generation.

---

## Decision Outcome

Adopt Option 3.

### Implementation Specifics

1. **Configuration Schema (`ConfidenceConfig`):**
   * `low_evidence_threshold: float = 0.65`
   * `coverage_depth: int = 5`
2. **Output Schema (`Confidence`):**
   * `score: float`
   * `level: Literal["HIGH", "MEDIUM", "LOW"]`
   * `is_refusal: bool`
   * `refusal_reason: Optional[str]`
   * Backward-compatible fields: `evidence_coverage: float`, `missing_terms: list[str]`, `low_evidence: bool`, `passages_considered: int`.
3. **Direct Passage Evaluator (`assess_passages`):**
   * Supports `assess_passages(query: str, passages: list[Any], config: Optional[ConfidenceConfig] = None) -> Confidence`.
   * Input validation: `len(passages) >= 1`.
4. **Answer Suppression (`app/api/app.py`):**
   * When `confidence.is_refusal` is True, suppress `generated_answer = None` even when `payload.generate_answer = True`.
5. **Observability (`app/api/metrics.py`):**
   * `ABSTENTION_EVENTS_TOTAL = Counter("docscout_abstention_events_total", ..., ["level"])`
   * `CONFIDENCE_SCORES = Histogram("docscout_confidence_scores", ...)`
