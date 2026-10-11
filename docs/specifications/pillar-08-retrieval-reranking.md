# Pillar 8 Specification: Advanced Retrieval, Reranking & Evidence Synthesis
*DocScout Enterprise Regulatory Intelligence Engine*

---

## FEAT-071: Cross-Encoder Candidate Rerank Ladder
- **Objective:** Implement a latency-budgeted multi-stage reranking architecture: RRF initial fusion pools 64 candidates, which are dynamically filtered and scored by a cross-encoder model down to final top-k.
- **In-scope behavior:** Batching 64 candidate pairs `(query, passage_text)`; scoring with cross-encoder transformer (`ms-marco-MiniLM-L-6-v2`); ordering by cross-attention score; enforcing a strict 40ms timeout circuit breaker.
- **Excluded behavior:** Unbounded candidate pool sizes ($>64$) that exceed inference latency budgets; sequential un-batched scoring.
- **Implementation boundaries:** `app/retrieval/rerank.py`, `app/retrieval/search.py`.
- **Integration points:** `Retriever._rerank()` in `app/retrieval/search.py`; `CrossEncoderReranker` in `app/retrieval/rerank.py`.
- **Source-of-truth files:** `app/retrieval/rerank.py`, `app/retrieval/types.py`.
- **Supported inputs:** Query string `query: str`, candidate passages `candidates: list[Candidate]`, `top_k: int = 10`.
- **Input validation rules:** `len(candidates) >= top_k`; `query` non-empty; candidate text length $\le 512$ tokens.
- **Output schema:** `list[Candidate]` reordered in descending order of cross-encoder logit scores.
- **Configuration schema:** `RetrievalConfig.rerank_top_n: int = 64`, `RetrievalConfig.rerank_batch_size: int = 16`, `RetrievalConfig.rerank_timeout_ms: int = 40`.
- **Default values:** `rerank_top_n = 50`, `rerank_batch_size = 16`, `rerank_timeout_ms = 40`.
- **Dependencies:** `sentence-transformers` / `torch` (CPU optimized with ONNX Runtime or float32).
- **Compatibility requirements:** Fallback to pre-rerank RRF order if timeout triggers, maintaining deterministic tiebreak on chunk UUID.
- **Authorization rules:** Internal retrieval engine component; inherits caller search authorization.
- **Data isolation rules:** Operates in-memory on caller's candidate pool; zero per-query persistence.
- **Error behavior:** Inference timeout or model exception logs warning with correlation ID and preserves pre-rerank candidate order.
- **Fallback behavior:** Pre-rerank RRF candidate ranking returned without score disruption.
- **Observability requirements:** Histogram `docscout_rerank_duration_seconds`, counter `docscout_rerank_circuit_breaker_trips_total`.
- **Performance limits:** 64-candidate reranking executed in $\le 32.0\text{ ms}$ on 4-core CPU; p95 under 40ms.
- **Resource limits:** Memory allocation $\le 120\text{ MB}$ for model weights in memory.
- **Acceptance criteria:** Increases Recall@5 and nDCG@5 by $\ge 3.0\text{ pp}$ over raw RRF across the 365 scored gold set items.
- **Evaluation dataset:** `evals/gold/v1/gold.jsonl` (365 scored items).
- **Evaluation baseline:** Current baseline `hybrid-rrf` without cross-encoder rerank (nDCG@5 = 0.867).
- **Required improvement threshold:** nDCG@5 $\ge 0.895$ ($+2.8\text{ pp}$).
- **Regression limits:** P95 retrieval latency must remain $\le 50.0\text{ ms}$ cold.
- **Completion criteria:** Validated via `make bench` and committed under `evals/reports/`.

---

## FEAT-072: Lost-in-the-Middle Context Reordering
- **Objective:** Reorder retrieved passages before presenting them to the user or downstream LLM, placing the highest-scoring evidence at the beginning and end of the context window to counter transformer attention degradation.
- **In-scope behavior:** Sorting retrieved candidates by score; distributing items using alternating boundary placement (Rank 1 at position 0, Rank 2 at position $N-1$, Rank 3 at position 1, Rank 4 at position $N-2$); preserving citation provenance markers.
- **Excluded behavior:** Truncating or dropping passages during reordering.
- **Implementation boundaries:** `app/retrieval/context_reorder.py`, `app/retrieval/search.py`.
- **Integration points:** Post-reranking stage in `Retriever.retrieve()` immediately before response compilation.
- **Source-of-truth files:** `app/retrieval/context_reorder.py`.
- **Supported inputs:** Ordered passage candidate list `passages: list[Passage]`.
- **Input validation rules:** `passages` non-empty list.
- **Output schema:** `list[Passage]` with reordered positional sequence and updated `presentation_rank` metadata.
- **Configuration schema:** `RetrievalConfig.enable_lost_in_middle_reordering: bool = True`.
- **Default values:** `enable_lost_in_middle_reordering = True`.
- **Dependencies:** Pure Python standard library list manipulation.
- **Compatibility requirements:** Monotonic preservation of passage content and chunk IDs.
- **Authorization rules:** Internal retrieval engine component.
- **Data isolation rules:** In-memory transformation only.
- **Error behavior:** If reordering raises unexpected exception, return passages in standard descending order.
- **Fallback behavior:** Standard descending score order.
- **Observability requirements:** Log `context_reordering_applied: True` in search metadata.
- **Performance limits:** Reordering execution latency $\le 0.05\text{ ms}$ for 10 passages.
- **Resource limits:** Zero extra memory.
- **Acceptance criteria:** Reordered context exhibits verified U-shaped relevance distribution (highest relevance at ends).
- **Evaluation dataset:** 50 multi-passage question answering evaluations.
- **Evaluation baseline:** Monolithic descending order where key evidence placed in the middle suffered 22% lower attention utilization.
- **Required improvement threshold:** Downstream claim extraction recall improves by $\ge 8.5\text{ pp}$.
- **Regression limits:** Zero change to underlying passage relevance scores.
- **Completion criteria:** Unit tests pass in `tests/test_context_reorder.py`.

---

## FEAT-073: Token-Budget Dynamic Context Packing
- **Objective:** Dynamically pack retrieved passages to fill a precise 95% token budget ceiling, trimming lower-relevance periphery while preserving complete statutory sentences.
- **In-scope behavior:** Counting tokens using target tokenizer; packing top-scoring passages until 95% ceiling is reached; sentence-boundary trimming on the final boundary chunk to prevent dangling half-sentences; discarding overflow chunks.
- **Excluded behavior:** Arbitrarily slicing passages in the middle of words or regulatory clauses.
- **Implementation boundaries:** `app/retrieval/context_packer.py`, `app/retrieval/search.py`.
- **Integration points:** Context compilation in `app/retrieval/search.py` and `app/api/app.py`.
- **Source-of-truth files:** `app/retrieval/context_packer.py`, `app/retrieval/types.py`.
- **Supported inputs:** `passages: list[Passage]`, `max_context_tokens: int = 2048`, `target_utilization: float = 0.95`.
- **Input validation rules:** `max_context_tokens >= 256`; `0.5 <= target_utilization <= 1.0`.
- **Output schema:** `PackedContext(packed_passages: list[Passage], total_tokens: int, utilization_ratio: float, truncated_boundary_chunk: bool)`.
- **Configuration schema:** `ContextPackerConfig(max_tokens: int = 2048, sentence_boundary_trim: bool = True)`.
- **Default values:** `max_tokens = 2048`, `sentence_boundary_trim = True`.
- **Dependencies:** Tiktoken / HuggingFace fast tokenizer.
- **Compatibility requirements:** Thread-safe execution; compatible with any model context limit.
- **Authorization rules:** Internal retrieval engine component.
- **Data isolation rules:** In-memory packing; stateless.
- **Error behavior:** Packing error returns top-3 passages untrimmed with diagnostic warning.
- **Fallback behavior:** Fixed top-k truncation fallback.
- **Observability requirements:** Gauge `docscout_context_token_utilization_ratio`, counter `docscout_context_packs_completed_total`.
- **Performance limits:** Context packing execution $\le 0.8\text{ ms}$ p95.
- **Resource limits:** Memory allocation $\le 1\text{ MB}$.
- **Acceptance criteria:** Context token count is strictly $\le \text{ceiling}$ and achieves $\ge 90\%$ utilization across all queries.
- **Evaluation dataset:** 100 queries tested across context budgets of 1024, 2048, and 4096 tokens.
- **Evaluation baseline:** Fixed top-5 passage return resulting in erratic token lengths (often spilling over or wasting 50% of budget).
- **Required improvement threshold:** Token budget utilization variance $\le 5\%$.
- **Regression limits:** Zero sentence boundary truncations in packed evidence.
- **Completion criteria:** Unit tests pass in `tests/test_context_packer.py`.

---

## FEAT-074: Arm-Anchored Fusion with Provenance Guarantees (ADR-0007 Expansion)
- **Objective:** Guarantee that the absolute top-1 candidate from each retrieval arm (lexical BM25 and dense BGE) is strictly preserved in the final reranked candidate set, regardless of score variance, preventing loss of exact statutory circular IDs.
- **In-scope behavior:** Identifying arm leaders during candidate generation; injecting arm leaders into the rerank candidate pool; anchoring leaders into final top-k if rerank scores fall below survival threshold; recording provenance anchor flags.
- **Excluded behavior:** Forcing low-scoring arm leaders into Rank 1 if an overwhelming consensus candidate exists.
- **Implementation boundaries:** `app/retrieval/search.py` (`_anchor_arm_leaders()`), `app/retrieval/types.py`.
- **Integration points:** Post-rerank selection phase in `app/retrieval/search.py`.
- **Source-of-truth files:** `app/retrieval/search.py`, `docs/decisions/0007-arm-anchored-fusion.md`.
- **Supported inputs:** Reranked candidates `candidates: list[Candidate]`, arm leaders `arm_leaders: dict[str, Candidate]`, target `k: int`.
- **Input validation rules:** `k >= 1`; `candidates` non-empty.
- **Output schema:** `list[Candidate]` containing exactly `k` items with guaranteed presence of arm leaders.
- **Configuration schema:** `RetrievalConfig.anchor_arm_leaders: bool = True`.
- **Default values:** `anchor_arm_leaders = True`.
- **Dependencies:** Pure Python list surgery.
- **Compatibility requirements:** Enforces ADR-0007 formal decision invariant.
- **Authorization rules:** Internal retrieval engine component.
- **Data isolation rules:** In-memory transformation.
- **Error behavior:** If anchoring logic encounters unexpected state, return top-k candidates unanchored with warning.
- **Fallback behavior:** Pure score-based top-k selection.
- **Observability requirements:** Counter `docscout_arm_leaders_anchored_total{arm_name}`.
- **Performance limits:** Anchoring execution overhead $\le 0.05\text{ ms}$.
- **Resource limits:** Zero extra memory.
- **Acceptance criteria:** Exact circular number queries (e.g. "DOR.CRE.REC.No. 60/08.12.001/2023-24") retain 100% Recall@1 regardless of dense semantic noise.
- **Evaluation dataset:** 35 exact circular ID queries from evaluation benchmark.
- **Evaluation baseline:** Non-anchored fusion where dense embedding noise occasionally washed out exact BM25 hits to rank 4 or 5.
- **Required improvement threshold:** Exact-ID Recall@1 = 1.000 (100% retention).
- **Regression limits:** Zero degradation to dense semantic retrieval on conceptual queries.
- **Completion criteria:** Passes `tests/test_arm_anchoring.py` and regression gate `make eval-gate`.

---

## FEAT-075: Section-Aware Context Window Expansion
- **Objective:** When a retrieved chunk is a subsection or legal proviso, automatically pull adjacent sibling clauses from the same section to provide complete legal context and prevent out-of-context misinterpretation.
- **In-scope behavior:** Inspecting `clause_hierarchy` of top-1 retrieved chunk; querying database for preceding and following clauses within the same statutory section; stitching sibling clauses into an expanded context envelope.
- **Excluded behavior:** Expanding chunks across unrelated circular chapters or sections.
- **Implementation boundaries:** `app/retrieval/section_expander.py`, `app/retrieval/search.py`.
- **Integration points:** Post-retrieval expansion phase before context presentation.
- **Source-of-truth files:** `app/retrieval/section_expander.py`, `migrations/0012_hierarchical_chunking.up.sql`.
- **Supported inputs:** Top passage candidate `passage: Passage`, `max_sibling_clauses: int = 2`.
- **Input validation rules:** `passage.chunk_id` valid UUID; $1 \le \text{max\_sibling\_clauses} \le 4$.
- **Output schema:** `ExpandedPassage(core_chunk_id: UUID, expanded_text: str, sibling_chunks: list[ChunkRow], total_chars: int)`.
- **Configuration schema:** `RetrievalConfig.expand_section_context: bool = True`.
- **Default values:** `expand_section_context = True`.
- **Dependencies:** PostgreSQL index on `chunks(document_id, char_start)`.
- **Compatibility requirements:** Maintains original `core_chunk_id` as primary citation anchor.
- **Authorization rules:** Inherits caller search authorization.
- **Data isolation rules:** Bound to immutable document version; respects `is_synthetic` isolation.
- **Error behavior:** If sibling lookup fails, return core passage unexpanded with diagnostic log.
- **Fallback behavior:** Core passage returned unexpanded.
- **Observability requirements:** Counter `docscout_section_expansions_total`, duration histogram.
- **Performance limits:** Sibling chunk fetch and stitch latency $\le 2.5\text{ ms}$ p95.
- **Resource limits:** Database fetch limited to max 2 adjacent rows.
- **Acceptance criteria:** When a standalone penalty clause is retrieved, the operative violation rule defined in the preceding subsection is automatically included in context.
- **Evaluation dataset:** 20 regulatory qualification and penalty queries.
- **Evaluation baseline:** Standalone clause return lacking operative legal context.
- **Required improvement threshold:** Legal context completeness score $\ge 0.94$.
- **Regression limits:** Token length must not violate packed context ceilings.
- **Completion criteria:** Verified in `tests/test_section_expander.py`.

---

## FEAT-076: Cross-Lingual Semantic Regulatory Search
- **Objective:** Support searching in Hindi or English and retrieving relevant statutory clauses regardless of whether the source circular was drafted in English or Hindi.
- **In-scope behavior:** Utilizing multilingual embedding space (`bge-m3` or multilingual dense adapter); projecting cross-lingual query embeddings into shared vector space; retrieving corresponding statutory passages across language boundaries.
- **Excluded behavior:** Low-quality automated translation that corrupts legal jargon.
- **Implementation boundaries:** `app/retrieval/multilingual_dense.py`, `app/retrieval/port.py`.
- **Integration points:** `VectorStore` adapter in `app/retrieval/port.py`.
- **Source-of-truth files:** `app/retrieval/multilingual_dense.py`, `app/retrieval/types.py`.
- **Supported inputs:** Query string in Hindi (Devanagari script) or English `query: str`.
- **Input validation rules:** Valid UTF-8 string, length between 3 and 512 characters.
- **Output schema:** Standard `SearchResponse` containing relevant passages across English and Hindi gazette texts.
- **Configuration schema:** `RetrievalConfig.vector_store_adapter: str = "multilingual_dense"`.
- **Default values:** `vector_store_adapter = "pgvector"`.
- **Dependencies:** Multilingual vector embedder, PostgreSQL pgvector.
- **Compatibility requirements:** Plugs cleanly into `VectorStore` Protocol defined in `app/retrieval/port.py`.
- **Authorization rules:** Standard search authorization.
- **Data isolation rules:** Strictly stateless embedding projection.
- **Error behavior:** Multilingual model failure falls back to standard English BGE embedder with log.
- **Fallback behavior:** Standard English embedder fallback.
- **Observability requirements:** Counter `docscout_cross_lingual_queries_total{lang}`.
- **Performance limits:** Multilingual vector embedding generation $\le 18.0\text{ ms}$ on CPU.
- **Resource limits:** Memory footprint $\le 250\text{ MB}$ for multilingual model weights.
- **Acceptance criteria:** Queries submitted in Devanagari Hindi (e.g. "भुगतान एग्रीगेटर के लिए पूंजी आवश्यकता") successfully retrieve the corresponding English RBI Payment Aggregator circular.
- **Evaluation dataset:** 25 paired bilingual regulatory queries evaluated against bilingual gazette corpus.
- **Evaluation baseline:** 0% cross-lingual retrieval in baseline (Devanagari queries yielded zero English results).
- **Required improvement threshold:** Cross-lingual Recall@5 $\ge 0.880$.
- **Regression limits:** English-to-English retrieval accuracy must not regress ($\Delta \le 0.002$).
- **Completion criteria:** Verified in `tests/test_cross_lingual_retrieval.py`.

---

## FEAT-077: Confidence-Calibrated Selective Refusal (Abstention Gate)
- **Objective:** Compute an evidence coverage score (query terms $\cap$ passage terms); trigger explicit refusal when confidence falls below calibrated 0.65 threshold: "Every answer cites its source or it refuses to answer."
- **In-scope behavior:** Evaluating evidence density across top-5 passages; calculating coverage ratio; asserting confidence score; returning structured refusal status when coverage $< 0.65$; completely suppressing hallucinated speculative answers.
- **Excluded behavior:** Arbitrary refusal on valid complex queries with high term coverage.
- **Implementation boundaries:** `app/retrieval/confidence.py`, `app/api/models.py`.
- **Integration points:** Confidence assessment in `Retriever.retrieve()`; `Passage.confidence` evaluation.
- **Source-of-truth files:** `app/retrieval/confidence.py`, `app/evals/abstention.py`.
- **Supported inputs:** Clean query string `query: str`, retrieved candidate passages `passages: list[Passage]`.
- **Input validation rules:** `len(passages) >= 1`.
- **Output schema:** `Confidence(score: float, level: Literal["HIGH", "MEDIUM", "LOW"], is_refusal: bool, refusal_reason: Optional[str])`.
- **Configuration schema:** `ConfidenceConfig(low_evidence_threshold: float = 0.65, coverage_depth: int = 5)`.
- **Default values:** `low_evidence_threshold = 0.65`, `coverage_depth = 5`.
- **Dependencies:** Python regex term tokenizer, set intersection operations.
- **Compatibility requirements:** Pure Python execution; zero external dependencies.
- **Authorization rules:** Internal retrieval engine component.
- **Data isolation rules:** In-memory score calculation.
- **Error behavior:** If confidence calculation fails, default to conservative refusal (`is_refusal = True`) to prevent hallucinations.
- **Fallback behavior:** Fail-closed: returns explicit refusal.
- **Observability requirements:** Counter `docscout_abstention_events_total{level}`, histogram `docscout_confidence_scores`.
- **Performance limits:** Confidence score calculation $\le 0.2\text{ ms}$.
- **Resource limits:** Zero extra memory.
- **Acceptance criteria:** 100% refusal rate on the 60 unanswerable canary questions in `gold.jsonl`, with zero false rejections on high-confidence answerable items.
- **Evaluation dataset:** 60 unanswerable test queries + 365 answerable gold queries in `evals/gold/v1/gold.jsonl`.
- **Evaluation baseline:** Current baseline separation AUC = 0.730.
- **Required improvement threshold:** Separation AUC $\ge 0.820$; Selective Accuracy on answered queries $\ge 0.980$.
- **Regression limits:** False rejection rate on answerable queries $\le 2.0\%$.
- **Completion criteria:** Validated by `make eval-gate` in CI.

---

## FEAT-078: Sub-Sentence Evidence Highlighting & Span Pinpointing
- **Objective:** Calculate sentence-level cross-attention weights to pinpoint the exact 1-2 operative sentences within a 1,000-character chunk, highlighting them in bright amber in the console UI.
- **In-scope behavior:** Splitting retrieved passage into sentences; scoring each sentence against query using cross-encoder sentence scoring; identifying highest-scoring span; returning exact character offsets `[highlight_start, highlight_end]`.
- **Excluded behavior:** Arbitrary keyword highlighting that ignores semantic query intent.
- **Implementation boundaries:** `app/retrieval/span_pinpoint.py`, `app/api/models.py`.
- **Integration points:** Post-rerank decoration in `Retriever.retrieve()`; returned in `Passage.highlights`.
- **Source-of-truth files:** `app/retrieval/span_pinpoint.py`, `app/api/models.py`.
- **Supported inputs:** Query string `query: str`, passage text `text: str`.
- **Input validation rules:** `text` non-empty string.
- **Output schema:** `list[HighlightSpan(start: int, end: int, text: str, score: float)]`.
- **Configuration schema:** `HighlightConfig(max_highlight_spans: int = 2, min_sentence_score: float = 0.60)`.
- **Default values:** `max_highlight_spans = 2`, `min_sentence_score = 0.60`.
- **Dependencies:** Fast sentence boundary tokenizer (NLTK / regex), cross-encoder token scorer.
- **Compatibility requirements:** Character offsets must index directly into `Passage.text`.
- **Authorization rules:** Standard search authorization.
- **Data isolation rules:** In-memory calculation.
- **Error behavior:** Sentence scoring failure defaults to full passage return without sub-sentence highlights.
- **Fallback behavior:** Full passage displayed without span highlights.
- **Observability requirements:** Counter `docscout_spans_highlighted_total`.
- **Performance limits:** Span pinpointing latency $\le 2.0\text{ ms}$ for 5 passages.
- **Resource limits:** Zero extra memory.
- **Acceptance criteria:** Sub-sentence highlights achieve $\ge 90\%$ Intersection-over-Union (IoU) overlap with gold standard evidence quote spans.
- **Evaluation dataset:** 150 gold citation quotes in `evals/gold/v1/metadata.json`.
- **Evaluation baseline:** Full 1,000-character chunk displayed to user without guidance on where the answer lies.
- **Required improvement threshold:** Evidence span IoU $\ge 0.90$.
- **Regression limits:** Zero out-of-bounds character index exceptions.
- **Completion criteria:** Verified in `tests/test_span_pinpoint.py`.

---

## FEAT-079: Hard Negative Mining & Discriminative Indexing
- **Objective:** Mine hard negative passages during offline indexing (clauses from similar circulars that discuss different entity classes) to sharpen dense embedding discrimination and eliminate sector confusion.
- **In-scope behavior:** Generating hard negative candidate pairs using BM25 high-overlap / different-entity heuristics; fine-tuning dense projection adapter or calibrating reranker margins; storing negative pair matrices.
- **Excluded behavior:** Altering production raw BGE-small base weights without regression gating.
- **Implementation boundaries:** `scripts/mine_hard_negatives.py`, `app/retrieval/dense.py`.
- **Integration points:** Offline model calibration pipeline; `make mine-negatives`.
- **Source-of-truth files:** `scripts/mine_hard_negatives.py`, `corpus/raw/manifest.json`.
- **Supported inputs:** Ingested corpus chunks, entity taxonomy classifications.
- **Input validation rules:** Minimum 1,000 chunks in corpus.
- **Output schema:** `HardNegativeDataset(triplets: list[tuple[str, str, str]])` representing `(query, positive_chunk_id, negative_chunk_id)`.
- **Configuration schema:** `NegativeMiningConfig(max_negatives_per_positive: int = 5, min_lexical_similarity: float = 0.60)`.
- **Default values:** `max_negatives_per_positive = 5`, `min_lexical_similarity = 0.60`.
- **Dependencies:** Python `torch`, `sentence-transformers`, PostgreSQL BM25 index.
- **Compatibility requirements:** Offline execution script generating training/calibration artifacts.
- **Authorization rules:** Internal developer/operator script.
- **Data isolation rules:** Operates strictly on public circular corpus.
- **Error behavior:** Script logs failure on unindexable triplets and proceeds with valid pairs.
- **Fallback behavior:** Retains uncalibrated baseline embedding weights.
- **Observability requirements:** Record mined triplet count in build artifacts.
- **Performance limits:** Mining 10,000 triplets completed in $\le 5\text{ minutes}$ on standard CPU.
- **Resource limits:** Memory allocation $\le 512\text{ MB}$.
- **Acceptance criteria:** Reduces false-positive retrieval between similar entity classes (e.g. Housing Finance Companies vs Microfinance NBFCs) by $\ge 35\%$.
- **Evaluation dataset:** 40 cross-entity confusion evaluation queries.
- **Evaluation baseline:** Uncalibrated dense search suffering 28% false positive rate on entity boundaries.
- **Required improvement threshold:** False positive rate on cross-entity queries drops to $\le 10\%$.
- **Regression limits:** Zero loss of overall Recall@5 on standard gold set.
- **Completion criteria:** Mining script and validation report committed under `evals/bench/`.

---

## FEAT-080: Multi-Tiered Semantic Caching with Invalidation Webhooks
- **Objective:** In-memory LRU and Redis semantic cache keyed by normalized query embeddings and filters with instant webhook invalidation on circular updates, dropping warm latency to $<2.5\text{ ms}$.
- **In-scope behavior:** Two-tier caching (Tier 1: In-memory OrderedDict LRU; Tier 2: Redis); embedding-based semantic similarity cache hit ($>0.98$ cosine similarity); cache invalidation webhook receiver triggered upon new circular ingestion.
- **Excluded behavior:** Storing user PII or sensitive session tokens in global cache keys.
- **Implementation boundaries:** `app/api/cache.py`, `app/api/app.py` (`POST /v1/admin/cache/invalidate`).
- **Integration points:** Request caching middleware in `app/api/app.py`; invalidation hook in `app/ingest/discovery.py`.
- **Source-of-truth files:** `app/api/cache.py`, `app/api/app.py`.
- **Supported inputs:** Cache key tuple `(query, mode, k, generate_answer, filter_key, expand_query, expansion_mode)`.
- **Input validation rules:** Key must incorporate all search parameters to prevent cache pollution.
- **Output schema:** Cached `SearchResponse` with `cached: True` and execution latency $< 2.5\text{ ms}$.
- **Configuration schema:** `CacheConfig(lru_maxsize: int = 512, ttl_seconds: int = 300, enable_semantic_matching: bool = False)`.
- **Default values:** `lru_maxsize = 512`, `ttl_seconds = 300`, `enable_semantic_matching = False`.
- **Dependencies:** Python `collections.OrderedDict`, `threading.Lock`, optional `redis-py`.
- **Compatibility requirements:** Thread-safe execution; memory safety bounds.
- **Authorization rules:** Invalidation endpoint requires `admin:write` scope or admin API key.
- **Data isolation rules:** Cache keys partitioned by tenant if custom filters are applied.
- **Error behavior:** Cache read/write failure logs warning and executes live retrieval query without user-facing error.
- **Fallback behavior:** Direct database retrieval fallback.
- **Observability requirements:** Prometheus counters `docscout_cache_hits_total`, `docscout_cache_misses_total`, `docscout_cache_invalidations_total`.
- **Performance limits:** Cache hit lookup latency $\le 0.8\text{ ms}$ p95.
- **Resource limits:** Memory footprint $\le 64\text{ MB}$ for 512-entry cached response pool.
- **Acceptance criteria:** Cache hit rate $\ge 65\%$ on recurring queries; warm p95 latency drops from 48ms to 2.11ms.
- **Evaluation dataset:** 500-query benchmark replay (`make bench`).
- **Evaluation baseline:** Current cold query latency 48.11ms.
- **Required improvement threshold:** Warm p95 latency $\le 2.50\text{ ms}$.
- **Regression limits:** Zero stale cache hits following invalidation webhook call.
- **Completion criteria:** Cache benchmarks verified in `evals/bench/bench.json`.
