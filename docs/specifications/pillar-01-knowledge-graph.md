# Pillar 1 Specification: Regulatory Knowledge Graph & Semantic Ontology
*DocScout Enterprise Regulatory Intelligence Engine*

---

## FEAT-001: Graph-Augmented Retrieval (GAR)
- **Objective:** Enable multi-hop traversal over statutory concept relationships (`requires`, `enables`, `supersedes`, `specializedBy`) during query processing to bridge vocabulary and circular-reference gaps where statutory definitions exist across separated circulars.
- **In-scope behavior:** Parse incoming search queries for recognized taxonomy terms; traverse graph up to depth $N \le 2$; retrieve candidate chunks linked to 1-hop and 2-hop neighbor nodes; merge graph-expanded candidates with dense/lexical candidate pools with edge-weighted scoring.
- **Excluded behavior:** Real-time extraction of unverified graph edges from arbitrary external websites; traversal of unindexed circulars; cyclic infinite graph walking.
- **Implementation boundaries:** Confined to `app/retrieval/graph_retriever.py` and `app/retrieval/search.py`. Graph read operations use in-memory network representation or cached PostgreSQL relational adjacency table `taxonomy_edges`.
- **Integration points:** Injected into `Retriever.retrieve()` in `app/retrieval/search.py` alongside `DenseRetriever` and `BM25Index`; coordinates with `reciprocal_rank_fusion` in `app/retrieval/fusion.py`.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`graph.edges`, `terms[].relationships`), `do not commit!/lexicon.json` (`graph.edges`), `app/retrieval/graph_retriever.py`.
- **Supported inputs:** Cleaned query string `query: str`, `max_hops: int` (1 or 2), `allowed_edge_types: list[str]` (`["requires", "enables", "supersedes", "specializedBy"]`).
- **Input validation rules:** `1 <= max_hops <= 2`; query length between 3 and 512 characters; `allowed_edge_types` subset of `{"requires", "enables", "supersedes", "complements", "specializedBy"}`.
- **Output schema:** `list[tuple[str, float]]` representing `(chunk_id, graph_proximity_score)` where score is normalized in `[0.0, 1.0]`.
- **Configuration schema:** `RetrievalConfig.enable_gar: bool = False`, `RetrievalConfig.gar_max_hops: int = 1`, `RetrievalConfig.gar_decay_factor: float = 0.5`.
- **Default values:** `enable_gar = False`, `gar_max_hops = 1`, `gar_decay_factor = 0.5`.
- **Dependencies:** `networkx` or direct adjacency dictionary, `psycopg` connection pool for chunk metadata hydration.
- **Compatibility requirements:** Python 3.12, PostgreSQL 18+ with pgvector, fully compatible with existing `RetrievalConfig` serializations.
- **Authorization rules:** Same as search: authenticated caller with valid API key or Auth0 bearer token with scope `search:read`.
- **Data isolation rules:** Strictly filters out `is_synthetic = True` nodes/chunks when servicing production requests per ADR-0024 and G-EVAL-1.
- **Error behavior:** If graph lookup fails or raises exception, log error with correlation ID and proceed without graph candidates.
- **Fallback behavior:** Transparently fall back to standard 2-arm hybrid RRF (`dense` + `lexical`) with zero user-facing degradation.
- **Observability requirements:** Emit Prometheus counter `docscout_gar_invocations_total`, histogram `docscout_gar_traversal_duration_seconds`, log structlog field `gar_nodes_expanded`.
- **Performance limits:** Graph neighbor lookup and scoring must execute in $\le 6.0\text{ ms}$ p95.
- **Resource limits:** Memory footprint $\le 32\text{ MB}$ for in-memory graph representation; max 64 expanded candidate chunk IDs.
- **Acceptance criteria:** For multi-hop circular reference queries (e.g. queries referencing Master Direction requirements specified in subsidiary circulars), Recall@5 increases by $\ge 4.5\text{ pp}$ without degrading latency past 50ms p95.
- **Evaluation dataset:** `evals/gold/v1/gold.jsonl` partitioned on multi-hop regulatory queries ($n=48$).
- **Evaluation baseline:** Current `hybrid-rrf` without graph expansion (Recall@5 = 0.966 overall, 0.812 on multi-hop slice).
- **Required improvement threshold:** Recall@5 on multi-hop slice $\ge 0.880$ ($+6.8\text{ pp}$).
- **Regression limits:** Overall Recall@5 regression $\le 0.001$; p95 latency increase $\le 8\text{ ms}$.
- **Completion criteria:** Clean unit tests in `tests/test_graph_retrieval.py`, gate pass in `make eval-gate`, strict mypy zero errors.

---

## FEAT-002: Regulatory Concept Hierarchy & Entity Linking
- **Objective:** Map financial and market entities into a formal taxonomy hierarchy (e.g. `Regulated Entity` -> `NBFC` -> `NBFC-ND-SI` -> `Core Investment Company`) to automatically expand queries and enforce entity-scoped filtering.
- **In-scope behavior:** Parsing entity mentions in user queries; resolving canonical entity IDs; matching hierarchical parent/child relations; decorating search requests with entity classification metadata.
- **Excluded behavior:** Automatic creation of new financial entity types without regulatory gazette source anchor.
- **Implementation boundaries:** `app/retrieval/entity_linker.py`, `app/retrieval/taxonomy_loader.py`.
- **Integration points:** Pre-search query normalization pipeline in `app/api/app.py` and `app/retrieval/search.py`.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`domains["preserved-original"]`, `terms`), `do not commit!/lexicon.json` (`indices.byDomain`).
- **Supported inputs:** Raw user query string `query: str`, target entity scope `entity_scope: Optional[str]`.
- **Input validation rules:** String sanitized, ASCII/Unicode printable, length $\le 512$ characters.
- **Output schema:** `EntityLinkResult(entity_id: str, canonical_name: str, parent_ids: list[str], child_ids: list[str], confidence: float)`.
- **Configuration schema:** `EntityLinkingConfig(enabled: bool = True, min_confidence: float = 0.85, expand_children: bool = True)`.
- **Default values:** `enabled = True`, `min_confidence = 0.85`, `expand_children = True`.
- **Dependencies:** Regex token matcher, Trie data structure for statutory entity names.
- **Compatibility requirements:** Thread-safe execution; compatible with FastAPI middleware execution lifecycle.
- **Authorization rules:** Publicly callable within standard authenticated search endpoints.
- **Data isolation rules:** Entities defined in taxonomy are public regulatory classifications; zero tenant data leakage.
- **Error behavior:** If entity linking encounters unparseable syntax, logs warning and returns `None` (empty linking).
- **Fallback behavior:** Query executes as raw unlinked string through default dense/BM25 pipelines.
- **Observability requirements:** Log `linked_entities` in structlog access logs; counter `docscout_entities_linked_total{entity_type}`.
- **Performance limits:** Entity recognition and linking latency $\le 1.5\text{ ms}$ p95.
- **Resource limits:** Memory footprint $\le 5\text{ MB}$ for entity Trie.
- **Acceptance criteria:** Correctly links 100% of the 35 statutory entity categories defined across RBI and SEBI circulars.
- **Evaluation dataset:** Synthetic regulatory entity mention test set ($n=120$ queries with complex abbreviations and synonyms).
- **Evaluation baseline:** Legacy keyword search with 0% structured entity hierarchy recognition.
- **Required improvement threshold:** Entity recognition F1-score $\ge 0.96$.
- **Regression limits:** Zero false-positive entity tagging on general compliance queries.
- **Completion criteria:** Passes `tests/test_entity_linker.py`; documentation committed under `docs/architecture/entity-hierarchy.md`.

---

## FEAT-003: Edge-Weighted RRF Hybrid Fusion
- **Objective:** Extend Reciprocal Rank Fusion (RRF) to incorporate a 3rd rank arm derived from Knowledge Graph proximity, weighted dynamically by relation classification (`curated` vs `shares-standard` vs `similarity`).
- **In-scope behavior:** Tri-arm fusion across Dense (kNN), Lexical (BM25), and Graph (KG) candidate lists; applying edge-specific weighting coefficients; deterministic tiebreaking on UUID chunk IDs.
- **Excluded behavior:** Arbitrary non-deterministic rank shuffling; unbounded candidate arm sizes.
- **Implementation boundaries:** `app/retrieval/fusion.py`, `app/retrieval/types.py`.
- **Integration points:** Replaces `reciprocal_rank_fusion()` in `app/retrieval/search.py`.
- **Source-of-truth files:** `app/retrieval/fusion.py`, `do not commit!/term-taxonomy.json` (`graph.edgeKinds`).
- **Supported inputs:** `arms: dict[str, list[tuple[str, float]]]`, `weights: dict[str, float]`, `rrf_k: int = 60`.
- **Input validation rules:** `weights` must sum to $> 0.0$; `rrf_k >= 1`; all chunk IDs must be valid UUID strings.
- **Output schema:** `list[tuple[str, float]]` containing deduplicated chunk IDs and unified fusion scores in descending order.
- **Configuration schema:** `RetrievalConfig.fusion_mode: str = "rrf_tri_arm"`, `RetrievalConfig.kg_weight: float = 0.3`.
- **Default values:** `fusion_mode = "hybrid-rrf"`, `kg_weight = 0.3`, `rrf_k = 60`.
- **Dependencies:** Pure Python standard library (no C-extensions required).
- **Compatibility requirements:** Must preserve exact mathematical equivalence to 2-arm RRF when `kg_weight == 0.0`.
- **Authorization rules:** Internal retrieval engine component; inherits caller request authorization.
- **Data isolation rules:** Arm results filtered for `is_synthetic` prior to fusion invocation.
- **Error behavior:** If an arm yields invalid candidate tuples, discard invalid arm and fuse remaining valid arms with warning.
- **Fallback behavior:** Fall back to 2-arm RRF (`dense` + `lexical`) if KG arm is empty.
- **Observability requirements:** Record fusion candidate overlaps in structlog; gauge metric `docscout_fusion_candidates_count`.
- **Performance limits:** Tri-arm fusion of three 50-item candidate lists completed in $\le 0.4\text{ ms}$.
- **Resource limits:** $O(N)$ memory where $N$ is total unique candidates ($\le 150$).
- **Acceptance criteria:** Preserves ADR-0007 top-1 guarantee while improving MRR by $\ge 0.025$ on graph-dependent queries.
- **Evaluation dataset:** `evals/gold/v1/gold.jsonl` (365 scored items).
- **Evaluation baseline:** Current baseline `MRR = 0.854`.
- **Required improvement threshold:** Overall MRR $\ge 0.875$.
- **Regression limits:** Recall@10 must not regress below 0.990.
- **Completion criteria:** Mathematical invariance verified in `tests/test_fusion_tri_arm.py`.

---

## FEAT-004: Interactive Concept Subgraph Projection
- **Objective:** Extract and project a 2-hop ego-network around retrieved circular passages to render an interactive SVG/Canvas node-link visualization in the React console.
- **In-scope behavior:** Querying PostgreSQL adjacency table for nodes associated with top-5 retrieved passages; computing 2-hop ego subgraph; returning node/edge graph JSON; rendering interactive graph in UI.
- **Excluded behavior:** Full-corpus graph visualization; client-side force-directed layout computation that freezes the browser.
- **Implementation boundaries:** `app/api/app.py` (`GET /v1/graph/subgraph/{doc_id}`), `ui/src/components/ConceptGraphView.tsx`.
- **Integration points:** React search result card "Inspect Concept Graph" button; OpenAPI specification.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`graph`), `ui/src/components/ConceptGraphView.tsx`.
- **Supported inputs:** Path parameter `doc_id: str`, query parameter `depth: int = 2`, `max_nodes: int = 30`.
- **Input validation rules:** `doc_id` matches regex `^doc-[a-z0-9\-]+$`; $1 \le \text{depth} \le 2$; $5 \le \text{max\_nodes} \le 50$.
- **Output schema:** `SubgraphResponse(nodes: list[GraphNode], edges: list[GraphEdge], root_id: str)` where `GraphNode` has `(id, label, domain, level)` and `GraphEdge` has `(source, target, relation)`.
- **Configuration schema:** `GraphUIConfig(max_display_nodes: int = 30, enable_physics: bool = True)`.
- **Default values:** `depth = 2`, `max_nodes = 25`.
- **Dependencies:** React, D3.js or Cytoscape.js for rendering, PostgreSQL for adjacency lookup.
- **Compatibility requirements:** Modern browsers (Chrome, Firefox, Safari, Edge); responsive UI viewport down to 1024px.
- **Authorization rules:** Requires valid API key or authenticated user token with `search:read`.
- **Data isolation rules:** Graph nodes derived strictly from public regulatory taxonomy; no tenant data displayed.
- **Error behavior:** If node not found, return HTTP 404 with standard RFC-7807 problem details.
- **Fallback behavior:** UI renders informational alert "No concept relationships mapped for this document" without breaking UI.
- **Observability requirements:** Route `/v1/graph/subgraph/{doc_id}` instrumented in RED metrics; duration tracked in Prometheus.
- **Performance limits:** API endpoint latency $\le 15\text{ ms}$ p95; UI layout render $\le 60\text{ fps}$.
- **Resource limits:** API response payload $\le 64\text{ KB}$.
- **Acceptance criteria:** UI renders interactive graph within 200ms of user click, allowing node click to filter search.
- **Evaluation dataset:** Manual UX validation suite covering 20 core RBI circulars.
- **Evaluation baseline:** Zero visual graph capability in legacy UI console.
- **Required improvement threshold:** 100% successful rendering with zero console JavaScript errors.
- **Regression limits:** Zero layout shifts on main search results container.
- **Completion criteria:** Playwright E2E test `tests_e2e/test_concept_graph.spec.ts` green in CI.

---

## FEAT-005: Circular Citation Graph Extractor
- **Objective:** Extract and formalize cross-document statutory references (e.g., "in terms of Circular DBOD.No.BP.BC...") during ingestion to construct an explicit circular lineage graph.
- **In-scope behavior:** Regex and pattern-based identification of circular identifiers during document extraction; resolving cited circulars against internal corpus manifest; storing directed citation edges.
- **Excluded behavior:** Guessing citations from vague colloquial references without formal circular numbers.
- **Implementation boundaries:** `app/ingest/citation_extractor.py`, `app/ingest/extract_chain.py`.
- **Integration points:** Stage 2 of document ingestion pipeline; populates `circular_citations` PostgreSQL table.
- **Source-of-truth files:** `app/ingest/extract_chain.py`, `corpus/raw/manifest.json`.
- **Supported inputs:** Extracted document text `text: str`, document metadata `doc_id: str`.
- **Input validation rules:** `text` must be non-empty string $\ge 100$ characters.
- **Output schema:** `list[CitationEdge(source_doc_id: str, target_circular_no: str, target_doc_id: Optional[str], raw_citation_span: str)]`.
- **Configuration schema:** `CitationExtractorConfig(enabled: bool = True, resolve_unmanifested: bool = True)`.
- **Default values:** `enabled = True`, `resolve_unmanifested = True`.
- **Dependencies:** Python `re` module with compiled statutory pattern catalog.
- **Compatibility requirements:** Backward-compatible with all legacy ingested documents via idempotent migration script.
- **Authorization rules:** Internal ingestion pipeline execution; requires DB write privileges.
- **Data isolation rules:** Citation edges stored per document version; synthetic fixtures marked `is_synthetic = True`.
- **Error behavior:** Extraction error on a single clause logs warning and continues processing document.
- **Fallback behavior:** Documents with zero citations proceed through normal chunking without citation edges.
- **Observability requirements:** Prometheus counter `docscout_citations_extracted_total`, gauge `docscout_unresolved_citations_total`.
- **Performance limits:** Citation extraction processing speed $\ge 250\text{ pages/sec}$.
- **Resource limits:** Peak memory $\le 10\text{ MB}$ during regex execution.
- **Acceptance criteria:** Correctly extracts $\ge 95\%$ of statutory circular citations across the 20 benchmark RBI/SEBI circulars.
- **Evaluation dataset:** 20 benchmark regulatory documents with hand-annotated citation ground truth ($n=84$ citations).
- **Evaluation baseline:** 0% automated citation graph extraction in current baseline.
- **Required improvement threshold:** Citation extraction precision $\ge 98\%$, recall $\ge 92\%$.
- **Regression limits:** Zero slowdown to overall ingestion pipeline ($\le 2\%$ delta).
- **Completion criteria:** Automated migration extracts citations across entire corpus with verified DB foreign keys.

---

## FEAT-006: Taxonomy Layer-Partitioned Search Indexes
- **Objective:** Partition lexical and dense search indexes across the 9 taxonomy layers (`quality-and-verification`, `foundations`, `systems`, etc.) to enable isolated domain searches and 40% lower search latency.
- **In-scope behavior:** Tagging chunks with taxonomy layer at ingestion; applying partition pruning during SQL vector search; routing queries with explicit layer constraints.
- **Excluded behavior:** Hard physical table partitioning that breaks cross-layer joins.
- **Implementation boundaries:** `migrations/0011_layer_partitioning.up.sql`, `app/retrieval/dense.py`, `app/retrieval/lexical.py`.
- **Integration points:** `MetadataFilter.taxonomy_layer` in `app/retrieval/types.py`.
- **Source-of-truth files:** `do not commit!/lexicon.json` (`indices.byLayer`), `app/retrieval/types.py`.
- **Supported inputs:** `filter: MetadataFilter(taxonomy_layers: list[str])`.
- **Input validation rules:** `taxonomy_layers` must be subset of the 9 valid enum values in `lexicon.meta.conventions`.
- **Output schema:** Standard `list[tuple[str, float]]` filtered exclusively within requested layers.
- **Configuration schema:** `RetrievalConfig.enforce_layer_pruning: bool = True`.
- **Default values:** `enforce_layer_pruning = True`.
- **Dependencies:** PostgreSQL partial indexes on `chunks(taxonomy_layer)` where `is_current = True`.
- **Compatibility requirements:** Fully backward compatible; queries omitting layer filter search entire index.
- **Authorization rules:** Inherits search endpoint authorization.
- **Data isolation rules:** Strictly enforces `WHERE NOT d.is_synthetic` on all layer-pruned query branches.
- **Error behavior:** Invalid layer name returns HTTP 422 with list of valid layers.
- **Fallback behavior:** If partition index scan fails, PostgreSQL query planner falls back to main HNSW index scan.
- **Observability requirements:** Log layer filter in structlog; measure query duration partitioned by layer.
- **Performance limits:** Partitioned vector search p95 latency $\le 12.0\text{ ms}$ (vs 24ms unpartitioned).
- **Resource limits:** Max index storage overhead $\le 15\%$ of base vector index.
- **Acceptance criteria:** Layer-constrained queries execute with 100% layer purity and $\ge 35\%$ lower execution time.
- **Evaluation dataset:** 100 layer-specific evaluation queries across all 9 layers.
- **Evaluation baseline:** Full-table scans with post-retrieval Python filtering.
- **Required improvement threshold:** Query latency reduction $\ge 35\%$; 100% filter precision.
- **Regression limits:** Zero recall degradation for queries specifying correct layer.
- **Completion criteria:** Migration applied cleanly in native and docker environments; index verification tests pass.

---

## FEAT-007: Dynamic Definition Tooltips in Console UI
- **Objective:** Render dynamic popover cards displaying canonical definitions, aliases, and source anchors for any recognized taxonomy term present in search snippets or document views.
- **In-scope behavior:** Fast client-side entity detection in rendered text; popover overlay displaying canonical definition; linking to related terms.
- **Excluded behavior:** Modifying underlying document text; obstructive tooltips that block scrolling or text selection.
- **Implementation boundaries:** `ui/src/components/TermAnnotator.tsx`, `ui/src/hooks/useTaxonomyDictionary.ts`.
- **Integration points:** Search results passage viewer and document detail reader in React console.
- **Source-of-truth files:** `do not commit!/lexicon.json` (`terms`, `definitions`), `ui/src/components/TermAnnotator.tsx`.
- **Supported inputs:** Rendered passage text `content: string`.
- **Input validation rules:** Plain string input, HTML sanitization applied before DOM injection.
- **Output schema:** DOM node tree with `<span class="taxonomy-term" data-term-id="...">` wrappers.
- **Configuration schema:** `UIPreferences(highlight_taxonomy_terms: bool = True, tooltip_delay_ms: int = 250)`.
- **Default values:** `highlight_taxonomy_terms = True`, `tooltip_delay_ms = 250`.
- **Dependencies:** React, Radix UI Popover / Floating UI.
- **Compatibility requirements:** Accessible via keyboard focus (WCAG 2.2 AA compliant); touch-friendly on mobile devices.
- **Authorization rules:** Client-side UI feature; public taxonomy data.
- **Data isolation rules:** Completely isolated from user session data; static dictionary loaded once.
- **Error behavior:** If dictionary fails to fetch, render unannotated raw text without UI breakage.
- **Fallback behavior:** Graceful degradation to standard unannotated text.
- **Observability requirements:** Track client-side tooltip hover analytics via opt-in telemetry.
- **Performance limits:** Client-side token scanning and DOM annotation $\le 5\text{ ms}$ for a 1,000-character chunk.
- **Resource limits:** Dictionary bundle size $\le 180\text{ KB}$ gzipped.
- **Acceptance criteria:** Tooltips appear accurately over recognized terms with zero layout shift (CLS = 0.00).
- **Evaluation dataset:** React component unit tests with 50 diverse regulatory snippet samples.
- **Evaluation baseline:** Raw unannotated text display in legacy UI console.
- **Required improvement threshold:** 100% term detection accuracy on exact taxonomy terms.
- **Regression limits:** Zero UI rendering stutter or frame drops during fast scrolling.
- **Completion criteria:** Visual regression tests pass via Playwright.

---

## FEAT-008: Relationship-Filtered Search API
- **Objective:** Extend `POST /v1/search` to accept a `relationship_filter` parameter (e.g., `supersedes`, `requires`), constraining retrieval to passages establishing or modifying that relation.
- **In-scope behavior:** Joining candidate chunks against `taxonomy_edges` and `circular_citations` tables on specified relationship type; ranking compliant chunks.
- **Excluded behavior:** Arbitrary untyped relationship strings not present in taxonomy schema.
- **Implementation boundaries:** `app/api/models.py`, `app/retrieval/search.py`, `app/retrieval/types.py`.
- **Integration points:** `SearchRequest` schema in `app/api/models.py`; `POST /v1/search` endpoint.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`graph.edgeKinds`), `app/api/models.py`.
- **Supported inputs:** `relationship_filter: Optional[Literal["supersedes", "requires", "enables", "complements", "specializedBy"]]`.
- **Input validation rules:** Value must match allowed literal enum or be `None`.
- **Output schema:** Standard `SearchResponse` decorated with `matching_relationships: list[str]` on each returned passage.
- **Configuration schema:** Fully exposed via `SearchRequest` payload.
- **Default values:** `relationship_filter = None`.
- **Dependencies:** PostgreSQL index on `taxonomy_edges(relation_type)`.
- **Compatibility requirements:** Fully backward compatible; existing API requests without the parameter function identically.
- **Authorization rules:** Requires valid API key or bearer token with `search:read` scope.
- **Data isolation rules:** Relationship filtering respects tenant boundaries and `is_synthetic` exclusion.
- **Error behavior:** Invalid relationship string returns HTTP 422 with descriptive validation error.
- **Fallback behavior:** If relationship join yields zero matches, return empty result list with confidence 0.0 rather than unfiltered results.
- **Observability requirements:** Log `relationship_filter` in structlog; Prometheus counter `docscout_relationship_queries_total{relation}`.
- **Performance limits:** Query execution latency $\le 30\text{ ms}$ p95.
- **Resource limits:** DB join buffer $\le 16\text{ MB}$.
- **Acceptance criteria:** Correctly filters and returns only passages with verified relationship links.
- **Evaluation dataset:** 30 relationship-focused test queries (e.g. "What circulars does Master Direction 2023 supersede?").
- **Evaluation baseline:** General search without relationship constraints yielding mixed irrelevant provisions.
- **Required improvement threshold:** Relationship precision = 1.000 (zero false positive relationships).
- **Regression limits:** Zero latency impact on unconstrained standard searches.
- **Completion criteria:** API contract tests pass in `tests/test_api_search.py`.

---

## FEAT-009: Graph Degree Centrality Query Boosting
- **Objective:** Factor precomputed PageRank and degree centrality scores from the knowledge graph into passage scoring to surface foundational master directions on broad thematic queries.
- **In-scope behavior:** Precomputing node degree centrality on taxonomy graph; mapping centrality scores to document chunks; applying non-linear boost during hybrid fusion.
- **Excluded behavior:** Dynamic PageRank recalculation on the query request path.
- **Implementation boundaries:** `app/retrieval/centrality.py`, `app/retrieval/search.py`.
- **Integration points:** Scoring phase in `Retriever.retrieve()` before final top-k selection.
- **Source-of-truth files:** `do not commit!/lexicon.json` (`graph.nodes[].degree`), `app/retrieval/centrality.py`.
- **Supported inputs:** Broad thematic query (e.g. "KYC norms", "Outsourcing framework"), `enable_centrality_boost: bool`.
- **Input validation rules:** Centrality weight clamped in $[0.0, 0.3]$.
- **Output schema:** Rescored candidate ranking with `centrality_boost` component recorded in score breakdown.
- **Configuration schema:** `RetrievalConfig.centrality_weight: float = 0.15`, `RetrievalConfig.broad_query_threshold: float = 0.4`.
- **Default values:** `centrality_weight = 0.15`, `broad_query_threshold = 0.4`.
- **Dependencies:** Precomputed centrality lookup table in PostgreSQL or memory cache.
- **Compatibility requirements:** Mathematical stability; score monotonic invariance.
- **Authorization rules:** Standard search authorization.
- **Data isolation rules:** Centrality calculated strictly on public circular corpus.
- **Error behavior:** If centrality lookup fails, apply zero boost ($1.0\times$) and proceed normally.
- **Fallback behavior:** Standard RRF scoring without centrality adjustment.
- **Observability requirements:** Log `mean_centrality_boost` in search execution metadata.
- **Performance limits:** In-memory lookup overhead $\le 0.2\text{ ms}$.
- **Resource limits:** Lookup cache $\le 2\text{ MB}$.
- **Acceptance criteria:** On broad thematic queries, foundational Master Directions rank in top-3 $\ge 90\%$ of the time.
- **Evaluation dataset:** 40 broad thematic regulatory questions from gold benchmark.
- **Evaluation baseline:** Baseline nDCG@5 = 0.810 on broad query slice.
- **Required improvement threshold:** nDCG@5 on broad queries $\ge 0.885$ ($+7.5\text{ pp}$).
- **Regression limits:** Narrow specific queries (exact section numbers) must not have rank order perturbed.
- **Completion criteria:** Evaluation runner confirms nDCG gain in `evals/reports/`.

---

## FEAT-010: Automated Regulatory Ontology Ingestion Pipeline
- **Objective:** Automated worker pipeline that parses newly discovered circulars, extracts recurring statutory terms, and stages proposed ontology additions for human review.
- **In-scope behavior:** Text mining of "Definitions" section in master directions; entity boundary extraction; generating candidate taxonomy JSON records; staging in review queue.
- **Excluded behavior:** Unsupervised direct mutation of production `term-taxonomy.json` without review.
- **Implementation boundaries:** `app/ingest/ontology_extractor.py`, `app/api/admin_ontology.py`.
- **Integration points:** Post-ingestion hook in `app/ingest/discovery.py`; Admin API `/v1/admin/ontology/candidates`.
- **Source-of-truth files:** `do not commit!/term-taxonomy.schema.json`, `app/ingest/ontology_extractor.py`.
- **Supported inputs:** Ingested document payload `DocumentPayload(doc_id, text, metadata)`.
- **Input validation rules:** Document must be classified as Master Direction or Comprehensive Circular.
- **Output schema:** `CandidateTerm(term: str, definition: str, domain: str, source_doc_id: str, proposed_edges: list[dict])`.
- **Configuration schema:** `OntologyIngestConfig(auto_extract: bool = True, min_frequency: int = 3)`.
- **Default values:** `auto_extract = True`, `min_frequency = 3`.
- **Dependencies:** Python regex, spaCy / fast token pattern matcher.
- **Compatibility requirements:** Emitted JSON must validate 100% against `term-taxonomy.schema.json`.
- **Authorization rules:** Admin-only endpoint requiring `admin:write` Auth0 scope or admin API key.
- **Data isolation rules:** Staged terms partitioned in `ontology_staging` table with reviewer audit trail.
- **Error behavior:** Parse error logs detailed failure stack trace and flags document for manual inspection.
- **Fallback behavior:** Document continues regular chunking and vector indexing even if ontology extraction fails.
- **Observability requirements:** Counter `docscout_ontology_candidates_discovered_total`, admin alert on new candidates.
- **Performance limits:** Extraction completed in $\le 5.0\text{ seconds}$ per 50-page document.
- **Resource limits:** Memory allocation $\le 128\text{ MB}$ during extraction execution.
- **Acceptance criteria:** Automatically extracts $\ge 90\%$ of explicitly defined terms from Chapter 1 of RBI Master Directions.
- **Evaluation dataset:** 5 recent Master Directions with known definition glossaries ($n=65$ defined terms).
- **Evaluation baseline:** 0% automated ontology mining (manual curation only).
- **Required improvement threshold:** Candidate extraction recall $\ge 90\%$, precision $\ge 85\%$.
- **Regression limits:** Zero disruption to primary document ingestion throughput.
- **Completion criteria:** Staging endpoints and approval workflows verified in `tests/test_admin_ontology.py`.
