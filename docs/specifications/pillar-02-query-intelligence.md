# Pillar 2 Specification: Query Intelligence, Disambiguation & Intent Routing
*DocScout Enterprise Regulatory Intelligence Engine*

---

## FEAT-011: Context-Aware Token Disambiguation Engine
- **Objective:** Detect and disambiguate polysemous tokens (e.g., "coverage", "canary", "shift", "RE", "PA") using the 8 formal disambiguation rules from `term-taxonomy.json` to prevent catastrophic cross-domain retrieval errors.
- **In-scope behavior:** Analyzing surrounding sentence context window (5 tokens left/right); scoring domain probabilities; selecting canonical term sense; routing query to correct statutory domain.
- **Excluded behavior:** Arbitrary dictionary lookup for general non-technical English words.
- **Implementation boundaries:** `app/retrieval/disambiguation.py`, `app/retrieval/search.py`.
- **Integration points:** Pre-retrieval pipeline immediately following query cleaning in `app/retrieval/search.py`.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`disambiguations`), `app/retrieval/disambiguation.py`.
- **Supported inputs:** Clean query string `query: str`, optional domain hint `domain_hint: Optional[str]`.
- **Input validation rules:** String length between 3 and 512 characters, printable UTF-8.
- **Output schema:** `DisambiguationResult(token: str, resolved_sense: str, canonical_term: str, confidence: float, modified_query: str)`.
- **Configuration schema:** `DisambiguationConfig(enabled: bool = True, min_confidence: float = 0.70)`.
- **Default values:** `enabled = True`, `min_confidence = 0.70`.
- **Dependencies:** Regex tokenizer, context n-gram frequency lookup table.
- **Compatibility requirements:** Python 3.12, zero external C-dependencies, sub-millisecond execution.
- **Authorization rules:** Inherits caller search authorization (`search:read`).
- **Data isolation rules:** Disambiguation models are stateless and public; zero per-tenant context retained.
- **Error behavior:** If disambiguation fails or confidence $< 0.70$, retain original token unaltered and log diagnostic event.
- **Fallback behavior:** Pass-through query unmodified to default hybrid retrieval.
- **Observability requirements:** Counter `docscout_tokens_disambiguated_total{token, resolved_sense}`, histogram `docscout_disambiguation_latency_seconds`.
- **Performance limits:** Execution latency $\le 0.8\text{ ms}$ p95.
- **Resource limits:** Memory allocation $\le 4\text{ MB}$ for disambiguation rule table.
- **Acceptance criteria:** Correctly resolves 100% of the 8 canonical test cases in `term-taxonomy.json` (e.g., "branch coverage" -> structural vs "functional coverage model" -> functional; "canary deployment" -> traffic vs "canary token" -> leak detection).
- **Evaluation dataset:** Synthetic disambiguation benchmark suite ($n=80$ queries containing ambiguous terms in varied regulatory/technical contexts).
- **Evaluation baseline:** Legacy un-disambiguated search with 38% domain bleed on polysemous terms.
- **Required improvement threshold:** Disambiguation accuracy $\ge 96\%$.
- **Regression limits:** Zero false-positive modifications on queries lacking ambiguous terms.
- **Completion criteria:** Passes `tests/test_disambiguation.py` with 100% assertion coverage.

---

## FEAT-012: 296-Term Regulatory & Systems Acronym Expander
- **Objective:** Upgrade the static 36-term domain expander (ADR-0017) to a dynamic, indexed engine supporting all 296 acronyms in `lexicon.indices.byAcronym` with case-boundary guards.
- **In-scope behavior:** Bidirectional acronym expansion (Acronym -> Canonical Name and Canonical Name -> Acronym); case-sensitive regex boundaries for short abbreviations ($\le 3$ chars, e.g., `\bPA\b`, `\bRE\b`); deduplication against terms already present in query.
- **Excluded behavior:** Case-insensitive expansion of 2-letter words (e.g. matching "re" in "regarding" or "pa" in "per annum").
- **Implementation boundaries:** `app/retrieval/expansion.py`, `app/retrieval/types.py`.
- **Integration points:** `DomainQueryExpander` in `app/retrieval/search.py`, `SearchRequest` in `app/api/models.py`.
- **Source-of-truth files:** `do not commit!/lexicon.json` (`indices.byAcronym`), `app/retrieval/expansion.py`.
- **Supported inputs:** `query: str`, `expansion_mode: Literal["synonym", "hyde", "combined", "none"]`.
- **Input validation rules:** `query` non-empty, length $\le 512$ chars.
- **Output schema:** `ExpandedQuery(original_query: str, lexical_query: str, dense_query: str, expansions_applied: list[str])`.
- **Configuration schema:** `ExpansionConfig(enabled: bool = True, max_expansions_per_query: int = 5)`.
- **Default values:** `enabled = True`, `max_expansions_per_query = 5`.
- **Dependencies:** Pre-compiled regex automata dictionary.
- **Compatibility requirements:** Cache keys in `app/api/cache.py` must include `expansions_applied` hash to prevent cross-mode pollution.
- **Authorization rules:** Standard search endpoint authorization.
- **Data isolation rules:** Strictly public acronym catalog; completely stateless.
- **Error behavior:** Regex compilation failure or exception logs error and returns original unexpanded query.
- **Fallback behavior:** Transparent pass-through of original query string.
- **Observability requirements:** Metric `docscout_acronyms_expanded_total{acronym}`, log structlog key `expansions`.
- **Performance limits:** Expansion execution $\le 0.5\text{ ms}$ p95.
- **Resource limits:** Memory footprint $\le 8\text{ MB}$.
- **Acceptance criteria:** Correctly expands all 296 statutory and technical acronyms without false positive matches on common English prose.
- **Evaluation dataset:** 150 regulatory acronym queries evaluated against `evals/gold/v1/gold.jsonl`.
- **Evaluation baseline:** 36-term baseline missing 260 acronyms (e.g., SRO, CKYCR, ODR, TPAP, LEI, BRSR).
- **Required improvement threshold:** Recall@5 on low-leakage acronym queries increases from 0.740 to $\ge 0.940$ ($+20\text{ pp}$).
- **Regression limits:** High-leakage queries must show zero recall regression ($\Delta \le 0.001$).
- **Completion criteria:** Verified in `tests/test_query_expansion.py` and `evals/reports/`.

---

## FEAT-013: Intent-Driven Query Classification & Routing
- **Objective:** Automatically classify incoming queries against the 21 diagnostic intents from `term-taxonomy.json` and enrich API responses with intent metadata and prescriptive "first move" action items.
- **In-scope behavior:** Matching user query intent via lightweight embedding/regex classifier; mapping to primary domain and route terms; returning `firstMove` guidance in search response.
- **Excluded behavior:** Arbitrary speculative intent guessing on unstructured conversational chatter.
- **Implementation boundaries:** `app/retrieval/intent_router.py`, `app/api/models.py`.
- **Integration points:** `SearchResponse` model in `app/api/models.py`; `POST /v1/search`.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`intents`), `app/retrieval/intent_router.py`.
- **Supported inputs:** Clean query string `query: str`.
- **Input validation rules:** Length between 5 and 512 characters.
- **Output schema:** `IntentClassification(intent_id: str, label: str, primary_domain: str, first_move: str, confidence: float, recommended_terms: list[str])`.
- **Configuration schema:** `IntentRouterConfig(enabled: bool = True, min_confidence: float = 0.65)`.
- **Default values:** `enabled = True`, `min_confidence = 0.65`.
- **Dependencies:** Precomputed intent centroid vectors using BGE-small embedding model.
- **Compatibility requirements:** Additive field on `SearchResponse`; 100% backward compatible with existing API consumers.
- **Authorization rules:** Inherits caller search authorization.
- **Data isolation rules:** Completely stateless intent classification.
- **Error behavior:** If no intent clears confidence threshold, return `intent: None` without interrupting search.
- **Fallback behavior:** Search proceeds normally with `intent = None`.
- **Observability requirements:** Counter `docscout_queries_by_intent_total{intent_id}`, duration histogram.
- **Performance limits:** Intent classification latency $\le 2.5\text{ ms}$ p95.
- **Resource limits:** Memory footprint $\le 6\text{ MB}$ for intent centroid embeddings.
- **Acceptance criteria:** Accurately classifies $\ge 90\%$ of test utterances from `term-taxonomy.json.intents` (e.g. "our CI is flaky" -> `intent.flaky-ci`, "how to report cyber incident" -> `intent.incident-readiness`).
- **Evaluation dataset:** 105 synthetic utterances mapped across all 21 intents.
- **Evaluation baseline:** 0% intent recognition in current DocScout API.
- **Required improvement threshold:** Intent classification accuracy $\ge 90\%$.
- **Regression limits:** Zero search latency degradation past 50ms p95.
- **Completion criteria:** Integrated into `app/api/app.py` with passing unit tests in `tests/test_intent_router.py`.

---

## FEAT-014: Regulatory HyDE (Hypothetical Document Embeddings)
- **Objective:** Generate a structured statutory hypothesis passage (mirroring official RBI/SEBI circular formatting) for low-overlap queries before dense vector search to bridge phrasing mismatches.
- **In-scope behavior:** Template-based and lightweight LLM generation of hypothetical regulatory circular clauses; embedding the hypothetical clause in passage space; executing dense vector search with hypothesis vector.
- **Excluded behavior:** Presenting hypothetical passages to the user as factual answers.
- **Implementation boundaries:** `app/retrieval/hyde.py`, `app/retrieval/dense.py`.
- **Integration points:** Activated when `RetrievalConfig.expansion_mode == "hyde"`.
- **Source-of-truth files:** `app/retrieval/hyde.py`, `app/retrieval/types.py`.
- **Supported inputs:** User question string `query: str`.
- **Input validation rules:** Length between 10 and 256 characters.
- **Output schema:** `str` representing synthetic regulatory circular excerpt (e.g. "Reserve Bank of India / Department of Regulation / Notification...").
- **Configuration schema:** `HyDEConfig(enabled: bool = False, max_tokens: int = 120, temperature: float = 0.0)`.
- **Default values:** `enabled = False`, `max_tokens = 120`, `temperature = 0.0`.
- **Dependencies:** BAAI/bge-small-en-v1.5 embedder, local deterministic template engine or fast inference worker.
- **Compatibility requirements:** Must be entirely bypassable via `expansion_mode="none"`.
- **Authorization rules:** Standard search authorization.
- **Data isolation rules:** Generated hypothetical strings are strictly ephemeral and never stored in production database.
- **Error behavior:** If generation fails or times out (300ms limit), immediately fall back to standard raw query embedding.
- **Fallback behavior:** Direct raw query dense embedding.
- **Observability requirements:** Counter `docscout_hyde_invocations_total`, duration histogram `docscout_hyde_generation_seconds`.
- **Performance limits:** Template-based HyDE $\le 1.0\text{ ms}$; LLM-assisted HyDE $\le 350\text{ ms}$ (budgeted).
- **Resource limits:** Token generation budget capped at 120 tokens.
- **Acceptance criteria:** On the low-leakage query band ($<0.5$ term overlap), HyDE improves dense Recall@5 by $\ge 8.0\text{ pp}$.
- **Evaluation dataset:** Low-leakage query subset of `evals/gold/v1/gold.jsonl` ($n=54$ items).
- **Evaluation baseline:** Dense baseline Recall@5 = 0.722 on low-leakage band.
- **Required improvement threshold:** HyDE Dense Recall@5 $\ge 0.810$.
- **Regression limits:** Zero drop on exact-ID queries (guaranteed by arm-anchored fusion).
- **Completion criteria:** Benchmark report committed under `evals/reports/` validating statistical significance.

---

## FEAT-015: Audience & Difficulty Banding Filter
- **Objective:** Enable audience-specific snippet granularity and summary depth by tagging content and filtering queries according to the 4 taxonomy difficulty levels (`foundational`, `intermediate`, `advanced`, `expert`).
- **In-scope behavior:** Metadata filtering by target difficulty band; adapting snippet token window size based on difficulty level (shorter executive summaries for `foundational`, complete multi-clause extracts for `expert`).
- **Excluded behavior:** Hiding regulatory text entirely from users without authorization.
- **Implementation boundaries:** `app/api/models.py`, `app/retrieval/search.py`.
- **Integration points:** `SearchRequest.difficulty_band` parameter; snippet truncation logic in `Passage` constructor.
- **Source-of-truth files:** `do not commit!/lexicon.json` (`terms[].level`), `app/api/models.py`.
- **Supported inputs:** `difficulty_band: Optional[Literal["foundational", "intermediate", "advanced", "expert"]]`.
- **Input validation rules:** Must match allowed literal string or be `None`.
- **Output schema:** `Passage.difficulty_level: str`, adapted `Passage.text` window length.
- **Configuration schema:** `DifficultyConfig(default_level: str = "intermediate", max_expert_tokens: int = 512, max_foundational_tokens: int = 150)`.
- **Default values:** `difficulty_band = None` (returns full neutral passage).
- **Dependencies:** Pure Python schema and slice logic.
- **Compatibility requirements:** Backward-compatible; defaults to full passages when omitted.
- **Authorization rules:** Publicly accessible across all authenticated roles.
- **Data isolation rules:** Difficulty classifications are public taxonomy attributes.
- **Error behavior:** Invalid level returns HTTP 422 validation error.
- **Fallback behavior:** Omission returns standard 1,000-character chunk window.
- **Observability requirements:** Log `difficulty_band` in structlog search audit line.
- **Performance limits:** Snippet formatting overhead $\le 0.1\text{ ms}$.
- **Resource limits:** Zero extra memory consumption.
- **Acceptance criteria:** Foundational requests return concise $\le 150$-token plain-language summaries; expert requests return full statutory clauses.
- **Evaluation dataset:** 40 queries tested across all 4 difficulty levels.
- **Evaluation baseline:** Monolithic 1,000-char snippet returned to all users regardless of role.
- **Required improvement threshold:** 100% adherence to token window bounds per difficulty band.
- **Regression limits:** Zero loss of cited provenance spans or chunk UUID references.
- **Completion criteria:** Unit tests pass in `tests/test_difficulty_banding.py`.

---

## FEAT-016: Query Tagging & Metadata Constrained Retrieval
- **Objective:** Extract domain tags from incoming queries against the 45 taxonomy tags (`security`, `compliance`, `apis`, `audit`, etc.) to automatically apply strict SQL `WHERE` clauses, boosting precision.
- **In-scope behavior:** Tag extraction via multi-word regex vocabulary; translating tags into SQL `MetadataFilter` parameters; executing filtered pgvector search.
- **Excluded behavior:** Filtering on tags with low confidence ($< 0.85$) that might prematurely eliminate valid results.
- **Implementation boundaries:** `app/retrieval/query_tagger.py`, `app/retrieval/dense.py`.
- **Integration points:** Pre-search phase in `app/retrieval/search.py`.
- **Source-of-truth files:** `do not commit!/lexicon.json` (`indices.byTag`), `app/retrieval/query_tagger.py`.
- **Supported inputs:** Query string `query: str`, `auto_constrain: bool = False`.
- **Input validation rules:** Query length $\ge 3$ characters.
- **Output schema:** `list[str]` containing extracted taxonomy tags (e.g. `["security", "audit"]`).
- **Configuration schema:** `QueryTaggerConfig(auto_constrain: bool = False, min_tag_confidence: float = 0.90)`.
- **Default values:** `auto_constrain = False` (tags are surfaced as facets unless explicitly requested).
- **Dependencies:** Compiled keyword mapping from `lexicon.indices.byTag`.
- **Compatibility requirements:** Fully compatible with manual user-specified `MetadataFilter`.
- **Authorization rules:** Standard search authorization.
- **Data isolation rules:** Completely stateless.
- **Error behavior:** Tagging failure logs warning and proceeds with unconstrained query.
- **Fallback behavior:** Unconstrained hybrid retrieval.
- **Observability requirements:** Log `extracted_tags` in structlog; metric `docscout_tags_extracted_total{tag}`.
- **Performance limits:** Tag extraction latency $\le 0.3\text{ ms}$ p95.
- **Resource limits:** Memory footprint $\le 2\text{ MB}$.
- **Acceptance criteria:** Accurately extracts tags from $\ge 95\%$ of domain-specific regulatory queries.
- **Evaluation dataset:** 100 domain-specific queries across cybersecurity, capital adequacy, and payment systems.
- **Evaluation baseline:** Unconstrained retrieval suffering occasional cross-domain sector bleed.
- **Required improvement threshold:** Retrieval precision@5 improves by $\ge 6.0\text{ pp}$ when auto-constrained.
- **Regression limits:** Zero drop in Recall@10 on gold evaluation baseline.
- **Completion criteria:** Unit tests pass in `tests/test_query_tagger.py`.

---

## FEAT-017: Multi-Turn Conversational Coreference Resolver
- **Objective:** Resolve anaphoric pronouns and conversational ellipses across chat turns (e.g., "What are its exceptions?", "Does that apply to NBFCs too?") by anchoring context to previously cited circulars.
- **In-scope behavior:** Tracking circular IDs and entities from recent turns in user session; rewriting incomplete query into standalone canonical regulatory query before retrieval.
- **Excluded behavior:** Arbitrary open-domain conversation tracking; multi-session cross-user context bleed.
- **Implementation boundaries:** `app/api/chat.py`, `app/retrieval/coreference.py`.
- **Integration points:** `/v1/chat` endpoint; pre-retrieval query rewriting stage.
- **Source-of-truth files:** `app/api/chat.py`, `app/retrieval/coreference.py`.
- **Supported inputs:** Current user query `message: str`, recent turn history `history: list[ChatMessage]`.
- **Input validation rules:** History length $\le 10$ turns; message length $\le 512$ chars.
- **Output schema:** `CoreferenceResolution(rewritten_query: str, resolved_entities: list[str], referenced_circular_ids: list[str])`.
- **Configuration schema:** `ChatConfig(max_history_turns: int = 5, coreference_model: str = "fast-rule")`.
- **Default values:** `max_history_turns = 5`, `coreference_model = "fast-rule"`.
- **Dependencies:** Session store in Redis or in-memory LRU; fast pronoun replacement engine.
- **Compatibility requirements:** Seamlessly callable from UI chat console.
- **Authorization rules:** Requires authenticated user session matching tenant context.
- **Data isolation rules:** Session histories strictly isolated by `user_id` and wiped on session terminate.
- **Error behavior:** If coreference rewriting fails, submit original message unmodified.
- **Fallback behavior:** Original un-rewritten user message submitted to search.
- **Observability requirements:** Counter `docscout_coreferences_resolved_total`, structlog key `rewritten_query`.
- **Performance limits:** Coreference rewriting latency $\le 2.0\text{ ms}$ for rule engine.
- **Resource limits:** Memory allocation $\le 10\text{ KB}$ per active user session.
- **Acceptance criteria:** Successfully resolves $\ge 90\%$ of coreference ambiguity in multi-turn regulatory dialogues.
- **Evaluation dataset:** 25 multi-turn regulatory conversation transcripts ($n=75$ follow-up turns).
- **Evaluation baseline:** 14% success rate on follow-up turns with naive standalone search.
- **Required improvement threshold:** Follow-up turn Retrieval Recall@5 $\ge 0.850$.
- **Regression limits:** Rewriting must not alter queries that are already standalone.
- **Completion criteria:** Multi-turn chat tests pass in `tests/test_chat_coreference.py`.

---

## FEAT-018: Typo-Tolerant Regulatory Token Normalizer
- **Objective:** Specialized fuzzy token matcher calibrated against the 1,358 lexicon terms and official circular numbering syntax to correct user misspellings without corrupting legal references.
- **In-scope behavior:** Symmetric Delete / Damerau-Levenshtein distance matching (max distance 2); vocabulary restricted to valid regulatory entities, acts, and lexicon terms; circular ID regex protection.
- **Excluded behavior:** "Correcting" unfamiliar but valid statutory section numbers; aggressive general English autocorrect.
- **Implementation boundaries:** `app/retrieval/normalizer.py`.
- **Integration points:** Query ingestion stage in `app/retrieval/search.py`.
- **Source-of-truth files:** `do not commit!/lexicon.json` (`terms[].term`), `app/retrieval/normalizer.py`.
- **Supported inputs:** Clean query string `query: str`.
- **Input validation rules:** Length $\le 512$ characters.
- **Output schema:** `NormalizedQuery(normalized_query: str, corrections_applied: dict[str, str])`.
- **Configuration schema:** `NormalizerConfig(enabled: bool = True, max_edit_distance: int = 2)`.
- **Default values:** `enabled = True`, `max_edit_distance = 2`.
- **Dependencies:** Precomputed SymSpell dictionary built from lexicon terms.
- **Compatibility requirements:** Pure Python execution, zero native compilation required.
- **Authorization rules:** Standard search authorization.
- **Data isolation rules:** Stateless dictionary lookup.
- **Error behavior:** Normalizer failure returns original query string with error log.
- **Fallback behavior:** Raw query passed through to search.
- **Observability requirements:** Metric `docscout_typos_corrected_total{term}`, structlog `corrections`.
- **Performance limits:** Typo normalization latency $\le 0.5\text{ ms}$ p95.
- **Resource limits:** Memory footprint $\le 6\text{ MB}$ for SymSpell dictionary.
- **Acceptance criteria:** Recovers 100% of single-transposition and single-deletion errors in regulatory terms (e.g. "Paymnet Agregator" -> "Payment Aggregator").
- **Evaluation dataset:** 60 queries containing deliberate statutory typos.
- **Evaluation baseline:** 0% typo tolerance in legacy BM25 index (resulting in zero results).
- **Required improvement threshold:** Typo query Recall@5 recovery $\ge 0.900$.
- **Regression limits:** Zero false corrections on valid rare statutory terms.
- **Completion criteria:** Unit tests pass in `tests/test_normalizer.py`.

---

## FEAT-019: Interactive Search Query Suggestions
- **Objective:** High-speed autocomplete and related-query suggestion API powered by `lexicon.terms[].related` graph edges, guiding analysts as they compose queries.
- **In-scope behavior:** Prefix matching against taxonomy terms and acronyms; surfacing related concepts via 1-hop graph edges; returning ranked suggestion list.
- **Excluded behavior:** Unbounded full-text search during autocomplete typing.
- **Implementation boundaries:** `app/api/app.py` (`GET /v1/search/suggest`), `ui/src/components/SearchAutocomplete.tsx`.
- **Integration points:** React console search bar; OpenAPI endpoint.
- **Source-of-truth files:** `do not commit!/lexicon.json` (`terms`, `related`), `ui/src/components/SearchAutocomplete.tsx`.
- **Supported inputs:** Query prefix `q: str`, limit `limit: int = 5`.
- **Input validation rules:** $2 \le \text{len}(q) \le 64$; $1 \le \text{limit} \le 10$.
- **Output schema:** `SuggestionResponse(prefix: str, suggestions: list[SuggestionItem(term: str, category: str, type: str, score: float)])`.
- **Configuration schema:** `SuggestConfig(cache_ttl_seconds: int = 3600, min_prefix_length: int = 2)`.
- **Default values:** `limit = 5`, `min_prefix_length = 2`.
- **Dependencies:** In-memory Radix Trie loaded at application startup.
- **Compatibility requirements:** Sub-15ms response time to ensure responsive client-side typing.
- **Authorization rules:** Publicly callable within authenticated session (`search:read`).
- **Data isolation rules:** Public taxonomy dictionary only.
- **Error behavior:** Prefix lookup failure returns empty suggestion list `[]` with HTTP 200.
- **Fallback behavior:** Empty suggestions; user proceeds with free-form query.
- **Observability requirements:** Route `/v1/search/suggest` tracked in Prometheus; duration histogram.
- **Performance limits:** Response latency $\le 8.0\text{ ms}$ p95.
- **Resource limits:** In-memory Radix Trie $\le 3\text{ MB}$.
- **Acceptance criteria:** Returns relevant regulatory suggestions within 10ms for all valid statutory prefixes $\ge 2$ characters.
- **Evaluation dataset:** 100 statutory query prefix tests.
- **Evaluation baseline:** Zero autocomplete in legacy console UI.
- **Required improvement threshold:** 100% prefix match accuracy on canonical taxonomy terms.
- **Regression limits:** Zero impact on main API server memory or event loop.
- **Completion criteria:** Playwright E2E test `tests_e2e/test_autocomplete.spec.ts` passes.

---

## FEAT-020: Persona-Tailored Query Profiling
- **Objective:** Provide configurable search profiles tailored to distinct enterprise personas (`Statutory Auditor`, `Fintech Architect`, `Chief Risk Officer`) that dynamically adapt retrieval weights and expansion modes.
- **In-scope behavior:** Persona parameter in API request; adjusting BM25 vs Dense weights (Auditors favor exact lexical hits; Architects favor dense semantic concepts); configuring default HyDE and expansion settings.
- **Excluded behavior:** Arbitrary hardcoded user tier restrictions on public legal text.
- **Implementation boundaries:** `app/retrieval/persona.py`, `app/retrieval/types.py`.
- **Integration points:** `SearchRequest.persona` in `app/api/models.py`.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`terms[].roles`), `app/retrieval/persona.py`.
- **Supported inputs:** `persona: Optional[Literal["auditor", "architect", "risk_officer", "compliance_lead"]]`.
- **Input validation rules:** Must match allowed literal enum or be `None`.
- **Output schema:** Internal `RetrievalConfig` adjusted per persona profile.
- **Configuration schema:** `PersonaProfiles(auditor: ProfileSettings, architect: ProfileSettings, ...)`.
- **Default values:** `persona = None` (uses standard neutral `hybrid-rrf` config).
- **Dependencies:** Pure Python configuration mapper.
- **Compatibility requirements:** 100% backward-compatible; missing persona uses default config.
- **Authorization rules:** Available to all authenticated callers.
- **Data isolation rules:** Stateless profile application.
- **Error behavior:** Invalid persona returns HTTP 422 with supported persona list.
- **Fallback behavior:** Defaults to neutral `SERVING_CONFIG`.
- **Observability requirements:** Counter `docscout_queries_by_persona_total{persona}`, structlog logging.
- **Performance limits:** Profile resolution overhead $\le 0.05\text{ ms}$.
- **Resource limits:** Zero extra memory.
- **Acceptance criteria:** Auditor persona achieves 100% precision on exact circular clauses; Architect persona achieves $\ge 0.95$ recall on architectural implementation patterns.
- **Evaluation dataset:** 50 persona-stratified regulatory queries.
- **Evaluation baseline:** Single static `hybrid-rrf` configuration for all user types.
- **Required improvement threshold:** Persona-specific user satisfaction rating $+25\%$; MRR $+0.035$ per persona slice.
- **Regression limits:** Baseline neutral config performance must remain unchanged.
- **Completion criteria:** Unit tests pass in `tests/test_persona_profiling.py`.
