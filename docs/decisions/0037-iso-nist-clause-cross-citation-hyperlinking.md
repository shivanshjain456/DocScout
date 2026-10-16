# ADR-0037: ISO/NIST Clause Cross-Citation Hyperlinking (FEAT-046)

## Status
Accepted

## Context
RBI and SEBI circulars frequently cite external international standards (e.g., "Banks must comply with ISO/IEC 27001 standards", "in accordance with NIST SP 800-53", "mandated under PCI DSS 4.0 Requirement 3.4"). Historically in compliance workflows, these citations remain static, dead text strings, requiring compliance officers to manually look up external specs, determine governing control families, and map requirements.

## Decision
1. **Standard Mention Extractor (`app/ingest/standard_mention_extractor.py`)**:
   - Ingestion-time entity extraction engine backed by the Unified Standards Registry catalog (FEAT-041).
   - Extracts character-exact span offsets, raw citation strings, canonical `standard_id`, and extracted `control_hint` (e.g. `Req 3.4`, `A.5.15`).
   - Increments Prometheus counter `docscout_standard_mentions_extracted_total{standard_id}`.

2. **Persistence Schema (`migrations/0034_document_standard_mentions.up.sql`)**:
   - Create `document_standard_mentions` table linking circular documents, chunks, and standards registry entries.
   - Foreign key constraints ensure relational integrity with `standards_registry(id)`.

3. **Document Reader & Interactive Badges (`ui/src/components/DocumentReader.tsx`)**:
   - React console document viewer that renders circular text with interactive standard badges (`.standard-mention-badge`).
   - Accessible tooltips/dialogs showing governing body, standard name, control hint, and deep links (`/standards/{standard_id}`).
   - Fallback behavior: clean unannotated text display when extractor is disabled or encounters unknown text.
   - Client-side rendering budget <= 2.0ms.

4. **API Endpoints**:
   - `POST /v1/compliance/extract-standard-mentions`: extracts mentions on arbitrary regulatory text spans.
   - `GET /v1/documents/{document_id}/standard-mentions`: returns persistent relational mentions for a document.

## Consequences
- 100% of explicit ISO, NIST, and PCI-DSS mentions across circulars become interactive cross-references.
- Zero raw text modification; raw document strings remain immutable and byte-exact.
- Client-side deep links directly connect circular clauses with DocScout's crosswalk matrix and control definitions.
