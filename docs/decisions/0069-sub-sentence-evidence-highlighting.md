# ADR-0069: Sub-Sentence Evidence Highlighting and Span Pinpointing (FEAT-078)

* **Status:** Accepted
* **Date:** 2026-10-16
* **Deciders:** DocScout Core Engineering Team
* **Consulted:** Information Retrieval Guild, Regulatory Legal Engineering, UI/UX Engineering
* **Informed:** Core Platform Engineers, Product Operations

---

## Context and Problem Statement

A retrieved regulatory chunk spans approximately 1,000 characters (150 to 250 words) comprising multiple procedural clauses, administrative preambles, and cross-references. In time-critical compliance workflows (such as reporting a cyber security breach or verifying capital adequacy), requiring a compliance officer to manually scan a full 1,000-character paragraph introduces cognitive fatigue and review latency.

FEAT-078 introduces sub-sentence evidence highlighting and span pinpointing. By segmenting retrieved passages into statutory sentence units and scoring them against the user's semantic query intent, DocScout pinpoints the exact 1-2 operative sentences with character-exact offsets `[start, end]`. In the console UI, these pinpointed spans are highlighted in bright amber, drawing immediate visual focus to the exact operative statutory rule.

---

## Decision Drivers

1. **Character-Exact Offsets:** Pinpointed spans must provide exact integer character offsets `[start, end]` such that `passage.text[start:end] == span.text` without drift.
2. **Semantic Relevance vs Naive Keywords:** Avoid arbitrary keyword matching; rank sentences by semantic and lexical relevance to query intent.
3. **Strict Latency Budget:** Sentence boundary extraction and relevance scoring must execute in <= 2.0 ms across 5 retrieved passages on CPU.
4. **Gold Standard Overlap:** Pinpointed highlight spans must achieve >= 90% Intersection-over-Union (IoU) overlap with gold standard evidence quote spans.
5. **Configurable Boundaries:** Support `HighlightConfig` with `max_highlight_spans = 2` (default) and `min_sentence_score = 0.60` (default).
6. **Graceful Fail-Safe Fallback:** If sentence scoring fails or text has no discernable sentences, the system defaults cleanly to returning the full passage without highlights.
7. **Observability:** Track pinpointing events via `docscout_spans_highlighted_total{source}` counter.
8. **Typographical Compliance:** Strict ASCII typographical compliance across all documentation and code.

---

## Considered Options

1. **Full Heavy Cross-Encoder per Sentence:**
   * Evaluate each sentence individually through MiniLM cross-encoder.
   * *Drawbacks:* Scoring 20-30 sentences across 5 passages incurs 30-60 ms CPU latency, violating the <= 2.0 ms budget.
2. **Naive Keyword RegEx Substring Highlighting:**
   * Highlight any word appearing in both query and passage.
   * *Drawbacks:* Highlights irrelevant noise words (e.g. "report", "bank") scattered across non-operative sentences.
3. **Calibrated Semantic & Lexical Span Pinpointer (Chosen):**
   * Sentence boundary splitting with character offset tracking preserving whitespace boundaries.
   * Multi-signal scoring combining normalized query term coverage, proximity density, statutory entity/numeric alignment, and length normalization.
   * Scores calibrated to [0.0, 1.0], selecting top spans meeting `min_sentence_score` up to `max_highlight_spans`.
   * Execution time < 0.5 ms for 5 passages on CPU, with >= 90% IoU against gold evidence quotes.

---

## Decision Outcome

Adopt Option 3.

### Implementation Specifics

1. **Highlight Span Schema (`HighlightSpan`):**
   * `start: int`: Start character offset in `Passage.text` (0-indexed).
   * `end: int`: End character offset in `Passage.text` (`start < end <= len(text)`).
   * `text: str`: Exact substring corresponding to `passage.text[start:end]`.
   * `score: float`: Calibrated relevance score in [0.0, 1.0].
2. **Configuration Schema (`HighlightConfig`):**
   * `max_highlight_spans: int = 2`
   * `min_sentence_score: float = 0.60`
3. **Core Pinpointer (`app/retrieval/span_pinpoint.py`):**
   * `SpanPinpointer` with `pinpoint_highlights(query: str, text: str, config: HighlightConfig | None = None) -> list[HighlightSpan]`.
   * Splits sentences while strictly indexing character slices.
   * Computes semantic match incorporating key term intersection, exact phrase match, statutory entity/numeric bonus, and position weighting.
4. **Passage Model Integration (`app/api/models.py`):**
   * Expose `HighlightSpan` in `app/api/models.py`.
   * Add `highlights: list[HighlightSpan] = Field(default_factory=list)` to `Passage`.
5. **Retriever Integration (`app/retrieval/search.py` and `app/api/app.py`):**
   * Decorate retrieved passages with pinpointed highlights.
6. **Observability (`app/api/metrics.py`):**
   * `SPANS_HIGHLIGHTED_TOTAL = Counter("docscout_spans_highlighted_total", ..., ["source"])`.
