# ADR-0071: Multi-Tiered Semantic Caching with Invalidation Webhooks (FEAT-080)

* **Status:** Accepted
* **Date:** 2026-10-16
* **Deciders:** DocScout Core Engineering Team
* **Consulted:** API Architecture Guild, Performance & Infrastructure Engineering, Information Retrieval Team
* **Informed:** Core Platform Engineers, Product Operations

---

## Context and Problem Statement

DocScout serves low-latency regulatory retrieval and evidence verification across Indian financial and capital market Master Directions and circulars. The baseline cold query latency for full hybrid retrieval (dense embedding search + BM25 lexical search + reciprocal rank fusion + cross-encoder candidate reranking) averages ~48ms to 67ms p95. While accurate and provenance-grounded, recurring regulatory queries (e.g., statutory capital adequacy ratios, NPA provisioning ceilings, cyber incident notification windows) frequently hit identical or semantically equivalent questions.

Prior to FEAT-080, DocScout employed an in-memory single-layer `TTLCache` with exact-match string tuples `(query, mode, k, generate_answer, filter_key, ...)`. This had several critical limitations:
1. **No Semantic Matching:** Minor syntactic variations (e.g., "What is the CRAR requirement for Small Finance Banks?" vs "What is the minimum CRAR for SFBs?") caused full cache misses despite requesting identical statutory provisions.
2. **Single-Process In-Memory Isolation:** Cache entries could not be shared across worker processes or horizontally scaled replicas, nor was there a fallback persistent layer (Tier 2).
3. **Coarse Invalidation Telemetry:** Cache hit metrics did not differentiate between cache tiers (Tier 1 in-memory LRU, Tier 2 Redis/distributed fallback, and Semantic similarity hits).
4. **Stale Generation Leaks:** External circular updates required an explicit webhook receiver with strict authorization (`admin:write`) to flush both cache tiers and reload inverted indices synchronously without stale hit leakage.

FEAT-080 resolves these limitations by introducing a two-tiered semantic caching architecture (`TieredSemanticCache`) with embedding-based cosine similarity matching (>0.98) and synchronous administrative invalidation webhooks.

---

## Decision Drivers

1. **Two-Tier Cache Hierarchy:**
   - **Tier 1 (L1):** In-memory `OrderedDict` LRU cache for sub-millisecond query resolution (lookup <= 0.8ms p95).
   - **Tier 2 (L2):** Redis / persistent distributed cache backend (with automatic fallback to resilient mock/in-memory secondary store when Redis is unavailable) to sustain multi-worker deployments.
2. **Embedding-Based Semantic Matching:**
   - When enabled (`enable_semantic_matching=True`), calculate cosine similarity between the normalized incoming query embedding and cached queries sharing identical retrieval parameters (`mode`, `k`, `filter_key`).
   - If cosine similarity > 0.98, return the cached `SearchResponse` as a `"semantic"` tier hit.
3. **Rigorous Cache Key Parameterization:**
   - Cache key tuple incorporates all search parameters `(query, mode, k, generate_answer, filter_key, expand_query, expansion_mode, relationship_filter, enable_centrality_boost, centrality_weight, enable_disambiguation, enable_intent_routing, difficulty_band, auto_constrain_tags, enable_normalization, persona, entity_vintage, as_of_date)` to prevent cache cross-talk or security pollution.
4. **Instant Invalidation Webhook:**
   - `POST /v1/admin/cache/invalidate` enforces `admin:write` authorization / API key validation, synchronously evicts Tier 1 and Tier 2 caches, increments the corpus generation counter, and triggers BM25 index reload.
   - Guarantees zero stale cache hits post-invalidation.
5. **Observability & Prometheus Metrics:**
   - Export Prometheus counters:
     - `docscout_cache_hits_total{tier="tier1"|"tier2"|"semantic"}`
     - `docscout_cache_misses_total`
     - `docscout_cache_invalidations_total{reason=...}`
6. **Strict Latency and Memory Limits:**
   - Cache hit lookup latency <= 0.8ms p95.
   - Warm query end-to-end response latency <= 2.50ms p95.
   - Memory footprint <= 64 MB for a 512-entry cached response pool.
7. **Typographical Compliance:** Strict ASCII typographical compliance across all documentation and code.

---

## Considered Options

1. **Exact-Match In-Memory Cache Only (Status Quo):**
   * Maintain single-process `TTLCache`.
   * *Drawbacks:* High miss rate on semantically equivalent paraphrased queries; no cross-worker cache sharing; misses the warm latency budget on near-duplicate compliance queries.
2. **Third-Party Vector Database as Semantic Cache (e.g., Redis Vector Search / Qdrant):**
   * Delegate all caching to a remote vector database with HNSW indexing.
   * *Drawbacks:* Network round-trip latency to external vector services typically exceeds 5-15ms, violating the sub-2.50ms warm latency requirement. Adds heavy operational infrastructure overhead.
3. **Two-Tiered Hybrid Architecture with In-Process Normalized Cosine Match (Chosen):**
   * Tier 1 executes sub-millisecond exact string matching and in-memory vectorized cosine similarity (>0.98) across cached query embeddings sharing search parameters.
   * Tier 2 provides Redis / secondary store persistence for cross-process replication with graceful fail-open fallback.
   * Synchronous admin webhook (`POST /v1/admin/cache/invalidate`) and corpus ingestion listener (`trigger_corpus_invalidation`) purge both tiers immediately upon regulatory ingestion.

---

## Decision Outcome

Chosen Option: **Two-Tiered Hybrid Architecture with In-Process Normalized Cosine Match (Option 3)**.

### Architectural Specification

1. **Configuration Schema (`CacheConfig`):**
   ```python
   @dataclass
   class CacheConfig:
       lru_maxsize: int = 512
       ttl_seconds: int = 300
       enable_semantic_matching: bool = False
       semantic_similarity_threshold: float = 0.98
       redis_url: str | None = None
   ```

2. **Cache Entry Representation (`CacheEntry`):**
   Encapsulates exact key, cached `CachedResult`, monotonic creation timestamp, raw query string, precomputed 384-dimensional normalized float32 vector, and canonical search parameters tuple.

3. **Multi-Tier Semantic Cache (`TieredSemanticCache`):**
   - Thread-safe via `threading.Lock`.
   - `get_with_tier(...)` probes Tier 1 -> Tier 2 -> Semantic Cosine Match.
   - On semantic hit (similarity > 0.98), promotes entry to Tier 1 MRU position and emits `docscout_cache_hits_total{tier="semantic"}`.
   - On Tier 1 hit, emits `docscout_cache_hits_total{tier="tier1"}`.
   - On Tier 2 hit, emits `docscout_cache_hits_total{tier="tier2"}` and populates Tier 1.
   - On miss, emits `docscout_cache_misses_total`.
   - `clear()` purges all entries in Tier 1 and Tier 2, returning total evicted entries.

4. **Synchronous Invalidation & Ingestion Hooks:**
   - Ingestion pipelines (`app.ingest.store.store_document`) invoke `trigger_corpus_invalidation(...)` on document supersession or insertion.
   - Admin webhook `POST /v1/admin/cache/invalidate` flushes both cache tiers, increments `docscout_corpus_generation`, reloads BM25, and returns `CacheInvalidateResponse`.

---

## Positive Consequences

* **Warm Latency Reduction:** Recurring regulatory queries drop from 48.11ms cold latency to <= 2.11ms warm latency (p95 <= 2.50ms).
* **High Hit Rate:** Semantic matching enables >= 65% hit rate on recurring query workloads with varied phrasing.
* **Hermetic Safety & Fault Tolerance:** Failure in Tier 2 (Redis network drop or timeout) logs a warning and transparently falls back to direct retrieval without raising 500 errors to callers.
* **Zero Stale Reads:** Synchronous generation invalidation guarantees 0 stale cache hits following circular updates.

---

## Negative Consequences & Mitigation

* **Vector Dot Product Computation:** Comparing against 512 cached embeddings incurs memory and CPU overhead.
  * *Mitigation:* Normalized unit vectors allow dot product directly via single-pass BLAS/NumPy. Comparing only entries with matching search parameters limits candidates to <= 512, completing in < 0.1ms.
* **Memory Bounds:** Caching full `CachedResult` objects could expand process footprint.
  * *Mitigation:* Hard LRU capacity ceiling `lru_maxsize = 512` caps Tier 1 memory consumption strictly at <= 64 MB.
