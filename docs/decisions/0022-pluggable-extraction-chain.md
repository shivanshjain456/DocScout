# ADR-0022: Pluggable Extraction Chain with Heuristic Fidelity and Deep Fallback

- **Status:** accepted
- **Date:** 2026-10-09
- **Deciders:** Principal Engineer
- **Related:** ADR-0003 (chunking strategy), ADR-0004 (persistence schema), ADR-0005 (content-derived chunk IDs), ADR-0008 (serve evidence not answers), ADR-0012 (corpus and gold scale)

## Context

Indian financial regulation circulars (RBI Master Directions, SEBI Circulars) exhibit heterogeneous layout formats:
1. Native digital circulars with standard typography and linear paragraphs.
2. Circular annexures containing dense, multi-column financial schedules (e.g. Net Owned Fund requirements, capital adequacy ratios, risk weights).
3. Scanned annexures and stamped statutory forms where regulatory content is embedded in raster image streams.

Under naive single-parser extraction (`pypdf` plain text mode):
- Standard text extraction extracts clean documents quickly (<100ms per file).
- However, on scanned annexures, `pypdf` extracts only margin text or stamps (<50 characters per page), failing the `MIN_CLEAN_CHARS` (500) floor (FR-3 / C-11) or creating empty document stubs where retrieval recall drops to near-zero.
- Multi-column tables collapse into unstructured run-on text, destroying column-to-value associations.

At the same time, forcing deep multimodal document parsers (such as Docling, MinerU, or Marker with multi-gigabyte PyTorch vision models) across every document is unacceptable:
- It inflates Docker container images by 5–8 GB.
- Ingestion latency explodes from <2 seconds to over 5 minutes.
- Lean production environments (2 vCPU / 2GB RAM) risk Out-Of-Memory termination.

## Decision

We implement a **two-tier pluggable extraction chain** (`app/ingest/extract_chain.py`) with **heuristic fidelity evaluation** and **structured fallback**:

### 1. Two-Tier Extraction Chain (`ExtractionChain`)

- **Tier 1: Fast Path (`FastPypdfExtractor`):**
  - Uses `pypdf` plain text extraction.
  - Zero memory overhead, sub-second execution on clean text documents.
  - Preserves 100% byte-for-byte character fidelity and zero regression on clean documents.

- **Fidelity Gate (`evaluate_fidelity`):**
  - Evaluates the output of Tier 1 against strict regulatory quality heuristics:
    1. *Clean character floor:* `clean_chars >= 500` (FR-3).
    2. *Per-page density:* `chars_per_page >= 80` for multi-page documents (detects scanned image pages with only margin stamps).
    3. *Corruption / replacement ratio:* `replacement_ratio <= 0.05` (<5% corrupt characters like `\ufffd` or non-printable ASCII).
    4. *Scanned image object presence:* inspects PDF XObjects for raster image streams (`/Subtype /Image`) accompanied by sparse text.
  - If all heuristics pass, the fast extraction is accepted immediately.
  - If any heuristic fails, the chain escalates automatically to Tier 2.

- **Tier 2: Deep Fallback (`DeepFallbackExtractor`):**
  - Structured table and raster stream parser.
  - Uses PDF layout extraction mode (`extraction_mode="layout"`) to preserve spatial column alignments.
  - Linearizes multi-column tables into markdown tables (`| Column 1 | Column 2 | ... |`), preserving tabular cell associations.
  - Inspects image XObjects directly without requiring external imaging libraries (e.g., Pillow), extracting OCR text streams, alternate text (`/Alt`), and image annotations.
  - Pluggable design: dynamically binds to external `Docling` if installed in the host environment, while providing a self-contained offline parser that runs in CPU CI runners.

### 2. Runtime Configuration & Provenance

- Configurable via `DOCSCOUT_EXTRACTOR` environment variable (`app/config.py`):
  - `auto` (default): Fast path with automatic fidelity escalation to deep fallback.
  - `fast` / `pypdf`: Forces Tier 1 unconditionally (for strict baseline benchmarking).
  - `deep` / `docling` / `mineru`: Forces Tier 2 structured extraction unconditionally.
- Ingestion metadata preserves the exact extractor responsible for the document version in `document_versions(extractor)` (`"pypdf"`, `"deep-fallback"`, or `"docling"`).

### 3. Invariant Preservation (FR-7)

- Every extractor passes output through `normalise_whitespace()`.
- Canonical text remains normalized, single-spaced, and offset-stable.
- Downstream character span offsets (`char_start`, `char_end`) for citations and knowledge-graph provision nodes remain 1:1 consistent.

## Consequences

### Positive
- **Zero Regression on Clean Documents:** Clean documents (95%+ of the regulatory corpus) use the fast path with exact byte-for-byte character count preservation.
- **Scanned Annexure Recovery:** Scanned PDF fixtures with embedded OCR streams recover over 1,200 clean characters with full tabular structure where naive `pypdf` failed with <40 characters.
- **Lean Deployment Maintained:** Production container images remain lean and CPU-only; no 5GB GPU weight dependencies are introduced.
- **Audit Provenance:** Database records whether each document version was extracted via `pypdf` or `deep-fallback`.

### Tradeoffs & Maintenance
- Scanned documents with no text layer or embedded OCR streams still require OCR preprocessing before ingestion if external OCR engines (Tesseract / Cloud Vision) are not installed.
- Table linearization relies on layout whitespace detection; irregular scanned page angles may require manual verification.

## Rejected Alternatives

### Universal Docling / MinerU Execution
- **What it is:** Running Docling on every document during ingestion regardless of fidelity.
- **Why it was plausible:** Unified parsing architecture across all document types.
- **Why rejected:**
  1. Massive resource footprint: increases container image by 5+ GB.
  2. Latency: slows corpus ingestion from seconds to minutes.
  3. Risk of OOM errors on standard 2GB cloud instances.
- **Revisit condition:** If Docling releases an ultra-lightweight (<50MB) C/Rust-native inference engine that matches pypdf speed on CPU.

### External OCR Microservice (Tesseract Server / Cloud OCR API)
- **What it is:** Streaming PDF bytes to an external OCR service during ingestion.
- **Why it was plausible:** Offloads processing from the ingestion container.
- **Why rejected:**
  1. Violates offline hermetic reproducibility: ingestion tests in CI would require an external live service or network credentials.
  2. Potential data residency and regulatory compliance concerns when sending unredacted financial filings to third-party APIs.
- **Revisit condition:** In an enterprise deployment where an on-premise centralized OCR cluster is already provisioned and networked.
