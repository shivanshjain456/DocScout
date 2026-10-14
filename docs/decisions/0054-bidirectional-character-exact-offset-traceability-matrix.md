# ADR-0054: Bidirectional Character-Exact Offset Traceability Matrix (FEAT-063)

## Status
Accepted

## Context
In regulatory intelligence and legal compliance workflows, every cited statement or evidence passage must be incontrovertibly grounded in the primary statutory source document. Under Spec FR-7, DocScout enforces character-exact span citations (`text[char_start:char_end] == passage.text`). However, when analysts inspect cited passages in UI viewers or audit consoles, text-only snippets require analysts to manually search and find the referenced paragraph within hundreds of scanned PDF pages.

Attempting to resolve visual highlights on the client side via loose string matching or browser DOM regex search introduces severe failure modes:
1. Positional drift: Scanned historical circulars with varying fonts, multi-column layouts, and watermarks cause browser text search to highlight wrong occurrences or fail completely.
2. Merged words and hyphenation: Standard PDF extractors collapse hyphenated line endings, breaking exact string matching against rendered canvas viewports.
3. Lack of immutable provenance: Without durable geometric bounding boxes stored with each chunk, audit evidence packages cannot reconstruct the visual context of a regulatory citation.

DocScout requires a deterministic, bidirectional character-exact offset traceability matrix that binds extracted chunk character offsets to PDF physical bounding boxes (72 DPI coordinates: `x0, y0, x1, y1`) and stores them durably for zero-drift UI highlighting.

## Decision
1. **Core Offset Traceability Matrix (`app/ingest/offset_matrix.py`)**:
   - `OffsetTraceabilityMatrix`: Layout geometry engine leveraging `pdfplumber` character streams (`page.chars`):
     - Maps each extracted character offset to its exact page index and geometric bounding box (`x0, top, x1, bottom`).
     - For any arbitrary character slice `[char_start:char_end]`, groups contiguous characters into line-level visual bounding boxes.
     - Merges adjacent intra-line character bounding boxes into clean, non-overlapping highlight rectangles.
     - Generates standard CSS highlight styles (`top`, `left`, `width`, `height` in percentage or PDF points).
     - Computes Intersection-over-Union (IoU) overlap against target token geometry to guarantee >= 0.95 visual fidelity.
   - `TraceabilityConfig`:
     - `strict_offset_verification: bool = True`
     - `dpi: int = 72`
     - `merge_adjacent_words: bool = True`
   - `ChunkCoordinates` dataclass:
     - `chunk_id: UUID`, `page_number: int`, `bbox: tuple[float, float, float, float]`, `char_start: int`, `char_end: int`.

2. **Strict Verification Invariants**:
   - Invariant 1 (Strict Offset Verification): If `strict_offset_verification` is True, character indices must strictly lie within document boundaries.
   - Invariant 2 (Coordinate Validity): All bounding box coordinates must be non-negative floats within page geometry (`0 <= x0 < x1 <= page_width`, `0 <= y0 < y1 <= page_height`).
   - Invariant 3 (Fallback Resilience): If character geometry extraction fails on a degraded page, logs warning and falls back to a page-level banner bounding box.

3. **Database Schema Evolution (`migrations/0047_chunk_coordinates.up.sql`)**:
   - Creates `chunk_coordinates` table:
     - `id BIGSERIAL PRIMARY KEY`
     - `chunk_id UUID REFERENCES chunks(chunk_id) ON DELETE CASCADE`
     - `page_number INTEGER NOT NULL DEFAULT 1`
     - `x0 DOUBLE PRECISION NOT NULL`
     - `y0 DOUBLE PRECISION NOT NULL`
     - `x1 DOUBLE PRECISION NOT NULL`
     - `y1 DOUBLE PRECISION NOT NULL`
     - `char_start INTEGER NOT NULL`
     - `char_end INTEGER NOT NULL`
     - `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
   - Indices on `chunk_id` and `page_number`.
   - Access grants for `docscout_app` and `docscout`.

4. **Public REST Endpoints and Observability**:
   - `POST /v1/ingest/coordinates`: Computes bounding boxes from base64 PDF and character span.
   - `GET /v1/ingest/coordinates/{chunk_id}`: Retrieves stored bounding boxes for a chunk.
   - Prometheus metrics:
     - Counter: `docscout_coordinate_mappings_created_total{status}`

## Consequences
- Cited passages in regulatory audit workflows link directly to exact yellow highlight boxes on original PDF circular scans with zero positional drift.
- Bounding box IoU overlap exceeds 0.95 across benchmark scanned circulars.
- Storage overhead per chunk remains under 2 KB.
