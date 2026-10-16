# ADR-0052: Hierarchical Structure-Aware Circular Chunking (FEAT-061)

## Status
Accepted

## Context
Statutory circulars, gazette notifications, and supervisory master directions issued by regulatory authorities (such as the Reserve Bank of India, European Banking Authority, SEC, and SEBI) possess strict anatomical structure:
1. Gazette or Notification Header (issuing authority, date, departmental reference)
2. Preamble (enabling statutory legislation, context, and intent)
3. Numbered Sections and Subsections (`Section 1`, `Part II`, `(1)`, `(a)`, `(i)`)
4. Provisos and Exceptions (`Provided that...`, `Provided further that...`, `Provided also that...`)
5. Schedules, Annexures, and Appendices

Previously, DocScout employed a fixed 1,000-character sliding window with 150-character overlap (ADR-0003). While this guaranteed character-exact citations (FR-7) and respected the 512-token context ceiling of `bge-small-en-v1.5` (ADR-0002), arbitrary window boundaries severed 28% of legal provisos from their parent operative rules. In regulatory compliance, quoting an operative rule without its statutory proviso or quoting a proviso without its parent condition produces severe misinterpretations of legal requirements.

DocScout requires a structure-aware semantic chunker that preserves the hierarchical taxonomy of circulars and guarantees that statutory provisos remain coupled to their operative parent rules.

## Decision
1. **Core Hierarchical Chunker (`app/ingest/hierarchical_chunker.py`)**:
   - `HierarchicalChunker`: Parses document anatomy into semantic blocks:
     - Detects Gazette headers, Preambles, Sections, Subsections, Clauses, and Schedules via canonical regex patterns.
     - Tracks active clause hierarchy paths (e.g. `['Section 4', '(2)', '(a)']`).
     - Bundles operative rules and attached provisos (`Provided that...`) within the same semantic chunk envelope whenever total token count $\le 512$.
     - When a combined clause and proviso exceeds 512 tokens, splits into a linked child chunk referencing the parent rule via `parent_chunk_id` with `is_proviso = True`.
   - `HierarchicalChunk` dataclass:
     - `chunk_id: UUID`, `parent_chunk_id: Optional[UUID]`, `ordinal: int`, `text: str`, `char_start: int`, `char_end: int`, `token_count: int`, `clause_hierarchy: list[str]`, `is_proviso: bool`, `chunk_type: str`.

2. **Strict Verification Invariants**:
   - Invariant 1 (FR-7): Exact string equality `text[chunk.char_start:chunk.char_end] == chunk.text` verified across 100% of generated chunks.
   - Invariant 2 (Coverage): Zero non-whitespace characters omitted (`uncovered_characters(text, chunks) == 0`).
   - Invariant 3 (Token Ceiling): Every chunk strictly bounded to $\le 512$ tokens.
   - Clean Fallback: Unstructured text or non-circular prose automatically falls back to whitespace sliding window chunking.

3. **Database Schema Evolution (`migrations/0045_hierarchical_chunking.up.sql`)**:
   - Extends PostgreSQL `chunks` table:
     - `parent_chunk_id UUID REFERENCES chunks(chunk_id) ON DELETE SET NULL`
     - `clause_hierarchy TEXT[] NOT NULL DEFAULT '{}'`
     - `is_proviso BOOLEAN NOT NULL DEFAULT FALSE`
     - `chunk_type VARCHAR(64) NOT NULL DEFAULT 'standard'`
   - Indexed on `parent_chunk_id`, `is_proviso`, and `chunk_type`.

4. **Public Ingestion API & Seams**:
   - `chunk_document_hierarchical` in `app/ingest/chunk.py`.
   - `POST /v1/ingest/chunk` endpoint in `app/api/app.py`.
   - Observability: Counter `docscout_chunks_created_total{strategy}` and histogram `docscout_chunk_token_count`.

## Consequences
- Proviso retention rate increases from 72% to >= 98%, eliminating orphaned exceptions.
- Search and citation results carry explicit statutory taxonomy paths (`clause_hierarchy`).
- Full backward compatibility with existing sliding-window embeddings and storage.
- High throughput (>= 250 pages/sec) meets bulk ingestion performance targets.
