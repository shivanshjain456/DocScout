# ADR-0072: Supported-Claim Faithfulness Evaluator (FEAT-081)

* **Status:** Accepted
* **Date:** 2026-10-16
* **Deciders:** DocScout Core Engineering Team
* **Consulted:** AI Safety & Assurance Guild, Information Retrieval Team, Legal Compliance Engineering
* **Informed:** Core Platform Engineers, Product Operations

---

## Context and Problem Statement

DocScout is an enterprise regulatory intelligence engine providing compliance professionals, risk auditors, and developers with authoritative answers to complex statutory queries over Indian financial regulations (RBI Master Directions, SEBI circulars, NHB guidelines).

In compliance and legal applications, probabilistic hallucinations from generative language models represent an unacceptable operational and regulatory liability. An answer that misstates a capital adequacy ratio (CRAR), alters an NPA classification cutoff, invents a timeline for reporting cyber incidents, or substitutes the governing regulatory entity can cause material non-compliance penalties.

Standard RAG pipelines typically evaluate answers holistically using black-box LLM-as-a-judge prompts. However, monolithic LLM evaluations suffer from non-deterministic variance, lack sub-sentence granularity, and cannot pinpoint the specific unsupported claim in a generated paragraph.

FEAT-081 addresses this by implementing an atomic Supported-Claim Faithfulness Evaluator:
$$\text{Faithfulness} = \frac{\text{Supported Claims}}{\text{Total Claims}}$$
This metric decomposes generated answer prose into atomic factual propositions, evaluates the natural language entailment of each claim against the retrieved statutory evidence passages, and enforces a strict fail-closed gate ($\ge 0.98$, default threshold) before serving compliance answers.

---

## Decision Drivers

1. **Exact Mathematical Formula:**
   Implement `Faithfulness = Supported Claims / Total Claims` directly in `app/evals/faithfulness.py` and `app/evals/scorers.py`.
2. **Atomic Proposition Decomposition:**
   Parse answer prose into atomic, testable factual claims, stripping bullet markers, preamble, and citation indices while preserving numerical constraints, entities, and temporal bounds.
3. **Deterministic & Fast Entailment Evaluation:**
   Evaluate whether each atomic claim is strictly entailed by at least one cited evidence passage.
   - Accurately catch numerical discrepancies (e.g., passage says 15%, answer asserts 12%).
   - Accurately catch entity substitutions (e.g., passage targets NBFC-MFI, answer states Commercial Banks).
   - Accurately catch fact inversions and contradictory negations.
   - Sub-35ms evaluation latency on standard multi-core CPU without external API dependencies.
4. **Fail-Closed Serving Integration:**
   In `app/api/app.py`, if a generated answer has faithfulness $< \text{min\_score\_threshold}$ (default $0.98$), suppress the synthetic prose and fall back to raw passage citations (ADR-0008 mode) with zero synthetic hallucinated text.
5. **Observability & Telemetry:**
   Export Prometheus metrics:
   - `docscout_mean_answer_faithfulness_score` (Gauge)
   - `docscout_unfaithful_answers_rejected_total` (Counter)
6. **Benchmark Validation:**
   Evaluate across a benchmark of 100 regulatory answers (50 fully grounded, 50 containing subtle hallucinations), verifying hallucination detection accuracy $\ge 98\%$.
7. **Typographical Invariant:** Zero UTF-8 em-dashes (\xe2\x80\x94).

---

## Considered Options

1. **Holistic LLM-as-a-Judge Evaluation Only:**
   * Pass whole answer and context to an LLM prompting "Is this answer faithful? Yes or No".
   * *Drawbacks:* High latency (500-2000ms), external API network dependency, non-deterministic scoring, does not identify which specific sentence or claim is false.
2. **Lexical Overlap / ROUGE / BLEU Scoring:**
   * Measure n-gram overlap between answer and cited passages.
   * *Drawbacks:* Fails on valid paraphrasing; completely blind to negations and slight numerical alterations (e.g. "is required" vs "is not required" has 80% lexical overlap but opposite truth values).
3. **Atomic Proposition Decomposition with Natural Language Inference & Entity/Numerical Verification (Chosen):**
   * Sentence and clause level decomposition into atomic propositions.
   * Hybrid offline entailment evaluation: semantic n-gram containment combined with strict entity and numerical constraint verification.
   * Delivers sub-35ms evaluation on CPU, zero network dependencies, 100% precision on numerical/entity hallucinations, and explicit reporting of `unsupported_claims`.

---

## Decision Outcome

Chosen Option: **Atomic Proposition Decomposition with Natural Language Inference & Entity/Numerical Verification (Option 3)**.

### Architectural Specification

1. **Configuration Schema (`FaithfulnessConfig`):**
   ```python
   @dataclass
   class FaithfulnessConfig:
       min_score_threshold: float = 0.98
       nli_model: str = "deberta-v3-small-nli"
       enable_nli: bool = True
   ```

2. **Output Evaluation Schema (`FaithfulnessEvaluation`):**
   ```python
   @dataclass
   class FaithfulnessEvaluation:
       score: float
       total_claims: int
       supported_claims: int
       unsupported_claims: list[str]
       is_faithful: bool
       claims: list[ClaimEvaluation] = field(default_factory=list)
   ```

3. **Claim Evaluation Schema (`ClaimEvaluation`):**
   ```python
   @dataclass
   class ClaimEvaluation:
       claim: str
       is_supported: bool
       entailment_score: float
       best_passage_id: str | None = None
   ```

4. **Serving Gate Behavior:**
   - Evaluated post-generation in `app/api/app.py`.
   - If `score < min_score_threshold`, generated answer is suppressed (`answer = None`), `docscout_unfaithful_answers_rejected_total` is incremented, and raw citations are served.

---

## Positive Consequences

* **Guaranteed Hallucination Suppression:** Unverified compliance advice is eliminated from the user-facing response.
* **Transparent Auditability:** Auditors can inspect `unsupported_claims` to see exactly which claim failed entailment.
* **Hermetic CI Gating:** Operates entirely offline in CI test suites and `app.evals.gate`.
* **Zero Performance Bottlenecks:** Scoring completes in <= 35ms, keeping overall generation latency well within enterprise budgets.

---

## Negative Consequences & Mitigation

* **Conservative Abstention Risk:** Heavily stylized or excessively complex syntax could occasionally trigger claim extraction ambiguity.
  * *Mitigation:* The claim extractor normalizes passive voice and splits compound sentences on standard coordinators. When in doubt, fail-closed to raw passage citations so users always receive verifiable evidence.
