# Pillar 3 Specification: Regulatory Compliance Formulas & Quantitative Verification
*DocScout Enterprise Regulatory Intelligence Engine*

---

## FEAT-021: Statutory Formula Computational Engine
- **Objective:** In-engine AST parser and safe mathematical evaluator executing the 24 formulas from `term-taxonomy.json` (e.g., Software Carbon Intensity, Error Budget Burn Rate, MC/DC Bounds, Little's Law, Capital Adequacy, LCR) directly within DocScout.
- **In-scope behavior:** Parsing formula expressions; validating required input variables; evaluating expressions with arbitrary-precision arithmetic; returning computed values with units and standard citations.
- **Excluded behavior:** Arbitrary untrusted Python `eval()` or `exec()` code execution; network calls during calculation.
- **Implementation boundaries:** `app/compliance/formula_engine.py`, `app/api/app.py` (`POST /v1/compliance/calculate`).
- **Integration points:** API endpoint `/v1/compliance/calculate`; calculation widget in React UI console.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`formulas`), `app/compliance/formula_engine.py`.
- **Supported inputs:** `FormulaCalcRequest(formula_id: str, inputs: dict[str, float])`.
- **Input validation rules:** `formula_id` must match one of the 24 known formula IDs; all variables defined in formula schema must be present and finite floats.
- **Output schema:** `FormulaCalcResult(formula_id: str, name: str, expression: str, computed_value: float, unit: str, standard: str, note: str)`.
- **Configuration schema:** `FormulaEngineConfig(max_calc_duration_ms: int = 50, precision_decimal_places: int = 4)`.
- **Default values:** `max_calc_duration_ms = 50`, `precision_decimal_places = 4`.
- **Dependencies:** Python `ast` module, `decimal.Decimal` for financial precision.
- **Compatibility requirements:** Thread-safe execution; zero reliance on dynamic code generation.
- **Authorization rules:** Requires authenticated API key or user token with `compliance:read` scope.
- **Data isolation rules:** Calculation is purely functional and stateless; inputs are never persisted unless audit logging is explicitly requested.
- **Error behavior:** Missing variables return HTTP 422 with missing variable names; division by zero returns HTTP 400 with "Math domain error".
- **Fallback behavior:** Returns descriptive validation error guiding the user on required input variables.
- **Observability requirements:** Counter `docscout_formulas_calculated_total{formula_id}`, duration histogram.
- **Performance limits:** Calculation execution latency $\le 1.0\text{ ms}$ p95.
- **Resource limits:** Memory footprint $\le 2\text{ MB}$; CPU time $\le 5\text{ ms}$.
- **Acceptance criteria:** 100% test pass rate across all 24 formulas with known numerical test vectors (e.g. SCI calculation, burn rate calculation).
- **Evaluation dataset:** 48 test cases (2 test vectors per formula) with known analytical ground truths.
- **Evaluation baseline:** Zero computational formula capability in current DocScout.
- **Required improvement threshold:** 100% computational accuracy (relative error $< 10^{-6}$).
- **Regression limits:** Zero vulnerability to Python code injection probes.
- **Completion criteria:** Passes `tests/test_formula_engine.py` with 100% assertion coverage.

---

## FEAT-022: Automated Formula Extraction from Circulars
- **Objective:** Ingestion-time extractor that parses circular text to identify mathematical formulas, statutory ratios, and variable definitions, storing them in structured database columns.
- **In-scope behavior:** Regex and heuristic AST parsing of mathematical expressions (e.g. "CRAR = (Tier I + Tier II) / RWA", "LCR = Stock of HQLA / Total net cash outflows"); extracting variable definitions from surrounding text; populating `document_formulas` table.
- **Excluded behavior:** Guessing formulas from informal colloquial text.
- **Implementation boundaries:** `app/ingest/formula_extractor.py`, `app/ingest/extract_chain.py`.
- **Integration points:** Stage 3 of document ingestion chain; runs during PDF/HTML extraction.
- **Source-of-truth files:** `app/ingest/formula_extractor.py`, `migrations/0013_compliance_formulas.up.sql`.
- **Supported inputs:** Document text `text: str`, document metadata `doc_id: str`.
- **Input validation rules:** `text` non-empty, length $\ge 100$ characters.
- **Output schema:** `list[ExtractedFormula(doc_id: str, formula_name: str, raw_expression: str, parsed_ast: dict, variables: dict[str, str], span: tuple[int, int])]`.
- **Configuration schema:** `FormulaExtractorConfig(enabled: bool = True, min_confidence: float = 0.85)`.
- **Default values:** `enabled = True`, `min_confidence = 0.85`.
- **Dependencies:** Python `re`, `sympy` or custom expression tokenizer.
- **Compatibility requirements:** Extracted formulas stored in standard PostgreSQL JSONB column.
- **Authorization rules:** Internal ingestion pipeline execution.
- **Data isolation rules:** Formulas tied to document version; respects `is_synthetic` isolation.
- **Error behavior:** Extraction failure on a clause logs warning and continues processing remaining document text.
- **Fallback behavior:** Document chunks indexed normally without formula metadata tags.
- **Observability requirements:** Counter `docscout_formulas_extracted_total`, gauge `docscout_documents_with_formulas_total`.
- **Performance limits:** Processing throughput $\ge 150\text{ pages/sec}$.
- **Resource limits:** Memory footprint $\le 20\text{ MB}$.
- **Acceptance criteria:** Extracts statutory formulas from 100% of benchmark prudential circulars (Capital Adequacy, Liquidity Risk, Net Stable Funding Ratio).
- **Evaluation dataset:** 10 benchmark circulars containing known statutory formulas ($n=18$ formulas).
- **Evaluation baseline:** 0% automated formula extraction in baseline.
- **Required improvement threshold:** Extraction precision $\ge 95\%$, recall $\ge 90\%$.
- **Regression limits:** Zero slowdown to main text indexing pipeline ($\le 3\%$).
- **Completion criteria:** Verified in `tests/test_formula_extraction.py`.

---

## FEAT-023: Statutory Threshold & Boundary Validator
- **Objective:** Rule engine that checks user-provided or extracted financial ratios against statutory floors and ceilings (e.g. CRAR $\ge 15\%$ for NBFC-SI; LCR $\ge 100\%$; Leverage Ratio $\ge 4\%$), generating compliance status flags.
- **In-scope behavior:** Evaluating numeric values against threshold rules; flagging violations (BREACH), warning states (AMBER), and compliant states (GREEN); returning citation of the specific circular establishing the threshold.
- **Excluded behavior:** Providing binding legal or financial advice.
- **Implementation boundaries:** `app/compliance/boundary_validator.py`, `app/api/models.py`.
- **Integration points:** Used by `POST /v1/compliance/validate-ratios` and React compliance dashboard.
- **Source-of-truth files:** `app/compliance/boundary_validator.py`, `do not commit!/term-taxonomy.json` (`formulas[].note`).
- **Supported inputs:** `RatioValidationRequest(entity_type: str, ratios: dict[str, float])`.
- **Input validation rules:** `entity_type` must be valid regulatory entity class; ratio values must be numeric.
- **Output schema:** `RatioValidationResponse(overall_status: Literal["COMPLIANT", "WARNING", "BREACH"], findings: list[RatioFinding(ratio_name: str, reported_value: float, statutory_threshold: str, status: str, circular_citation: str)])`.
- **Configuration schema:** `ValidationRulesConfig(tolerance_percentage: float = 0.05)`.
- **Default values:** `tolerance_percentage = 0.05` (triggers AMBER warning within 5% of threshold).
- **Dependencies:** Pure Python rule engine.
- **Compatibility requirements:** Standard Pydantic schema validation; FastAPI integration.
- **Authorization rules:** Requires authenticated API key or user token with `compliance:read`.
- **Data isolation rules:** Ratios validated ephemerally; zero persistence unless audit logging requested.
- **Error behavior:** Unrecognized ratio name returns HTTP 422 with catalog of known ratios.
- **Fallback behavior:** Returns descriptive error schema.
- **Observability requirements:** Counter `docscout_validations_performed_total{status}`, structlog audit logging.
- **Performance limits:** Validation execution latency $\le 1.2\text{ ms}$ p95.
- **Resource limits:** Memory allocation $\le 1\text{ MB}$.
- **Acceptance criteria:** Correctly identifies compliance, warning, and breach states across all 35 statutory financial thresholds in RBI Master Directions.
- **Evaluation dataset:** 70 test boundary scenarios (boundary - 1%, boundary, boundary + 1%).
- **Evaluation baseline:** 0% automated boundary validation in current baseline.
- **Required improvement threshold:** 100% boundary detection accuracy across test vectors.
- **Regression limits:** Zero false-positive breach alerts on compliant inputs.
- **Completion criteria:** Unit tests pass in `tests/test_boundary_validator.py`.

---

## FEAT-024: Compliance "What-If" Sensitivity Simulator
- **Objective:** Interactive calculation engine allowing risk managers to model how balance sheet shifts (e.g., changes in Tier-1 capital, risk-weighted assets, high-quality liquid assets) affect compliance ratios in real-time.
- **In-scope behavior:** Parameterized formula execution; computing partial derivatives / sensitivity deltas; streaming calculation results to UI sliders; generating stress-test scenario curves.
- **Excluded behavior:** Automated predictive financial modeling or balance sheet optimization.
- **Implementation boundaries:** `app/compliance/simulator.py`, `ui/src/components/SensitivitySimulator.tsx`.
- **Integration points:** API endpoint `/v1/compliance/simulate`; React console Simulator tab.
- **Source-of-truth files:** `app/compliance/simulator.py`, `ui/src/components/SensitivitySimulator.tsx`.
- **Supported inputs:** `SimulationRequest(formula_id: str, base_inputs: dict[str, float], deltas: dict[str, list[float]])`.
- **Input validation rules:** `deltas` length $\le 50$ points per variable; all inputs non-negative floats.
- **Output schema:** `SimulationResponse(formula_id: str, baseline_value: float, scenario_results: list[dict[str, float]], sensitivity_gradient: dict[str, float])`.
- **Configuration schema:** `SimulatorConfig(max_scenarios: int = 100)`.
- **Default values:** `max_scenarios = 100`.
- **Dependencies:** Python `math`, React and Recharts for frontend curve plotting.
- **Compatibility requirements:** Sub-10ms server calculation response to support smooth interactive UI sliders.
- **Authorization rules:** Requires authenticated caller with `compliance:read`.
- **Data isolation rules:** Strictly client-side or ephemeral server-side computation.
- **Error behavior:** Calculation failure returns HTTP 400 with exact parameter causing math error.
- **Fallback behavior:** Returns static baseline without sensitivity curve.
- **Observability requirements:** Metric `docscout_simulation_requests_total`, histogram `docscout_simulation_duration_seconds`.
- **Performance limits:** Simulation of 50 scenarios completed in $\le 4.0\text{ ms}$ on server; 60fps UI rendering.
- **Resource limits:** Memory footprint $\le 4\text{ MB}$.
- **Acceptance criteria:** UI updates sensitivity graphs in real-time as users drag input sliders with zero perceptible lag.
- **Evaluation dataset:** 10 stress-testing balance sheet scenarios.
- **Evaluation baseline:** Zero interactive simulation in legacy console.
- **Required improvement threshold:** 100% calculation agreement with manual spreadsheet stress models.
- **Regression limits:** Zero UI freeze or layout thrashing during continuous slider interaction.
- **Completion criteria:** Component tests in `ui/src/components/SensitivitySimulator.test.tsx` pass.

---

## FEAT-025: Standard-Linked Formula Annotator
- **Objective:** Cross-link formula definitions in circular text directly to parent international and national standards (e.g. linking carbon formulas to ISO/IEC 21031; CRAR to Basel III), enriching citations.
- **In-scope behavior:** Ingestion-time linking of extracted formulas to `standards_registry` records; injecting standard citation metadata into search passages that cite formulas.
- **Excluded behavior:** Linking unverified mathematical equations lacking statutory standard backing.
- **Implementation boundaries:** `app/ingest/standard_linker.py`, `migrations/0013_compliance_formulas.up.sql`.
- **Integration points:** Ingestion pipeline post-extraction phase; search response enrichment in `app/api/app.py`.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`formulas[].standard`), `app/ingest/standard_linker.py`.
- **Supported inputs:** `ExtractedFormula` object, `standards_registry` table.
- **Input validation rules:** Standard reference string must match an ID in `standardsRegistry`.
- **Output schema:** `AnnotatedFormula(formula_id: str, standard_id: str, standard_name: str, governing_body: str)`.
- **Configuration schema:** `StandardLinkerConfig(strict_matching: bool = True)`.
- **Default values:** `strict_matching = True`.
- **Dependencies:** PostgreSQL foreign keys between `compliance_formulas` and `standards_registry`.
- **Compatibility requirements:** Standard relational database integrity constraints.
- **Authorization rules:** Internal ingestion pipeline execution.
- **Data isolation rules:** Public standards metadata.
- **Error behavior:** Unmatched standard reference logs diagnostic info and sets `standard_id = NULL`.
- **Fallback behavior:** Formula stored without parent standard foreign key.
- **Observability requirements:** Counter `docscout_standard_formula_links_total`.
- **Performance limits:** Linking overhead $\le 0.5\text{ ms}$ per formula.
- **Resource limits:** Zero extra memory.
- **Acceptance criteria:** 100% of the 24 formulas in `term-taxonomy.json` successfully link to their governing standard.
- **Evaluation dataset:** All 24 taxonomy formulas.
- **Evaluation baseline:** Disconnected formulas lacking formal standard lineage.
- **Required improvement threshold:** 100% link resolution for standards present in registry.
- **Regression limits:** Zero database foreign key violations during ingestion.
- **Completion criteria:** Database migration test verifies relational integrity.

---

## FEAT-026: Numerical Regulatory Evidence Extractor
- **Objective:** High-precision tabular and prose parser extracting quantitative statutory parameters (penalty amounts, statutory filing windows, net worth thresholds) into structured queryable columns.
- **In-scope behavior:** Extraction of monetary values (INR), time horizons (days/months), and percentages; associating numerical values with their legal obligations; storing structured facts in `statutory_parameters` table.
- **Excluded behavior:** Extracting page numbers, document dates, or serial numbers as statutory quantitative limits.
- **Implementation boundaries:** `app/ingest/numeric_extractor.py`, `migrations/0012_statutory_parameters.up.sql`.
- **Integration points:** Post-chunking phase in ingestion pipeline.
- **Source-of-truth files:** `app/ingest/numeric_extractor.py`, `corpus/raw/*.PDF`.
- **Supported inputs:** Chunk text `text: str`, `chunk_id: str`.
- **Input validation rules:** Text length $\ge 50$ chars.
- **Output schema:** `list[StatutoryParameter(parameter_name: str, numeric_value: float, unit: str, obligation_type: str, chunk_id: str)]`.
- **Configuration schema:** `NumericExtractorConfig(currency: str = "INR", parse_words: bool = True)`.
- **Default values:** `currency = "INR"`, `parse_words = True` (e.g. parses "twenty-five crore").
- **Dependencies:** Python regex, word-to-number converter (`word2number`).
- **Compatibility requirements:** Stores numbers as standard SQL `DOUBLE PRECISION` and `NUMERIC(20,4)`.
- **Authorization rules:** Internal ingestion pipeline execution.
- **Data isolation rules:** Extracted facts bound to chunk ID; respects `is_synthetic` isolation.
- **Error behavior:** Failed extraction logs warning and proceeds with chunking.
- **Fallback behavior:** Chunk stored without structured numerical parameter tags.
- **Observability requirements:** Counter `docscout_parameters_extracted_total{unit}`.
- **Performance limits:** Extraction speed $\ge 200\text{ chunks/sec}$.
- **Resource limits:** Memory footprint $\le 8\text{ MB}$.
- **Acceptance criteria:** Extracts statutory deadlines and penalty limits from $\ge 92\%$ of circular clauses containing numerical requirements.
- **Evaluation dataset:** 50 regulatory clauses containing quantitative mandates ($n=68$ parameters).
- **Evaluation baseline:** 0% structured quantitative parameter extraction in baseline.
- **Required improvement threshold:** Extraction precision $\ge 96\%$, recall $\ge 90\%$.
- **Regression limits:** Zero corruption of chunk text or offsets.
- **Completion criteria:** Verified in `tests/test_numeric_extractor.py`.

---

## FEAT-027: Mathematical Sanity & Consistency Auditor
- **Objective:** Automated consistency validator verifying whether numerical tables in bank filings or circular annexures add up mathematically (checking row/column sums and percentage distributions).
- **In-scope behavior:** Parsing table rows and columns; verifying summation invariants ($\sum \text{rows} = \text{Total}$, $\sum \text{percentages} = 100\%$); detecting clerical discrepancies; generating discrepancy audit reports.
- **Excluded behavior:** Arbitrary financial auditing beyond mathematical identity verification.
- **Implementation boundaries:** `app/compliance/table_auditor.py`, `app/api/app.py`.
- **Integration points:** Ingestion table validator; API endpoint `POST /v1/compliance/audit-table`.
- **Source-of-truth files:** `app/compliance/table_auditor.py`.
- **Supported inputs:** `TableAuditRequest(table_matrix: list[list[Any]], row_labels: list[str], col_labels: list[str])`.
- **Input validation rules:** Table must have at least 2 rows and 2 columns; cells must be convertible to numeric floats.
- **Output schema:** `TableAuditResponse(is_mathematically_consistent: bool, discrepancies_found: list[TableDiscrepancy(cell_coordinate: str, expected_sum: float, actual_sum: float, delta: float)])`.
- **Configuration schema:** `TableAuditorConfig(tolerance_epsilon: float = 0.01)`.
- **Default values:** `tolerance_epsilon = 0.01` (to account for rounding).
- **Dependencies:** Python standard library `decimal`.
- **Compatibility requirements:** Fully stateless API execution.
- **Authorization rules:** Requires authenticated API caller with `compliance:read`.
- **Data isolation rules:** Table data processed strictly in memory; zero persistence.
- **Error behavior:** Malformed table returns HTTP 422 with exact row/col formatting error.
- **Fallback behavior:** Returns descriptive validation failure schema.
- **Observability requirements:** Counter `docscout_tables_audited_total`, structlog error logs on discrepancy.
- **Performance limits:** Audit of a 20x20 table executed in $\le 2.0\text{ ms}$.
- **Resource limits:** Memory footprint $\le 4\text{ MB}$.
- **Acceptance criteria:** Detects 100% of seeded arithmetic errors in balance sheet disclosure matrices.
- **Evaluation dataset:** 20 synthetic regulatory disclosure tables with 10 deliberate summation errors.
- **Evaluation baseline:** 0% automated mathematical table auditing in baseline.
- **Required improvement threshold:** Error detection precision = 1.000, recall = 1.000.
- **Regression limits:** Zero false-positive discrepancy flags on valid rounded tables.
- **Completion criteria:** Verified in `tests/test_table_auditor.py`.

---

## FEAT-028: Indian Financial Unit Normalizer
- **Objective:** Normalization layer converting Lakhs, Crores, Millions, Billions, basis points (bps), and percentages into canonical ISO numeric floats for uniform search and comparison.
- **In-scope behavior:** Regex matching of financial denominations (e.g. "₹50 Cr", "Rs. 25 Lakh", "50 bps", "7.5%"); converting to standardized numerical floats; storing canonical values alongside raw text.
- **Excluded behavior:** Foreign currency forex conversions without specified spot rates.
- **Implementation boundaries:** `app/retrieval/unit_normalizer.py`.
- **Integration points:** Query expansion in `app/retrieval/search.py`; ingestion numeric extractor.
- **Source-of-truth files:** `app/retrieval/unit_normalizer.py`.
- **Supported inputs:** Text string containing monetary or quantitative terms `text: str`.
- **Input validation rules:** String length $\le 512$ chars.
- **Output schema:** `NormalizedUnitsResult(canonical_float: float, raw_token: str, dimension: Literal["CURRENCY_INR", "PERCENTAGE", "BASIS_POINTS", "TIME_DAYS"])`.
- **Configuration schema:** `UnitNormalizerConfig(default_currency: str = "INR")`.
- **Default values:** `default_currency = "INR"`.
- **Dependencies:** Compiled regex pattern catalog.
- **Compatibility requirements:** Sub-millisecond execution; zero external runtime dependencies.
- **Authorization rules:** Internal utility; public data.
- **Data isolation rules:** Completely stateless.
- **Error behavior:** Unrecognized unit returns raw unconverted string with diagnostic log.
- **Fallback behavior:** Retain raw token in search query.
- **Observability requirements:** Metric `docscout_units_normalized_total{dimension}`.
- **Performance limits:** Normalization execution $\le 0.2\text{ ms}$ p95.
- **Resource limits:** Memory allocation $\le 1\text{ MB}$.
- **Acceptance criteria:** Converts 100% of standard Indian financial notations (Lakh, Crore, bps) into exact IEEE-754 floats.
- **Evaluation dataset:** 50 Indian financial denomination test strings.
- **Evaluation baseline:** Literal string matching failing to equate "50 Crore" with "5,000,000,000".
- **Required improvement threshold:** 100% conversion accuracy across test set.
- **Regression limits:** Zero false-positive conversions of general words containing unit substrings.
- **Completion criteria:** Unit tests pass in `tests/test_unit_normalizer.py`.

---

## FEAT-029: Formula Dependency Graph Builder
- **Objective:** Construct a directed acyclic graph (DAG) of formula variables to determine dependencies, calculation sequences, and missing prerequisite data points for multi-step regulatory returns.
- **In-scope behavior:** Analyzing formula variable definitions; mapping inputs that are themselves outputs of subsidiary formulas; performing topological sort; detecting circular dependencies.
- **Excluded behavior:** Arbitrary circular reference resolution in invalid equations.
- **Implementation boundaries:** `app/compliance/formula_dag.py`.
- **Integration points:** Formula engine orchestration; `/v1/compliance/formula-dag/{formula_id}`.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`formulas`), `app/compliance/formula_dag.py`.
- **Supported inputs:** Target `formula_id: str`.
- **Input validation rules:** `formula_id` must exist in `compliance_formulas` catalog.
- **Output schema:** `FormulaDAGResponse(formula_id: str, calculation_order: list[str], root_inputs: list[str], intermediate_variables: list[str], is_acyclic: bool)`.
- **Configuration schema:** `FormulaDAGConfig(max_depth: int = 5)`.
- **Default values:** `max_depth = 5`.
- **Dependencies:** Python standard library `graphlib.TopologicalSorter`.
- **Compatibility requirements:** Python 3.12+ standard library.
- **Authorization rules:** Requires authenticated API caller with `compliance:read`.
- **Data isolation rules:** Public formula definitions only.
- **Error behavior:** Cycle detection raises `CycleError` and returns HTTP 422 with cycle path.
- **Fallback behavior:** Returns error details indicating circular variable definition.
- **Observability requirements:** Counter `docscout_formula_dags_generated_total`.
- **Performance limits:** DAG generation and topological sort $\le 0.8\text{ ms}$.
- **Resource limits:** Memory allocation $\le 2\text{ MB}$.
- **Acceptance criteria:** Successfully computes valid calculation order for all multi-variable statutory ratios (e.g. Risk-Weighted Assets computation).
- **Evaluation dataset:** All multi-step formulas in `term-taxonomy.json`.
- **Evaluation baseline:** Flat isolated formulas lacking dependency knowledge.
- **Required improvement threshold:** 100% valid topological sort across acyclic formula dependencies.
- **Regression limits:** Zero infinite recursion on cyclic definitions.
- **Completion criteria:** Verified in `tests/test_formula_dag.py`.

---

## FEAT-030: Historical Formula Evolution & Versioning
- **Objective:** Track and version changes in statutory formulas over time (e.g., Basel II standardized vs Basel III internal ratings-based approach) to enable retroactive audits.
- **In-scope behavior:** Storing effective date ranges (`valid_from`, `valid_to`) on formula records; querying formula by historical `as_of_date`; retrieving exact historical coefficients and thresholds.
- **Excluded behavior:** Guessing formula definitions for dates prior to regulatory records.
- **Implementation boundaries:** `migrations/0013_compliance_formulas.up.sql`, `app/compliance/formula_engine.py`.
- **Integration points:** `FormulaCalcRequest.as_of_date` parameter; `/v1/compliance/calculate`.
- **Source-of-truth files:** `app/compliance/formula_engine.py`, `migrations/0013_compliance_formulas.up.sql`.
- **Supported inputs:** Formula ID `formula_id: str`, query date `as_of_date: Optional[datetime.date]`.
- **Input validation rules:** `as_of_date` format `YYYY-MM-DD`, between 1990-01-01 and current date.
- **Output schema:** Formula record active on specified date with `effective_window: tuple[date, Optional[date]]`.
- **Configuration schema:** `FormulaVersioningConfig(default_to_latest: bool = True)`.
- **Default values:** `default_to_latest = True` (uses latest active formula if date omitted).
- **Dependencies:** PostgreSQL bitemporal date range index on `compliance_formulas(valid_from, valid_to)`.
- **Compatibility requirements:** Seamlessly defaults to latest formula when date omitted.
- **Authorization rules:** Requires standard `compliance:read` authorization.
- **Data isolation rules:** Public statutory version history.
- **Error behavior:** If no formula valid on given date, return HTTP 404 with historical coverage bounds.
- **Fallback behavior:** Returns earliest known formula version with explicit historical disclaimer.
- **Observability requirements:** Log `as_of_date` in structlog when non-default date requested.
- **Performance limits:** Versioned formula lookup latency $\le 1.0\text{ ms}$ p95.
- **Resource limits:** Zero extra memory.
- **Acceptance criteria:** Accurately resolves historical risk-weight formulas for historical audit dates (e.g. 2018 vs 2024).
- **Evaluation dataset:** 15 historical formula audit queries.
- **Evaluation baseline:** 0% historical formula versioning (latest formula only).
- **Required improvement threshold:** 100% historical formula accuracy across versioned test cases.
- **Regression limits:** Zero performance impact when querying latest current formulas.
- **Completion criteria:** Database migration and tests pass in `tests/test_formula_versioning.py`.
