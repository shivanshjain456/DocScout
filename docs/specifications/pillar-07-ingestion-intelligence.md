# Pillar 7 Specification: Ingestion, Extraction & Document Intelligence
*DocScout Enterprise Regulatory Intelligence Engine*

---

## FEAT-061: Hierarchical Structure-Aware Circular Chunking
- **Objective:** Replace naive 1,000-character sliding windows with semantic chunking that mirrors the anatomical hierarchy of regulatory circulars (Gazette Header, Preamble, Section, Subsection, Clause, Proviso, and Schedule).
- **In-scope behavior:** Parsing regulatory numbering patterns (e.g. `1.(a).(i)`, `Provided that...`); creating parent-child chunk links; preserving legal qualifications within the same semantic chunk envelope.
- **Excluded behavior:** Arbitrary chunking across unrelated regulatory sections.
- **Implementation boundaries:** `app/ingest/chunk.py`, `app/ingest/hierarchical_chunker.py`.
- **Integration points:** Replaces `chunk_document()` in `app/ingest/chunk.py`; populates `parent_chunk_id` in PostgreSQL.
- **Source-of-truth files:** `app/ingest/chunk.py`, `corpus/raw/*.PDF`.
- **Supported inputs:** Document extraction payload `Extraction(text, pages, extractor)`.
- **Input validation rules:** `text` non-empty string $\ge 100$ characters.
- **Output schema:** `list[HierarchicalChunk(chunk_id: UUID, parent_chunk_id: Optional[UUID], text: str, clause_hierarchy: list[str], char_start: int, char_end: int, is_proviso: bool)]`.
- **Configuration schema:** `ChunkingConfig(max_chunk_tokens: int = 512, min_chunk_tokens: int = 64, preserve_provisos: bool = True)`.
- **Default values:** `max_chunk_tokens = 512`, `min_chunk_tokens = 64`, `preserve_provisos = True`.
- **Dependencies:** Python regex, tiktoken / BGE tokenizer for token length enforcement.
- **Compatibility requirements:** Chunks must strictly respect `ck_chunks_token_ceiling` ($\le 512$ tokens) in database.
- **Authorization rules:** Internal ingestion pipeline execution.
- **Data isolation rules:** Chunk records bound to document version; respects `is_synthetic` isolation.
- **Error behavior:** Unstructured text that fails hierarchical regex falls back cleanly to whitespace-boundary window chunking.
- **Fallback behavior:** Legacy 1,000-char window chunking with 150-char overlap.
- **Observability requirements:** Counter `docscout_chunks_created_total{strategy}`, histogram `docscout_chunk_token_count`.
- **Performance limits:** Chunking speed $\ge 250\text{ pages/sec}$.
- **Resource limits:** Memory allocation $\le 16\text{ MB}$ per document.
- **Acceptance criteria:** 100% of provisos ("Provided that...") remain attached to their operative parent rule rather than being severed across window boundaries.
- **Evaluation dataset:** 20 benchmark regulatory circulars containing complex legal clauses and provisos ($n=170$ chunks).
- **Evaluation baseline:** Legacy fixed-window chunking where 28% of provisos were truncated from parent rules.
- **Required improvement threshold:** Proviso-parent retention rate $\ge 98\%$.
- **Regression limits:** Zero loss of character coverage invariant (100% text coverage verified via `uncovered_characters()`).
- **Completion criteria:** Passes `tests/test_hierarchical_chunking.py`.

---

## FEAT-062: High-Fidelity Table Lineage & Matrix Parser
- **Objective:** Extract complex financial disclosure tables, capital adequacy matrices, and fee schedules from regulatory PDFs into structured Markdown and JSON, preserving multi-row headers and lineage.
- **In-scope behavior:** Table boundary detection; extraction of merged headers; serializing table structure into JSONB `table_data_json` and readable Markdown representation; storing cell coordinate maps.
- **Excluded behavior:** OCR extraction on rotated unreadable handwritten annotations.
- **Implementation boundaries:** `app/ingest/table_parser.py`, `app/ingest/extract_chain.py`.
- **Integration points:** Stage 2 of ingestion pipeline; populates `chunks(table_data_json)`.
- **Source-of-truth files:** `app/ingest/table_parser.py`, `migrations/0012_hierarchical_chunking.up.sql`.
- **Supported inputs:** PDF document byte stream or PyPDF/pdfplumber document object.
- **Input validation rules:** Document must contain detectable table wireframes or tab-delimited alignment.
- **Output schema:** `ExtractedTable(table_id: str, page_number: int, headers: list[str], matrix: list[list[str]], markdown_repr: str, json_repr: dict)`.
- **Configuration schema:** `TableParserConfig(strategy: Literal["pdfplumber", "docling", "miner_u"], min_rows: int = 2)`.
- **Default values:** `strategy = "pdfplumber"`, `min_rows = 2`.
- **Dependencies:** `pdfplumber` / `pypdf`, Python standard library `json`.
- **Compatibility requirements:** Table Markdown representation must be directly indexable by BM25 and vector embedders.
- **Authorization rules:** Internal ingestion pipeline execution.
- **Data isolation rules:** Table data stored per document version; respects `is_synthetic` isolation.
- **Error behavior:** Table parsing error logs warning and extracts page text as plain unformatted text.
- **Fallback behavior:** Plain text fallback extraction.
- **Observability requirements:** Counter `docscout_tables_extracted_total`, histogram `docscout_table_extraction_duration_seconds`.
- **Performance limits:** Table extraction processing speed $\ge 30\text{ pages/sec}$.
- **Resource limits:** Memory footprint $\le 64\text{ MB}$ during PDF parsing.
- **Acceptance criteria:** Cell accuracy $\ge 98\%$ on complex RBI balance sheet disclosure matrices.
- **Evaluation dataset:** 15 regulatory circular annexures containing dense multi-column tables.
- **Evaluation baseline:** Legacy plain text extraction where table rows were scrambled into disjointed sentences.
- **Required improvement threshold:** Table cell extraction accuracy $\ge 98\%$.
- **Regression limits:** Zero crash on malformed or non-table PDF pages.
- **Completion criteria:** Verified in `tests/test_table_parser.py`.

---

## FEAT-063: Bidirectional Character-Exact Offset Traceability Matrix
- **Objective:** Maintain an immutable coordinate mapping between chunk text spans, extracted plain text, and exact bounding boxes on original PDF pages, guaranteeing zero positional drift in UI highlighting.
- **In-scope behavior:** Recording PDF page index, horizontal/vertical bounding box coordinates ($x_0, y_0, x_1, y_1$), and character offsets during extraction; storing in `chunk_coordinates` table.
- **Excluded behavior:** Approximating coordinates via loose string search on rendered client viewports.
- **Implementation boundaries:** `app/ingest/offset_matrix.py`, `app/api/models.py`.
- **Integration points:** Ingestion extraction phase; returned in `Passage.provenance` payload; consumed by React PDF viewer.
- **Source-of-truth files:** `app/ingest/offset_matrix.py`, `app/api/models.py`.
- **Supported inputs:** Document extraction tokens with layout geometry.
- **Input validation rules:** Coordinates must be non-negative floats within PDF page dimensions ($0 \le x \le \text{width}$, $0 \le y \le \text{height}$).
- **Output schema:** `ChunkCoordinates(chunk_id: UUID, page_number: int, bbox: tuple[float, float, float, float], char_start: int, char_end: int)`.
- **Configuration schema:** `TraceabilityConfig(strict_offset_verification: bool = True)`.
- **Default values:** `strict_offset_verification = True`.
- **Dependencies:** `pdfplumber` character layout engine, PostgreSQL storage.
- **Compatibility requirements:** Coordinate schema conforms to standard PDF points (72 DPI).
- **Authorization rules:** Public provenance metadata returned with search results.
- **Data isolation rules:** Bound to immutable document version SHA-256.
- **Error behavior:** If coordinate extraction fails for a span, log warning and set coordinates to page-level bounding box.
- **Fallback behavior:** Page-level highlighting fallback.
- **Observability requirements:** Counter `docscout_coordinate_mappings_created_total`.
- **Performance limits:** Coordinate extraction overhead $\le 10\%$ of extraction duration.
- **Resource limits:** Database storage overhead $\le 2\text{ KB}$ per chunk.
- **Acceptance criteria:** 100% of cited passages highlight the exact yellow bounding box on the original PDF scan in the UI console with zero positional shift.
- **Evaluation dataset:** 50 cited passages across 20 scanned PDF circulars.
- **Evaluation baseline:** Text-only search snippets without visual PDF coordinate grounding.
- **Required improvement threshold:** Bounding box Intersection-over-Union (IoU) overlap $\ge 0.95$ with target text.
- **Regression limits:** Invariant `verify_offsets()` must never fail.
- **Completion criteria:** Verified in `tests/test_offset_matrix.py` and Playwright visual diff tests.

---

## FEAT-064: OCR Degradation & Confidence Scoring Pipeline
- **Objective:** Evaluate character confidence scores per scanned PDF page; automatically route degraded pages ($<85\%$ confidence) to multi-pass image pre-processing (deskew, binarize, denoise) and OCR.Space fallback.
- **In-scope behavior:** Computing character-level confidence averages; flagging degraded historical scans; applying unsharp masking, deskewing, and contrast stretching; re-extracting text via OCR.Space fallback.
- **Excluded behavior:** Indiscriminate cloud OCR calls on clean vector PDF pages (wasting OCR quota).
- **Implementation boundaries:** `app/ingest/ocr_quality.py`, `app/ingest/ocr_space.py`, `app/ingest/extract_chain.py`.
- **Integration points:** Stage 1 of extraction chain; integrates with existing `app/ingest/ocr_space.py`.
- **Source-of-truth files:** `app/ingest/ocr_quality.py`, `app/ingest/ocr_space.py`.
- **Supported inputs:** PDF page raster image `PIL.Image` or byte buffer.
- **Input validation rules:** Image must be non-empty raster $\ge 150\text{ DPI}$.
- **Output schema:** `OCRQualityScore(page_number: int, confidence: float, is_degraded: bool, preprocessing_applied: list[str], extracted_text: str)`.
- **Configuration schema:** `OCRQualityConfig(degradation_threshold: float = 0.85, auto_preprocess: bool = True)`.
- **Default values:** `degradation_threshold = 0.85`, `auto_preprocess = True`.
- **Dependencies:** Pillow (`PIL`), OpenCV (`cv2`) for deskewing, `httpx` for OCR.Space client.
- **Compatibility requirements:** Honors existing 500 req/day and 1MB size bounds on OCR.Space integration.
- **Authorization rules:** Internal ingestion pipeline execution.
- **Data isolation rules:** Cached in `ocr_extractions` table keyed by image SHA-256.
- **Error behavior:** Preprocessing error logs warning and attempts OCR on un-preprocessed original image.
- **Fallback behavior:** Local `pypdf` extraction fallback if OCR.Space is unreachable or quota exhausted.
- **Observability requirements:** Gauge `docscout_ocr_mean_page_confidence`, counter `docscout_ocr_degraded_pages_routed_total`.
- **Performance limits:** Quality evaluation $\le 15\text{ ms}$ per page; image preprocessing $\le 45\text{ ms}$ per page.
- **Resource limits:** Memory footprint $\le 64\text{ MB}$ during image transformation.
- **Acceptance criteria:** Word Error Rate (WER) on degraded historical gazettes drops by $\ge 40\%$ following pre-processing and fallback routing.
- **Evaluation dataset:** 10 historical low-contrast RBI gazette scans (1995-2005).
- **Evaluation baseline:** Raw un-preprocessed OCR yielding garbled text on low-contrast scans.
- **Required improvement threshold:** OCR Word Error Rate (WER) reduction $\ge 40\%$.
- **Regression limits:** Clean digital PDFs must bypass preprocessing and cloud OCR 100% of the time (zero quota waste).
- **Completion criteria:** Verified in `tests/test_ocr_quality.py`.

---

## FEAT-065: Intelligent Regulatory Furniture & Gazette Stamp Stripper
- **Objective:** Intelligently strip repetitive gazette stamps, page numbers, publication watermarks, header banners, and printer signatures without altering character offsets of substantive statutory clauses.
- **In-scope behavior:** Regex and spatial layout detection of recurring headers/footers; replacing furniture characters with whitespace to preserve downstream character offset indices; eliminating noise tokens.
- **Excluded behavior:** Stripping substantive legal preambles or statutory circular notification reference numbers.
- **Implementation boundaries:** `app/ingest/clean.py`, `app/ingest/furniture_stripper.py`.
- **Integration points:** Stage 2 of clean pipeline in `app/ingest/clean.py`.
- **Source-of-truth files:** `app/ingest/clean.py`, `app/ingest/guards.py`.
- **Supported inputs:** Raw extracted text string `text: str`.
- **Input validation rules:** Length preserving: $\text{len}(\text{cleaned\_text}) == \text{len}(\text{raw\_text})$.
- **Output schema:** Cleaned text string with exact identical length and byte count.
- **Configuration schema:** `FurnitureConfig(strip_gazette_stamps: bool = True, strip_page_numbers: bool = True)`.
- **Default values:** `strip_gazette_stamps = True`, `strip_page_numbers = True`.
- **Dependencies:** Python regex with compiled gazette furniture patterns.
- **Compatibility requirements:** Enforces `clean.py` length-preserving invariant (`len(cleaned) == len(raw)`).
- **Authorization rules:** Internal ingestion pipeline execution.
- **Data isolation rules:** Applied consistently across all ingested documents.
- **Error behavior:** If pattern fails to match, text is left un-stripped; length invariant never violated.
- **Fallback behavior:** Unmodified text passed to next stage.
- **Observability requirements:** Counter `docscout_furniture_tokens_stripped_total`.
- **Performance limits:** Cleaning throughput $\ge 500\text{ pages/sec}$.
- **Resource limits:** Zero extra memory.
- **Acceptance criteria:** Eliminates 100% of recurring "THE GAZETTE OF INDIA : EXTRAORDINARY" stamps and page footers while maintaining byte-exact string lengths.
- **Evaluation dataset:** 20 official Indian Gazette regulatory notifications.
- **Evaluation baseline:** Legacy cleaner leaving repetitive header stamps that inflated BM25 term frequency.
- **Required improvement threshold:** 100% removal of target furniture patterns; 100% adherence to length preservation.
- **Regression limits:** Zero loss of substantive legal clauses or circular numbers.
- **Completion criteria:** Passes `tests/test_clean.py` and `guards.py` length invariant assertions.

---

## FEAT-066: Annexure, Schedule & FAQ Relational Association
- **Objective:** Automatically detect and preserve the relational hierarchy between main policy circular directives and their subsidiary technical annexures, schedules, and explanatory FAQs.
- **In-scope behavior:** Parsing structural headers ("Annexure I", "Schedule A", "Frequently Asked Questions"); establishing foreign-key parent-child links in database; enabling hierarchical cross-document retrieval.
- **Excluded behavior:** Merging massive 50-page technical annexures into single monolithic parent chunks.
- **Implementation boundaries:** `app/ingest/annexure_linker.py`, `migrations/0012_hierarchical_chunking.up.sql`.
- **Integration points:** Post-extraction phase in ingestion pipeline.
- **Source-of-truth files:** `app/ingest/annexure_linker.py`, `app/retrieval/search.py`.
- **Supported inputs:** Document extraction payload with detected section headings.
- **Input validation rules:** Non-empty section headings.
- **Output schema:** `list[SectionRelationship(parent_section_id: str, child_section_id: str, relationship_type: Literal["ANNEXURE", "SCHEDULE", "FAQ", "APPENDIX"])]`.
- **Configuration schema:** `AnnexureLinkerConfig(auto_link_faqs: bool = True)`.
- **Default values:** `auto_link_faqs = True`.
- **Dependencies:** Relational database table `document_sections`.
- **Compatibility requirements:** Fully backward compatible; documents without annexures function normally.
- **Authorization rules:** Internal ingestion pipeline execution.
- **Data isolation rules:** Relational links stored per document version.
- **Error behavior:** Linking failure logs warning and treats sections as independent sibling chunks.
- **Fallback behavior:** Chunks indexed as standard unlinked sections.
- **Observability requirements:** Counter `docscout_annexures_linked_total{type}`.
- **Performance limits:** Linking execution overhead $\le 1.0\text{ ms}$ per document.
- **Resource limits:** Zero extra memory.
- **Acceptance criteria:** When a user queries a directive in the main circular, relevant procedural rules in its Annexure are retrieved in the top-5 candidates.
- **Evaluation dataset:** 10 Master Directions with dense technical annexures.
- **Evaluation baseline:** Isolated retrieval missing procedural guidance hidden in annexures.
- **Required improvement threshold:** Cross-section retrieval recall on procedural queries $+18\text{ pp}$.
- **Regression limits:** Zero disruption to primary circular text ranking.
- **Completion criteria:** Verified in `tests/test_annexure_linker.py`.

---

## FEAT-067: Incremental Deterministic Chunk Hashing (UUIDv5)
- **Objective:** Generate content-derived chunk IDs using `uuid5(NAMESPACE, "sha256:char_start:char_end")`, enabling zero-churn incremental indexing, atomic updates, and permanent citation stability.
- **In-scope behavior:** Computing stable deterministic UUIDs from content SHA-256 and span coordinates; detecting unmodified chunks during circular re-ingestion; bypassing re-embedding for unchanged chunks.
- **Excluded behavior:** Random UUIDv4 generation that causes citation churn on re-indexing.
- **Implementation boundaries:** `app/ingest/ids.py`, `app/ingest/store.py`.
- **Integration points:** Core chunk ID generation in `app/ingest/chunk.py`; storage upsert in `app/ingest/store.py`.
- **Source-of-truth files:** `app/ingest/ids.py`, `app/ingest/store.py`.
- **Supported inputs:** Document payload hash `sha256: str`, character span `char_start: int`, `char_end: int`.
- **Input validation rules:** `sha256` valid 64-char hex string; $0 \le \text{char\_start} < \text{char\_end}$.
- **Output schema:** Stable `uuid.UUID` version 5.
- **Configuration schema:** Immutable namespace UUID `DOCSCOUT_CHUNK_NAMESPACE`.
- **Default values:** `DOCSCOUT_CHUNK_NAMESPACE = uuid.UUID("e7b6d1c0-4f8a-4b9e-9d2a-1c3b5a7e9f0d")`.
- **Dependencies:** Python standard library `uuid`, `hashlib`.
- **Compatibility requirements:** Byte-for-byte identical output across repeated runs on identical inputs.
- **Authorization rules:** Internal ingestion pipeline execution.
- **Data isolation rules:** Fully deterministic across all environments.
- **Error behavior:** Invalid span parameters raise `ValueError` and halt chunk creation.
- **Fallback behavior:** Fail-closed: invalid spans never receive generated IDs.
- **Observability requirements:** Counter `docscout_chunks_reused_total` (cache hits during incremental re-ingestion).
- **Performance limits:** ID generation speed $\ge 500,000\text{ IDs/sec}$.
- **Resource limits:** Zero memory overhead.
- **Acceptance criteria:** Re-running ingestion on an identical 100-page document results in 0 new database chunk inserts and 100% chunk reuse.
- **Evaluation dataset:** Corpus re-ingestion test across all 35 manifest documents.
- **Evaluation baseline:** Random UUIDv4 generation resulting in 100% database churn and orphaned citations.
- **Required improvement threshold:** 100% deterministic chunk ID reproducibility.
- **Regression limits:** Zero ID collisions across distinct text spans.
- **Completion criteria:** Invariance verified in `tests/test_chunk_ids.py`.

---

## FEAT-068: Bilingual Devanagari / Hindi Normalization & Parsing
- **Objective:** Full Unicode Devanagari normalization (NFC) and bilingual circular extraction for official Indian Gazette notifications published in parallel Hindi and English columns.
- **In-scope behavior:** Unicode NFC canonical decomposition/composition; stripping zero-width joiners/non-joiners where appropriate; bilingual column separation; dual-language text indexing.
- **Excluded behavior:** Machine translation that replaces original statutory Devanagari legal text.
- **Implementation boundaries:** `app/ingest/devanagari.py`, `app/ingest/clean.py`.
- **Integration points:** Stage 1 of clean pipeline in `app/ingest/clean.py`.
- **Source-of-truth files:** `app/ingest/devanagari.py`, `app/ingest/clean.py`.
- **Supported inputs:** Raw extracted text containing Unicode Devanagari characters (U+0900 to U+097F).
- **Input validation rules:** Valid UTF-8 encoding.
- **Output schema:** Normalized Unicode NFC text string.
- **Configuration schema:** `DevanagariConfig(normalize_nfc: bool = True, strip_zwj: bool = False)`.
- **Default values:** `normalize_nfc = True`, `strip_zwj = False`.
- **Dependencies:** Python standard library `unicodedata`.
- **Compatibility requirements:** Enforces `clean.py` length-preserving invariants.
- **Authorization rules:** Internal ingestion pipeline execution.
- **Data isolation rules:** Universal text normalization applied to all bilingual documents.
- **Error behavior:** Unicode decode error raises descriptive exception and logs character offset.
- **Fallback behavior:** Fail-closed: non-UTF-8 bytes rejected at ingestion boundary.
- **Observability requirements:** Counter `docscout_devanagari_characters_normalized_total`.
- **Performance limits:** Normalization throughput $\ge 1,000,000\text{ chars/sec}$.
- **Resource limits:** Zero extra memory.
- **Acceptance criteria:** Completely eliminates Devanagari character corruption (such as orphaned matras or broken conjuncts) in ingested gazettes.
- **Evaluation dataset:** 10 official bilingual Hindi/English RBI circular notifications.
- **Evaluation baseline:** Legacy cleaner containing regex rules that stripped valid Devanagari characters as noise.
- **Required improvement threshold:** 100% retention and clean retrieval of statutory Hindi text.
- **Regression limits:** Zero distortion of English characters or punctuation.
- **Completion criteria:** Unicode roundtrip tests pass in `tests/test_devanagari.py`.

---

## FEAT-069: Automated Regulatory Metadata & Notification ID Extraction
- **Objective:** Extract circular reference numbers (`RBI/2023-24/102`), department names (`Department of Regulation`), subject lines, and issuing officer signatures into structured columns.
- **In-scope behavior:** Regex and layout pattern extraction of gazette notification metadata; populating `documents(circular_no, issuing_department, subject, signoff_authority)` columns; enabling exact administrative filtering.
- **Excluded behavior:** Inventing missing notification numbers for informal press releases.
- **Implementation boundaries:** `app/ingest/metadata_extractor.py`, `app/ingest/extract_chain.py`.
- **Integration points:** Document ingestion stage immediately following text extraction.
- **Source-of-truth files:** `app/ingest/metadata_extractor.py`, `corpus/raw/manifest.json`.
- **Supported inputs:** Document text `text: str`, filename `filename: str`.
- **Input validation rules:** `text` length $\ge 100$ characters.
- **Output schema:** `DocumentMetadata(circular_no: Optional[str], department: Optional[str], subject: Optional[str], date_issued: Optional[date], signoff_officer: Optional[str])`.
- **Configuration schema:** `MetadataExtractorConfig(strict_pattern_matching: bool = True)`.
- **Default values:** `strict_pattern_matching = True`.
- **Dependencies:** Compiled regex patterns for RBI, SEBI, and Central Government gazette conventions.
- **Compatibility requirements:** Populates standard PostgreSQL metadata columns.
- **Authorization rules:** Internal ingestion pipeline execution.
- **Data isolation rules:** Bound to public document record.
- **Error behavior:** If pattern fails to match, fields set to `NULL` with diagnostic warning log.
- **Fallback behavior:** Document stored with available filename metadata.
- **Observability requirements:** Counter `docscout_metadata_fields_extracted_total{field_name}`.
- **Performance limits:** Extraction completed in $\le 1.5\text{ ms}$ per document.
- **Resource limits:** Zero extra memory.
- **Acceptance criteria:** Successfully extracts circular reference numbers and departments from $\ge 98\%$ of official RBI/SEBI publications.
- **Evaluation dataset:** All 35 circulars in `corpus/raw/manifest.json`.
- **Evaluation baseline:** Manual manifest entry curation without automated extraction.
- **Required improvement threshold:** Automated metadata extraction accuracy $\ge 98\%$.
- **Regression limits:** Zero false-positive circular ID assignments.
- **Completion criteria:** Verified in `tests/test_metadata_extractor.py`.

---

## FEAT-070: Duplicate & Reprint Deduplication Engine
- **Objective:** Detect circular reprints, identical notifications issued across multiple departments, and identical press releases using SHA-256 and MinHash LSH similarity.
- **In-scope behavior:** Computing full-text SHA-256 and MinHash signature; checking for existing identical documents in corpus; linking duplicates via `canonical_document_id` rather than re-chunking.
- **Excluded behavior:** Deduplicating distinct circular amendments that happen to share identical introductory boilerplates.
- **Implementation boundaries:** `app/ingest/deduplicator.py`, `app/ingest/store.py`.
- **Integration points:** Ingestion pre-storage check in `app/ingest/store.py`.
- **Source-of-truth files:** `app/ingest/deduplicator.py`, `app/ingest/store.py`.
- **Supported inputs:** Extracted document text `text: str`, document SHA-256 `sha256: str`.
- **Input validation rules:** `text` non-empty.
- **Output schema:** `DeduplicationResult(is_duplicate: bool, canonical_doc_id: Optional[str], similarity_score: float)`.
- **Configuration schema:** `DeduplicationConfig(min_similarity_threshold: float = 0.98)`.
- **Default values:** `min_similarity_threshold = 0.98`.
- **Dependencies:** Python `hashlib`, MinHash LSH or fast token Jaccard similarity.
- **Compatibility requirements:** Relational foreign key `documents(canonical_document_id)`.
- **Authorization rules:** Internal ingestion pipeline execution.
- **Data isolation rules:** Universal deduplication across public corpus.
- **Error behavior:** Deduplication check error defaults to `is_duplicate = False` and logs warning.
- **Fallback behavior:** Document processed as independent unique document.
- **Observability requirements:** Counter `docscout_duplicate_documents_detected_total`.
- **Performance limits:** Deduplication check latency $\le 2.0\text{ ms}$ per document.
- **Resource limits:** Memory footprint $\le 8\text{ MB}$.
- **Acceptance criteria:** Identifies 100% of exact reprints and $>95\%$ of near-identical gazette re-issues, preventing vector database bloat.
- **Evaluation dataset:** 10 pairs of duplicate and near-duplicate regulatory publications.
- **Evaluation baseline:** 0% automated deduplication (storing duplicate chunks and diluting search ranks).
- **Required improvement threshold:** Deduplication precision $\ge 99\%$, recall $\ge 95\%$.
- **Regression limits:** Zero false deduplication of distinct circular versions or amendments.
- **Completion criteria:** Verified in `tests/test_deduplicator.py`.
