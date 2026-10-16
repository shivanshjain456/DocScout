# ADR-0055: OCR Degradation & Confidence Scoring Pipeline (FEAT-064)

## Status
Accepted

## Context
DocScout ingests historical statutory notifications, circulars, and official gazettes dating from 1995 through the present day. Modern circulars are clean, digitally typeset vector PDFs with crisp character geometry. However, legacy circulars (e.g., early RBI notifications and SEBI orders from 1995-2005) exist only as photocopied or low-resolution raster scans with significant skew, salt-and-pepper noise, uneven illumination, and degraded character glyphs.

Processing all ingested pages through external cloud OCR (OCR.Space) causes severe operational problems:
1. Cloud quota exhaustion: The operational free tier provides 500 requests per day and a 1 MB file ceiling. Indiscriminately submitting clean digital vector PDFs rapidly exhausts quota, causing subsequent degraded scans to fail.
2. Inefficient latency: Cloud round-trips add hundreds of milliseconds per page to ingestion pipelines that otherwise complete in sub-10ms.
3. Garbled extraction on degraded scans: Directly OCRing low-contrast, skewed gazettes without image enhancement produces unacceptable Word Error Rates (WER), resulting in hallucinated or lost statutory clauses.

DocScout requires an intelligent, multi-tier degradation and confidence scoring pipeline that evaluates character-level confidence scores per scanned PDF page, automatically routes degraded pages (confidence < 85%) to multi-pass image pre-processing (contrast stretching, unsharp masking, deskewing, denoising) and fallback OCR, while allowing clean vector PDFs to bypass preprocessing and external OCR 100% of the time.

## Decision
1. **Quality Assessment and Confidence Scoring Engine (`app/ingest/ocr_quality.py`)**:
   - `OCRQualityEvaluator`:
     - Inspects PDF page text streams or raster images to compute character-level confidence averages.
     - For vector PDF pages with native font streams, computes dictionary validity, printable ASCII/Unicode distribution, and font encoding health. Clean digital pages score >= 0.95 confidence.
     - For raster images or low-confidence pages, evaluates image sharpness, contrast ratio, background binarization clarity, and character recognition certainty.
     - Pages scoring below `degradation_threshold` (default 0.85) are flagged as `is_degraded = True`.
   - `ImagePreprocessor`:
     - Multi-pass enhancement pipeline leveraging Pillow and NumPy:
       - Pass 1: Contrast stretching / autocontrast (`autocontrast`) to expand dynamic range.
       - Pass 2: Unsharp masking (`unsharp_mask`) to sharpen blurred statutory character glyphs.
       - Pass 3: Projection-profile deskewing (`deskew`) to correct scan rotation angles (-5 to +5 degrees).
       - Pass 4: Median filtering (`denoise`) to remove salt-and-pepper scanner noise.
     - Bounded memory footprint (<= 64 MB) and fast execution (<= 45 ms per page).
   - `OCRQualityConfig`:
     - `degradation_threshold: float = 0.85`
     - `auto_preprocess: bool = True`
   - `OCRQualityScore`:
     - `page_number: int`, `confidence: float`, `is_degraded: bool`, `preprocessing_applied: list[str]`, `extracted_text: str`.

2. **Integration with OCR.Space and Local Ingestion (`app/ingest/ocr_space.py`, `app/ingest/extract_chain.py`)**:
   - Clean digital PDFs bypass cloud OCR and preprocessing completely (zero quota waste).
   - Degraded pages are pre-processed and submitted to `OCR.Space` or fallback extractor.
   - Results are cached durably in PostgreSQL `ocr_extractions` table keyed by image SHA-256.

3. **Database Schema Evolution (`migrations/0048_ocr_quality.up.sql`)**:
   - Updates `ocr_extractions` table with:
     - `confidence DOUBLE PRECISION NULL`
     - `is_degraded BOOLEAN DEFAULT FALSE`
     - `preprocessing_applied JSONB NOT NULL DEFAULT '[]'::jsonb`
   - Creates index on `(is_degraded, confidence)`.
   - Explicit permissions granted to `docscout_app` and `docscout`.

4. **Public REST Endpoints and Observability**:
   - `POST /v1/ingest/ocr/assess`: Evaluates raster or PDF page confidence, optionally applies preprocessing, and returns `OCRQualityScore`.
   - `GET /v1/ingest/ocr/{image_sha256}`: Fetches cached OCR quality result by image SHA-256 hash.
   - Prometheus metrics:
     - Gauge: `docscout_ocr_mean_page_confidence`
     - Counter: `docscout_ocr_degraded_pages_routed_total{status}`

## Consequences
- Clean digital PDFs bypass cloud OCR 100% of the time, preserving cloud quota for truly degraded historical scans.
- Word Error Rate (WER) on degraded historical gazette scans drops by >= 40% following multi-pass preprocessing.
- Quality scoring overhead remains <= 15 ms per page, and preprocessing remains <= 45 ms per page.
