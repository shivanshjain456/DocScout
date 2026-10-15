# ADR-0067: Cross-Lingual Semantic Regulatory Search (FEAT-076)

* **Status:** Accepted
* **Date:** 2026-10-15
* **Deciders:** DocScout Core Engineering Team
* **Consulted:** Retrieval Architecture Guild, Multilingual NLP Engineering
* **Informed:** Core Platform Engineers, Product Operations

---

## Context and Problem Statement

Official Indian regulatory frameworks and gazettes published by the Reserve Bank of India (RBI), Securities and Exchange Board of India (SEBI), and the Ministry of Finance are issued bilingually in English and Hindi (Devanagari script). Compliance officers, legal analysts, and enterprise users frequently submit inquiries formulated in Devanagari Hindi (e.g., "भुगतान एग्रीगेटर के लिए पूंजी आवश्यकता", "गैर-बैंकिंग वित्तीय कंपनी पंजीकरण दिशानिर्देश", "केवाईसी सत्यापन और पैन लिंकिंग").

However, production vector indices in DocScout (`chunks.embedding vector(384)`) are indexed using English dense embeddings (`BAAI/bge-small-en-v1.5` per ADR-0002). In baseline evaluations, queries submitted in Devanagari Hindi achieved 0% cross-lingual retrieval (Recall@5 = 0.000) against English circular chunks because English BGE tokenizers lack Devanagari subword alignments, projecting Devanagari tokens into random noise or out-of-vocabulary buckets.

FEAT-076 implements Cross-Lingual Semantic Regulatory Search via a dedicated `MultilingualDenseStore` adapter conforming to the `VectorStore` Protocol in `app/retrieval/port.py`. It projects cross-lingual query embeddings into the shared 384-dimensional unit-norm vector space, enabling zero-shot retrieval of English regulatory circulars from Hindi inquiries and vice-versa without destructive automated translations that corrupt statutory terminology.

---

## Decision Drivers

1. **Cross-Lingual Retrieval Fidelity:** Cross-lingual Recall@5 >= 0.880 on a standardized benchmark of 25 paired bilingual regulatory queries against the gazette corpus.
2. **Zero English-to-English Regression:** Standard English queries must not regress (Delta <= 0.002 on Recall@5 and MRR).
3. **No Translation Distortion:** Avoid brittle machine translation pipelines that corrupt legal citations and statutory jargon.
4. **Clean Protocol Conformance:** Implement `VectorStore` Protocol (`search` and `fetch_metadata`) registered under `"multilingual_dense"` in `ADAPTER_REGISTRY`.
5. **Execution Latency Budget:** Multilingual query embedding and projection generation <= 18.0 ms on CPU.
6. **Resource Footprint Ceiling:** Memory consumption <= 250 MB for cross-lingual alignment weights and projections.
7. **Fail-Closed Fallback:** If cross-lingual projection encounters unexpected errors or missing weights, log a warning and fall back cleanly to standard English BGE embedding.
8. **Observability:** Track cross-lingual search operations with Prometheus counter `docscout_cross_lingual_queries_total{lang}` where `lang` is `"hi"` or `"en"`.
9. **Strict Typographical Compliance:** Zero UTF-8 em-dashes (`\xe2\x80\x94`).

---

## Considered Options

1. **Full Corpus Multi-Vector Re-indexing (Dual-Vector Ingestion):**
   * Re-index every document chunk with a 1024-dimensional multilingual model (e.g., `BAAI/bge-m3`).
   * *Drawbacks:* Violates ADR-0002. Chunks table schema pins `embedding vector(384)`. Doubling or tripling index dimensions triples memory requirements and breaks existing HNSW index performance.
2. **Machine Translation Pre-Filter (Google Translate / MarianMT):**
   * Translate Hindi queries into English via an external API or heavy MT model before running retrieval.
   * *Drawbacks:* High latency (200-500 ms per query), network dependency, and frequent corruption of specialized Indian statutory phrasing (e.g., translating legal provisos and acronyms incorrectly).
3. **Cross-Lingual Projection Adapter with Shared Alignment Space (Chosen):**
   * Implement `MultilingualDenseStore` in `app/retrieval/multilingual_dense.py`.
   * Detect Devanagari script via `app.ingest.devanagari` utilities (`has_devanagari`, `normalize_devanagari`).
   * Project Devanagari regulatory semantics into the canonical 384-dimensional unit-norm embedding space via aligned cross-lingual semantic representations.
   * Plug directly into `Retriever` via `RetrievalConfig.vector_store_adapter = "multilingual_dense"`.

---

## Decision Outcome

Adopt Option 3.

### Implementation Specifics

1. **Multilingual Embedding & Projection Engine (`app/retrieval/multilingual_dense.py`):**
   * `CrossLingualProjector`: Stateless alignment engine projecting Devanagari regulatory query semantics into the 384-dimensional unit-norm vector space.
   * `MultilingualDenseStore`: Concrete `VectorStore` adapter implementing:
     - `search(query_vector, k, filter=None, query_text=None)`: Detects language, executes cross-lingual projection when Devanagari script is present, delegates dense search to database or in-memory index, and records `docscout_cross_lingual_queries_total{lang}` metrics.
     - `fetch_metadata(chunk_ids, is_current=True)`: Hydrates chunk display and attribution metadata.
2. **Registry Integration (`app/retrieval/port.py`):**
   * Register `"multilingual_dense"` in `ADAPTER_REGISTRY`.
   * Support parameterization in `get_vector_store("multilingual_dense", conn=...)`.
3. **Retriever Pipeline Integration (`app/retrieval/search.py`):**
   * Provide `query_text=dense_query` to `store.search(...)`.
4. **Metrics (`app/api/metrics.py`):**
   * `CROSS_LINGUAL_QUERIES_TOTAL`: Prometheus Counter labeled with `lang` (`"hi"` or `"en"`).
5. **Testing & Verification (`tests/test_cross_lingual_retrieval.py`):**
   * Validate 25 paired bilingual regulatory queries (Hindi queries retrieving English Payment Aggregator, NBFC, KYC, Digital Lending, and Cyber Security circulars).
   * Verify Recall@5 >= 0.880, latency <= 18.0 ms, memory footprint <= 250 MB, and error fallback.
