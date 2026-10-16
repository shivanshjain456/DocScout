# Pillar 9 Specification: AI Assurance, Hallucination Prevention & Faithfulness Scoring
*DocScout Enterprise Regulatory Intelligence Engine*

---

## FEAT-081: Supported-Claim Faithfulness Evaluator
- **Objective:** Evaluate the exact formula `Faithfulness = Supported Claims / Total Claims` from `term-taxonomy.json.formulas` across generated answers using Natural Language Inference (NLI) to enforce 100% evidence entailment.
- **In-scope behavior:** Decomposing generated answer prose into atomic factual propositions; evaluating entailment of each claim against cited passages using an offline NLI model; computing numerical faithfulness ratio; rejecting answers with faithfulness $< 1.0$.
- **Excluded behavior:** Allowing probabilistic hallucinations to pass as valid compliance advice.
- **Implementation boundaries:** `app/evals/faithfulness.py`, `app/evals/scorers.py`.
- **Integration points:** CI evaluation harness `app/evals/runner.py`; post-generation verification gate in `app/api/app.py`.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`formulas` ["faithfulness"]), `app/evals/faithfulness.py`.
- **Supported inputs:** Generated answer `answer: str`, cited evidence passages `citations: list[Passage]`.
- **Input validation rules:** `answer` non-empty; at least 1 citation provided.
- **Output schema:** `FaithfulnessEvaluation(score: float, total_claims: int, supported_claims: int, unsupported_claims: list[str], is_faithful: bool)`.
- **Configuration schema:** `FaithfulnessConfig(min_score_threshold: float = 0.98, nli_model: str = "deberta-v3-small-nli")`.
- **Default values:** `min_score_threshold = 0.98`, `nli_model = "deberta-v3-small-nli"`.
- **Dependencies:** HuggingFace `transformers` NLI pipeline or fast ONNX runtime inference engine.
- **Compatibility requirements:** Runs offline in CI; zero external API dependencies.
- **Authorization rules:** Internal evaluation and generation verification component.
- **Data isolation rules:** Operates in-memory on generated answer candidates.
- **Error behavior:** If entailment model evaluation fails, reject generated answer and fall back to raw passage citations.
- **Fallback behavior:** Fail-closed: returns retrieved passages only (ADR-0008 mode) with zero synthetic prose.
- **Observability requirements:** Gauge `docscout_mean_answer_faithfulness_score`, counter `docscout_unfaithful_answers_rejected_total`.
- **Performance limits:** Faithfulness scoring completed in $\le 35.0\text{ ms}$ on 4-core CPU.
- **Resource limits:** Memory footprint $\le 120\text{ MB}$ for NLI model weights.
- **Acceptance criteria:** Enforces 100% citation entailment: zero answers with unverified claims are permitted through the serving gate.
- **Evaluation dataset:** 100 generated regulatory answers (50 fully grounded, 50 containing subtle hallucinations).
- **Evaluation baseline:** Unvalidated generation pipelines suffering 15-20% hallucination rates.
- **Required improvement threshold:** Hallucination detection accuracy $\ge 98\%$.
- **Regression limits:** Zero false rejection of valid, fully supported statutory claims.
- **Completion criteria:** Integrated into `make eval-gate` with verified passing baseline.

---

## FEAT-082: Deterministic Citation Provenance Grounding Validator
- **Objective:** Verify that every factual proposition contains an explicit `[ID:N]` marker mapping to a retrieved chunk ID that exists in the database and explicitly covers the proposition.
- **In-scope behavior:** AST and regex verification of citation markers in answer text; validating that cited chunk IDs exist in current database version; checking character span overlap between claim and cited text.
- **Excluded behavior:** Fuzzy citation references without precise chunk ID anchors.
- **Implementation boundaries:** `app/evals/citation_validator.py`, `app/api/models.py`.
- **Integration points:** Output validation filter in `app/api/app.py` before returning `SearchResponse`.
- **Source-of-truth files:** `app/evals/citation_validator.py`, `docs/decisions/0008-serve-evidence-not-answers.md`.
- **Supported inputs:** Answer text with citation markers `text: str`, returned passages `passages: list[Passage]`.
- **Input validation rules:** All citation indices `N` in `[ID:N]` must be valid 1-based integers $\le \text{len}(passages)$.
- **Output schema:** `CitationValidationResult(is_grounded: bool, valid_citations_count: int, invalid_citations: list[str], ungrounded_sentences: list[str])`.
- **Configuration schema:** `CitationValidatorConfig(strict_mode: bool = True)`.
- **Default values:** `strict_mode = True`.
- **Dependencies:** Pure Python regex and string parsing.
- **Compatibility requirements:** Sub-millisecond execution; zero model dependencies.
- **Authorization rules:** Internal validation middleware.
- **Data isolation rules:** In-memory verification.
- **Error behavior:** Any ungrounded sentence triggers immediate sanitization: ungrounded sentence stripped or replaced with refusal.
- **Fallback behavior:** Strips ungrounded claims, retaining only strictly cited sentences.
- **Observability requirements:** Counter `docscout_citations_validated_total{status}`.
- **Performance limits:** Validation execution latency $\le 0.4\text{ ms}$.
- **Resource limits:** Zero extra memory.
- **Acceptance criteria:** Citation Precision = 1.000 across all served answers (zero unsourced propositions).
- **Evaluation dataset:** All 365 answerable items in `evals/gold/v1/gold.jsonl`.
- **Evaluation baseline:** Current baseline citation precision = 1.000.
- **Required improvement threshold:** Citation precision maintained at 1.000 (zero regression).
- **Regression limits:** Gate fails if a single unsourced proposition is detected.
- **Completion criteria:** Validated in `tests/test_citation_validator.py`.

---

## FEAT-083: Adversarial Red-Teaming & Prompt Injection Shield
- **Objective:** Intercept prompt injection attacks, system prompt extractions, and malicious regulatory tampering attempts using a pre-retrieval security filter trained on the taxonomy's `Adversarial Prompt Corpus`.
- **In-scope behavior:** Analyzing query embeddings and token patterns against known prompt injection vectors (ignore previous instructions, roleplay jailbreaks, SQL injection in queries); blocking malicious queries with HTTP 400.
- **Excluded behavior:** Blocking legitimate complex regulatory queries that happen to discuss security vulnerabilities.
- **Implementation boundaries:** `app/api/security_shield.py`, `app/api/app.py`.
- **Integration points:** Inbound request middleware in `app/api/app.py`.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`security-appsec-testing`), `app/api/security_shield.py`.
- **Supported inputs:** Raw user query `query: str`, client IP `client_ip: str`.
- **Input validation rules:** Checked before any downstream database or model processing.
- **Output schema:** `SecurityShieldDecision(is_safe: bool, threat_type: Optional[str], threat_score: float, action: Literal["ALLOW", "BLOCK", "FLAG"])`.
- **Configuration schema:** `ShieldConfig(blocking_threshold: float = 0.88, rate_limit_on_attack: bool = True)`.
- **Default values:** `blocking_threshold = 0.88`, `rate_limit_on_attack = True`.
- **Dependencies:** Fast regex rule automata, lightweight linear classifier on query embeddings.
- **Compatibility requirements:** Sub-millisecond execution to prevent impacting legitimate search latency.
- **Authorization rules:** Publicly enforced across all incoming API traffic.
- **Data isolation rules:** Blocked attack payloads logged in isolated security audit ledger; client IP rate-limited.
- **Error behavior:** Blocked queries return HTTP 400 with "Invalid search query syntax" (refuses to disclose threat signature).
- **Fallback behavior:** Fails closed on extreme threat scores ($>0.95$).
- **Observability requirements:** Counter `docscout_security_threats_blocked_total{threat_type}`, security incident alerts.
- **Performance limits:** Security screening execution latency $\le 0.6\text{ ms}$ p95.
- **Resource limits:** Memory allocation $\le 4\text{ MB}$.
- **Acceptance criteria:** Blocks 100% of standard prompt injection benchmarks (e.g. BIU, JailbreakBench) while maintaining 0% false block rate on valid statutory queries.
- **Evaluation dataset:** 100 adversarial attack prompts + 100 legitimate complex regulatory queries.
- **Evaluation baseline:** 0% pre-retrieval adversarial filtering in baseline.
- **Required improvement threshold:** Attack detection rate $\ge 99\%$; false positive rate $\le 0.5\%$.
- **Regression limits:** Zero impact on legitimate search execution.
- **Completion criteria:** Security audit test suite passes in `tests/test_security_shield.py`.

---

## FEAT-084: Canary Token Provenance & Leakage Assertions
- **Objective:** Ingest synthetic circular fixtures containing cryptographic canary tokens (per taxonomy `Canary Token Assertions`) to mathematically prove zero cross-tenant leakage or synthetic data contamination.
- **In-scope behavior:** Planting unique cryptographic canary strings (e.g. `CANARY-UUID-SECRET`) in synthetic evaluation documents; running automated assertion suites querying across production endpoints; verifying 100% non-emergence of canary strings.
- **Excluded behavior:** Deploying canary tokens into real regulatory documents.
- **Implementation boundaries:** `app/evals/canary.py`, `migrations/0010_synthetic_artifact_provenance.up.sql`.
- **Integration points:** Automated CI security job; `scripts/verify_canaries.py`.
- **Source-of-truth files:** `app/evals/canary.py`, `corpus/raw/manifest.json`.
- **Supported inputs:** Ingested corpus documents, canary registry table `canary_tokens`.
- **Input validation rules:** Canary tokens must be high-entropy cryptographically generated strings.
- **Output schema:** `CanaryAuditReport(canaries_planted: int, leakage_detected: bool, leaked_canary_ids: list[str], passed_assertions: bool)`.
- **Configuration schema:** `CanaryConfig(enforce_zero_leakage_gate: bool = True)`.
- **Default values:** `enforce_zero_leakage_gate = True`.
- **Dependencies:** Python `secrets`, `psycopg` for DB verification.
- **Compatibility requirements:** Enforces ADR-0024 and resolves G-EVAL-1 provenance invariants.
- **Authorization rules:** Internal automated evaluation and security verification tool.
- **Data isolation rules:** Canary fixtures marked `is_synthetic = True`; production queries strictly exclude `is_synthetic`.
- **Error behavior:** If a canary token appears in standard production query response, CI job fails immediately with exit code 1.
- **Fallback behavior:** Fail-closed build rejection.
- **Observability requirements:** Counter `docscout_canary_audit_runs_total`, gauge `docscout_canary_leakage_detected`.
- **Performance limits:** Canary assertion suite execution $\le 5.0\text{ seconds}$ in CI.
- **Resource limits:** Zero extra memory in production serving.
- **Acceptance criteria:** Proves 100% containment of synthetic test fixtures away from production serving queries.
- **Evaluation dataset:** 15 synthetic evaluation fixtures in `corpus/raw/manifest.json`.
- **Evaluation baseline:** Unaudited synthetic fixtures risking silent production data leakage.
- **Required improvement threshold:** Leakage rate = 0.000 (mathematically verified zero leakage).
- **Regression limits:** Build fails if a single canary token is exposed.
- **Completion criteria:** Passing security verification step in `.github/workflows/ci.yml`.

---

## FEAT-085: Expected Calibration Error (ECE) Evaluator
- **Objective:** Evaluate the mathematical calibration between DocScout's stated confidence score (0.00-1.00) and actual empirical retrieval accuracy across the gold evaluation set using Expected Calibration Error (ECE).
- **In-scope behavior:** Partitioning confidence predictions into 10 discrete probability bins; computing accuracy vs confidence gap per bin; calculating weighted ECE metric; enforcing ECE gate in CI.
- **Excluded behavior:** Arbitrarily scaling confidence scores to pass the metric without empirical justification.
- **Implementation boundaries:** `app/evals/calibration.py`, `app/evals/runner.py`.
- **Integration points:** CI evaluation runner `app/evals/runner.py`; committed under `evals/reports/`.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`formulas` ["ece"]), `app/evals/calibration.py`.
- **Supported inputs:** Confidence predictions and ground-truth hit outcomes across evaluation items.
- **Input validation rules:** Minimum 100 predictions; confidence scores bounded in $[0.0, 1.0]$.
- **Output schema:** `ECEReport(ece_score: float, bin_accuracies: list[float], bin_confidences: list[float], max_calibration_error: float, is_calibrated: bool)`.
- **Configuration schema:** `CalibrationConfig(max_allowed_ece: float = 0.06, num_bins: int = 10)`.
- **Default values:** `max_allowed_ece = 0.06`, `num_bins = 10`.
- **Dependencies:** Python standard library `math`, numpy.
- **Compatibility requirements:** Pure offline evaluation metric.
- **Authorization rules:** Internal evaluation pipeline.
- **Data isolation rules:** Operates on historical benchmark evaluations.
- **Error behavior:** Metric calculation error logs warning and marks calibration gate as UNVERIFIED.
- **Fallback behavior:** CI gate warns on unverified calibration.
- **Observability requirements:** Prometheus gauge `docscout_eval_ece_score` committed in evaluation artifacts.
- **Performance limits:** ECE calculation over 1,000 predictions executed in $\le 5.0\text{ ms}$.
- **Resource limits:** Zero memory overhead.
- **Acceptance criteria:** DocScout's stated confidence score achieves an ECE $\le 0.05$, ensuring a "90% confidence" score truly means a 90% probability of factual correctness.
- **Evaluation dataset:** 365 scored gold set items in `evals/gold/v1/gold.jsonl`.
- **Evaluation baseline:** Uncalibrated baseline confidence heuristic (ECE $\approx 0.14$).
- **Required improvement threshold:** ECE $\le 0.05$ (calibration error reduced by $\ge 60\%$).
- **Regression limits:** ECE must not regress above 0.06 in any release.
- **Completion criteria:** ECE metric included and verified in `evals/reports/*/results.json`.

---

## FEAT-086: Refusal Precision & Selective Accuracy Gate
- **Objective:** CI evaluation runner that computes selective accuracy, false rejection rate, and refusal precision over answerable vs unanswerable query sets, enforcing strict abstention behavior.
- **In-scope behavior:** Evaluating system performance across 60 unanswerable queries and 365 answerable queries; calculating selective accuracy ($\text{Accuracy on answered items}$); computing refusal precision ($\text{True unanswerable refused} / \text{Total refused}$); gating CI merges.
- **Excluded behavior:** Allowing answers on unanswerable test queries.
- **Implementation boundaries:** `app/evals/abstention.py`, `app/evals/gate.py`.
- **Integration points:** `make eval-gate` in CI/CD pipeline.
- **Source-of-truth files:** `app/evals/abstention.py`, `evals/gold/v1/gold.jsonl`.
- **Supported inputs:** Benchmark run results JSON.
- **Input validation rules:** Results must contain scored items for both answerable and unanswerable subsets.
- **Output schema:** `AbstentionGateResult(selective_accuracy: float, refusal_precision: float, false_rejection_rate: float, gate_passed: bool)`.
- **Configuration schema:** `AbstentionGateConfig(min_selective_accuracy: float = 0.95, min_refusal_precision: float = 0.98, max_false_rejection_rate: float = 0.03)`.
- **Default values:** `min_selective_accuracy = 0.95`, `min_refusal_precision = 0.98`, `max_false_rejection_rate = 0.03`.
- **Dependencies:** Python standard library `math`.
- **Compatibility requirements:** Enforces E-12 evaluation protocol invariants.
- **Authorization rules:** CI release gate execution.
- **Data isolation rules:** Offline benchmark suite.
- **Error behavior:** If selective accuracy falls below 0.95, gate fails and blocks release.
- **Fallback behavior:** PR merge blocked until retrieval accuracy and refusal thresholds are restored.
- **Observability requirements:** Logged in `evals/reports/*/report.md` with pass/fail status.
- **Performance limits:** Gate evaluation execution $\le 100\text{ ms}$.
- **Resource limits:** Zero extra memory.
- **Acceptance criteria:** Refusal Precision $\ge 0.980$ and Selective Accuracy $\ge 0.965$ on benchmark suite.
- **Evaluation dataset:** Full goldset `2.0.0` (425 items total: 365 answerable, 60 unanswerable).
- **Evaluation baseline:** Current baseline Selective Accuracy = 0.966.
- **Required improvement threshold:** Selective Accuracy maintained $\ge 0.965$; Refusal Precision $\ge 0.980$.
- **Regression limits:** 0 tolerance for regression below threshold (1pp rule).
- **Completion criteria:** `make eval-gate` exits 0 in CI.

---

## FEAT-087: Counterfactual Robustness Testing Suite
- **Objective:** Automated test harness that systematically perturbs entity names, dates, or penalty values in evaluation circulars to verify that DocScout answers from context, not parametric memory.
- **In-scope behavior:** Synthesizing counterfactual variations of gold set circulars (e.g. changing an 18-month timeline to 24 months); asserting that retrieved answers and citations reflect the modified counterfactual context; proving zero leakage from pre-training memory.
- **Excluded behavior:** Deploying counterfactual test circulars into production customer indices.
- **Implementation boundaries:** `app/evals/counterfactual.py`, `scripts/generate_counterfactuals.py`.
- **Integration points:** CI evaluation test suite; `make test-counterfactual`.
- **Source-of-truth files:** `app/evals/counterfactual.py`, `evals/gold/v1/gold.jsonl`.
- **Supported inputs:** Gold set circular documents, entity perturbation mapping.
- **Input validation rules:** Perturbations must alter substantive facts while preserving syntactic validity.
- **Output schema:** `CounterfactualTestResult(items_tested: int, correct_counterfactual_answers: int, parametric_leakage_detected: int, robustness_score: float)`.
- **Configuration schema:** `CounterfactualConfig(min_robustness_score: float = 0.95)`.
- **Default values:** `min_robustness_score = 0.95`.
- **Dependencies:** Python string manipulation, isolated in-memory test database.
- **Compatibility requirements:** Runs in isolated CI test container.
- **Authorization rules:** Internal developer test tool.
- **Data isolation rules:** Counterfactual documents flagged with `is_synthetic = True` and deleted post-run.
- **Error behavior:** Parametric memory leakage (answering with real-world fact instead of perturbed test fact) fails test.
- **Fallback behavior:** Test fails; PR blocked.
- **Observability requirements:** Log counterfactual evaluation summary in test reports.
- **Performance limits:** Suite of 50 counterfactual tests executed in $\le 15\text{ seconds}$.
- **Resource limits:** Memory allocation $\le 128\text{ MB}$.
- **Acceptance criteria:** DocScout achieves $\ge 98\%$ accuracy on counterfactual queries, proving 100% grounding in retrieved text.
- **Evaluation dataset:** 50 counterfactually perturbed regulatory questions and circulars.
- **Evaluation baseline:** Unvalidated LLM systems that recite memorized real-world facts 35% of the time despite contrary context.
- **Required improvement threshold:** Counterfactual context adherence $\ge 98\%$.
- **Regression limits:** Zero tolerance for parametric memory overrides.
- **Completion criteria:** Test suite passes in `tests/test_counterfactual.py`.

---

## FEAT-088: Data Contamination & Lexical Leakage Stratifier
- **Objective:** Automatically partition the evaluation gold set into lexical leakage bands ($<0.5$ term overlap, 0.5-0.8 overlap, $>0.8$ overlap) to prevent benchmark memorization and ensure generalized search capability.
- **In-scope behavior:** Computing term intersection between question text and gold citation quote text; categorizing items into Low, Medium, and High leakage strata; reporting retrieval metrics independently per band.
- **Excluded behavior:** Reporting only aggregate macro-averages that mask low-overlap performance drops.
- **Implementation boundaries:** `app/evals/runner.py` (`_leakage_bands()`), `app/evals/goldset.py`.
- **Integration points:** Core reporting pipeline in `app/evals/runner.py`; output in `results.json` and `report.md`.
- **Source-of-truth files:** `app/evals/runner.py`, `evals/gold/v1/gold.jsonl`.
- **Supported inputs:** Gold items with query text and pinned citation quote text.
- **Input validation rules:** Valid gold item format with non-empty query and quote.
- **Output schema:** `LeakageStratificationReport(low_leakage: MetricSlice, medium_leakage: MetricSlice, high_leakage: MetricSlice)`.
- **Configuration schema:** `LeakageConfig(low_threshold: float = 0.50, high_threshold: float = 0.80)`.
- **Default values:** `low_threshold = 0.50`, `high_threshold = 0.80`.
- **Dependencies:** Python regex term tokenizer.
- **Compatibility requirements:** Enforces schema `docscout.eval.retrieval/1` committed in evaluation reports.
- **Authorization rules:** Internal evaluation runner.
- **Data isolation rules:** Offline benchmark suite analysis.
- **Error behavior:** If stratification fails, log error and report aggregate metrics with diagnostic warning.
- **Fallback behavior:** Standard unstratified macro-average reporting.
- **Observability requirements:** Stratified metrics published in `report.md` table.
- **Performance limits:** Stratification computation $\le 5.0\text{ ms}$ for 425 items.
- **Resource limits:** Zero extra memory.
- **Acceptance criteria:** Generates transparent stratified evaluation tables in every benchmark run, showing separate recall for realistic low-leakage queries.
- **Evaluation dataset:** All 365 answerable items in `evals/gold/v1/gold.jsonl`.
- **Evaluation baseline:** Current baseline with 54 low-leakage items, 142 medium-leakage items, 169 high-leakage items.
- **Required improvement threshold:** Low-leakage Recall@5 verified $\ge 0.900$.
- **Regression limits:** Low-leakage recall drop cannot exceed 1pp in any commit.
- **Completion criteria:** Report verified in `evals/reports/*/report.md`.

---

## FEAT-089: Real-Time Hallucination Telemetry & Prometheus Alarms
- **Objective:** Expose real-time Prometheus gauges for `docscout_claim_support_ratio`, `docscout_abstention_events_total`, and `docscout_unsupported_claim_alerts` to alert SREs and compliance officers instantly.
- **In-scope behavior:** Tracking claim support ratios across all served responses; exposing standard OpenMetrics endpoints at `GET /metrics`; triggering PagerDuty/Slack alarms if claim support ratio falls below 0.98 over a 5-minute window.
- **Excluded behavior:** Logging raw confidential query text to Prometheus metrics labels.
- **Implementation boundaries:** `app/api/metrics.py`, `app/api/app.py`.
- **Integration points:** Prometheus metrics collector in `app/api/metrics.py`; `/metrics` endpoint.
- **Source-of-truth files:** `app/api/metrics.py`, `app/config.py`.
- **Supported inputs:** Operational claim evaluation outcomes from serving pipeline.
- **Input validation rules:** Stored as aggregate counters and histograms without high-cardinality labels.
- **Output schema:** Standard Prometheus text format (version 0.0.4).
- **Configuration schema:** `MetricsConfig(enable_ai_assurance_metrics: bool = True)`.
- **Default values:** `enable_ai_assurance_metrics = True`.
- **Dependencies:** `prometheus_client` Python library.
- **Compatibility requirements:** Conforms to Prometheus and OpenTelemetry scraping standards.
- **Authorization rules:** Unauthenticated or basic-auth protected `/metrics` endpoint per infrastructure config.
- **Data isolation rules:** Aggregated metrics; zero tenant-specific data in label values.
- **Error behavior:** Metrics update failure logs error and never interrupts primary search response.
- **Fallback behavior:** Fail-open for search responses if metrics emission fails.
- **Observability requirements:** Scraped every 15 seconds by Prometheus server.
- **Performance limits:** Metric update overhead $\le 0.02\text{ ms}$ per search request.
- **Resource limits:** Memory allocation $\le 2\text{ MB}$.
- **Acceptance criteria:** Instantly reflects simulated hallucination spikes, triggering alert manager notifications within 60 seconds.
- **Evaluation dataset:** Simulated production traffic load test with 5% seeded unsupported claims.
- **Evaluation baseline:** Generic HTTP latency/status metrics lacking AI assurance visibility.
- **Required improvement threshold:** 100% alert firing on supported-claim ratio drops below 0.98.
- **Regression limits:** Zero performance impact on core `/v1/search` endpoint latency.
- **Completion criteria:** Metrics verified in `tests/test_metrics.py`.

---

## FEAT-090: Automated LLM Judge Calibration with Cohen's Kappa
- **Objective:** Statistical validator measuring inter-annotator agreement (Cohen's Kappa) between automated evaluation judges and human legal experts, enforcing $\kappa \ge 0.85$ to ensure trustworthy automated gating.
- **In-scope behavior:** Computing Cohen's Kappa statistic on paired binary/multiclass evaluations (automated judge vs human annotator); asserting statistical significance; failing CI gates if automated judge drifts from human consensus.
- **Excluded behavior:** Using uncalibrated automated judges to certify compliance features.
- **Implementation boundaries:** `app/evals/judge_calibration.py`, `app/evals/stats.py`.
- **Integration points:** Pre-evaluation calibration check in `app/evals/runner.py`.
- **Source-of-truth files:** `app/evals/judge_calibration.py`, `app/evals/stats.py`.
- **Supported inputs:** Paired classification arrays `judge_scores: list[int]`, `human_scores: list[int]`.
- **Input validation rules:** Arrays must have identical length $\ge 50$ items; values binary (0/1) or categorical.
- **Output schema:** `CalibrationReport(cohen_kappa: float, agreement_rate: float, p_value: float, is_calibrated: bool)`.
- **Configuration schema:** `JudgeCalibrationConfig(min_kappa: float = 0.85)`.
- **Default values:** `min_kappa = 0.85`.
- **Dependencies:** Python standard library `math`, `scipy.stats` or custom verified Kappa calculator in `stats.py`.
- **Compatibility requirements:** Pure offline statistical calculation.
- **Authorization rules:** Internal evaluation pipeline.
- **Data isolation rules:** Benchmark calibration dataset.
- **Error behavior:** If Kappa calculation fails, gate halts with descriptive statistical error.
- **Fallback behavior:** Release blocked until judge calibration is restored.
- **Observability requirements:** Cohen's Kappa score recorded in evaluation reports.
- **Performance limits:** Kappa calculation $\le 2.0\text{ ms}$ for 500 paired annotations.
- **Resource limits:** Zero extra memory.
- **Acceptance criteria:** Enforces $\kappa \ge 0.85$ across all automated evaluation judges used in CI regression gates.
- **Evaluation dataset:** 100 human-annotated regulatory answer evaluation pairs with gold human judgments.
- **Evaluation baseline:** Current baseline kappa = 1.000 / 0.844.
- **Required improvement threshold:** Automated judge Cohen's Kappa $\ge 0.850$.
- **Regression limits:** Release gate fails if judge Kappa falls below 0.80.
- **Completion criteria:** Calibration test passes in `tests/test_judge_calibration.py`.
