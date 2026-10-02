# ADR-0003: Chunk at 1,000 characters with 15% overlap, over offset-preserved cleaned text

- **Status:** accepted
- **Date:** 2026-10-01
- **Deciders:** DocScout agent operator; human sign-off pending (same gate as `docs/setup/SETUP_REPORT.md` §15)
- **Closes:** **U-8** · **Related:** `SPEC.md` FR-7, FR-8, FR-4 · ADR-0002 (`D = 384`, 512-token ceiling) · `docs/architecture/ARCHITECTURE.md` §4 · `docs/corpus/CORPUS_SPEC.md` C-5, C-17 · U-10, U-11, U-16, U-17
- **Evidence:** `docs/decisions/evidence/u8-chunking-sweep.json` (14 configurations) and `docs/decisions/evidence/u8-chunking-focus.json` (6 configurations with per-probe outcome
  vectors) · harness `scripts/experiments/u8_chunking_sweep.py`

## Context

Chunking is the last decision blocking the schema. `chunks` already has `char_start` and
`char_end`, FR-7 requires every chunk to resolve to a byte range in a specific document version,
and ADR-0002 fixed the embedder at 512 tokens, which caps how large a chunk may be.

### The measurement problem, and how it was solved

You cannot compare chunking configurations with chunk-level gold labels. The unit of retrieval
*is* the thing being varied: larger chunks mean fewer candidates, each containing more text, so
"recall@1 over chunks" rewards large chunks for being large. Every number would be incomparable.

So gold is a **character span**, fixed before any chunker runs. A retrieval is correct when the
retrieved chunk's `[start, end)` covers at least half the span. That definition is identical
across configurations, and it is the same thing the production schema stores.

Three further controls:

- **Offset-preserving masking.** Each probe sentence is replaced in the indexed text by an equal
  number of spaces, never deleted, so a span measured once still points at the same characters in
  every configuration.
- **Disjoint masking batches.** The first version of this harness masked all 200 probes at once,
  blanking 26% of the corpus and starving retrieval of the context it was being asked to match.
  Probes now run in 4 disjoint batches, so at most **7.0%** of the corpus is blank in any pass.
- **A verbatim control.** The same probes against unmasked text. It lands at 0.96–0.995 for every
  configuration, which is how we know the harness works and that the masked numbers measure
  difficulty rather than breakage.

Geometry is computed once from clean, unmasked text — exactly what production would chunk — and
shared by both retrieval variants. The injection canary is indexed as a distractor but **never**
used as gold: scoring a hit on it would invert the test it exists to perform. Every configuration
is scored under BM25, dense, and RRF(60) so the decision can be checked against U-10, still open.

### Results

200 probe spans over 21 documents (139,429 chars). `integrity` is the fraction of gold spans
sitting entirely inside some chunk — deterministic, no retrieval involved. `tightness` is gold
span length over cited chunk length: **higher means a tighter citation**, lower means the reader
is handed more irrelevant text.

| config | chunks | mean tok | max tok | trunc | integrity | tightness | masked R@5 | ctx chars @5 |
|---|---|---|---|---|---|---|---|---|
| fixed-400 | 362 | 104 | 194 | 0 | 0.575 | **0.475** | 0.245 | 1,914 |
| fixed-600 | 244 | 154 | 272 | 0 | 0.755 | 0.342 | 0.395 | 2,843 |
| fixed-800 | 183 | 205 | 360 | 0 | 0.815 | 0.243 | 0.505 | 3,792 |
| fixed-1000 | 149 | 251 | 447 | 0 | 0.855 | 0.201 | 0.620 | 4,661 |
| fixed-1200 | 125 | 299 | 526 | **2** | 0.885 | 0.175 | 0.660 | 5,559 |
| fixed-800 + ov120 | 209 | 207 | 357 | 0 | 0.915 | 0.247 | 0.475 | 3,835 |
| **fixed-1000 + ov150** | **170** | **254** | **441** | **0** | **0.965** | 0.204 | 0.595 | 4,718 |
| fixed-1200 + ov180 | 145 | 297 | 524 | **1** | 0.955 | 0.174 | **0.665** | 5,532 |
| clause-800 | 199 | 188 | 360 | 0 | 0.880 | 0.295 | 0.455 | 3,487 |
| clause-1000 | 163 | 230 | 444 | 0 | 0.910 | 0.243 | 0.570 | 4,261 |
| clause-1200 | 139 | 269 | 517 | **2** | 0.950 | 0.204 | 0.600 | 4,999 |
| fixed-1000 raw (no clean) | 149 | 268 | **484** | 0 | 0.855 | 0.193 | 0.620 | 4,674 |

Paired McNemar and 10,000-sample bootstrap on identical probes (`u8-chunking-focus.json`):

| comparison | base | alt | Δ | 95% CI | p | significant |
|---|---|---|---|---|---|---|
| overlap at 1000 → **integrity** | 0.855 | 0.965 | **+0.110** | [+0.060, +0.165] | 0.0001 | **yes** |
| overlap at 1000 → masked recall | 0.620 | 0.595 | −0.025 | [−0.070, +0.025] | 0.4049 | no |
| overlap at 800 → **integrity** | 0.815 | 0.915 | **+0.100** | [+0.045, +0.155] | 0.0012 | **yes** |
| 800+ov → 1000+ov, integrity | 0.915 | 0.965 | +0.050 | [+0.005, +0.095] | 0.0639 | no |
| 800+ov → 1000+ov, **masked recall** | 0.475 | 0.595 | **+0.120** | [+0.055, +0.190] | 0.0009 | **yes** |
| 1000+ov → 1200+ov, integrity | 0.965 | 0.955 | −0.010 | [−0.050, +0.030] | 0.8036 | no |
| 1000+ov → 1200+ov, **masked recall** | 0.595 | 0.665 | **+0.070** | [+0.020, +0.120] | 0.0125 | **yes** |
| clause-1000 → fixed-1000+ov, **integrity** | 0.910 | 0.965 | **+0.055** | [+0.010, +0.105] | 0.0433 | **yes** |
| clause-1000 → fixed-1000+ov, masked recall | 0.570 | 0.595 | +0.025 | [−0.030, +0.080] | 0.4869 | no |

Unlike ADR-0002, where nothing separated the candidates, here several effects are real.

Four findings drive the decision:

1. **Overlap is the cheapest quality in the whole sweep.** It buys +0.110 span integrity at 1,000
   chars (p = 0.0001) for 21 extra chunks and *no* loss of citation tightness (0.201 → 0.204).
   Reaching comparable integrity by growing chunks instead costs tightness badly: 1,000→1,200
   gains only +0.030 integrity while tightness falls 13%.
2. **Recall and citation tightness pull in opposite directions, monotonically.** Masked R@5 climbs
   0.245 → 0.665 as chunks grow from 400 to 1,200; tightness falls 0.475 → 0.174 over the same
   range. There is no size that maximises both, so the choice is an explicit trade, not an
   optimum.
3. **1,200 characters breaches the ADR-0002 ceiling.** Even on cleaned text it produced 524–526
   token chunks against a 512 limit, truncating 1–2 chunks per configuration. Truncation silently
   discards the tail of a chunk while leaving its `char_end` claiming otherwise — a correctness
   bug in citations, not a quality tradeoff. This disqualifies 1,200 despite its significantly
   better recall.
4. **Cleaning buys token headroom, not retrieval quality.** Integrity and recall are identical
   between cleaned and raw (0.855 / 0.620 both ways). What changes is the token budget: at 1,000
   chars, raw text peaks at **484** tokens versus **441** cleaned — 94% of the ceiling versus 86%.
   ADR-0002 speculated cleaning would help retrieval; measured, it does not. It earns its place by
   keeping the chosen size safely inside the limit.

## Decision

**Chunk cleaned document text into fixed-width windows of 1,000 characters with 150 characters
(15%) of overlap, breaking at whitespace.**

Normative rules, each tied to something that breaks without it:

- Text **MUST** be cleaned before chunking, and the cleaning **MUST** preserve offsets — noise
  characters are replaced by spaces of equal length, never deleted. This is what keeps
  `char_start`/`char_end` valid against the *original* extracted text, which FR-7 requires for a
  citation to resolve to a byte range. Cleaning removes Devanagari, Latin-Extended-B/IPA mojibake,
  `U+FFFD`, and page furniture (`Page N of M`): 4,113 characters, 2.95% of the corpus.
- Chunks **MUST** break on whitespace, never mid-token.
- A chunk **MUST NOT** exceed 512 tokens under the ADR-0002 tokenizer. 1,000 characters yields 254
  tokens on average and 441 at worst here, but density varies by document (ADR-0002 measured 2.1
  chars/token at worst), so the ingest pipeline **MUST** assert the bound and hard-split any chunk
  that exceeds it rather than letting the encoder truncate silently.
- Chunk identity is `(version_id, ordinal)` with `char_start`/`char_end`; `chunk_id` **MUST**
  remain resolvable after supersession (FR-4), so chunk rows are never rewritten in place when a
  new version arrives.
- Retrieval tuning (U-10) **MUST** be done against the hybrid, never the dense arm alone. On
  verbatim probes BM25 scores a perfect 1.000 R@5 where dense reaches 0.945 — and RRF(60) scores
  0.980, *below* BM25 alone, because naive fusion dilutes an exact lexical match. On masked probes
  the ordering inverts (dense 0.570, BM25 0.570, RRF 0.595). Fusion weighting is therefore a real
  open decision, not a formality.

**What this is not.** The masked R@5 of 0.595 is not a prediction of production recall. It is a
deliberately adversarial probe in which the answer text has been removed from the index, so the
retriever must match a sentence to its surroundings. The verbatim control on the same chunks is
0.980. Real queries sit between the two, and neither number may be quoted as a system metric —
only `EVAL_PROTOCOL.md` numbers against a real gold set may be.

## Consequences

- **U-8 closes.** FR-8 moves from UNRESOLVED to SPECIFIED; with U-9 already closed, the schema and
  the ingest pipeline are unblocked and M2 can begin.
- **An offset-preserving cleaning stage is now mandatory in ingest**, and is the first concrete
  requirement M2 inherits. It is also a correctness dependency of FR-7, not a tidiness measure.
- **7 of 200 spans (3.5%) still straddle a boundary** even at the chosen configuration. These are
  permanently uncitable as a single chunk. Reranking and a read-time context window can mitigate
  the retrieval half of that, but not the citation half.
- **Citation tightness is 0.204** — about 80% of a cited chunk is not the answer. This is a
  reviewer-effort proxy, *not* the same thing as `QUALITY_BAR.md`'s citation precision ≥ 0.90,
  which asks whether the citation supports the claim. It does mean a compliance reader is handed
  roughly five times the text they need, and the cross-encoder reranker was named as the
  intended mitigation.

  **Superseded in part by ADR-0009 (2026-10-02).** The 4.56 ms/pair this bullet relied on was
  measured on short synthetic text; on real chunks the reranker costs 102–126 ms/pair, and
  measured end to end it buys three items of recall@1 for 30× the p95. It is built and tested
  but disabled, so the "intended mitigation" for over-long context is currently *not* in the
  serving path. The chunk geometry decision itself is unaffected — it was never justified by
  the reranker — but this mitigation should not be cited as available.
- **Corpus sizing gets a conversion factor**: this configuration yields one chunk per ~820
  characters of source text, so `CORPUS_SPEC.md` C-5's illustrative 10,000 chunks corresponds to
  roughly 8.2M characters — about 59× the current 139k-character sample — and ~24 minutes of
  embedding at the ADR-0002 rate of 6.9 chunks/s.
- **Clause-aware chunking is parked, not dead.** It produced the tightest citations of any
  1,000-char configuration (0.243 vs 0.204) and would likely win outright if the extractor
  preserved layout. That makes extractor quality (U-16) a lever on citation quality, which was
  not previously obvious.
- **Revisit triggers:** a real gold set (U-17) showing recall below the `QUALITY_BAR.md`
  thresholds; an extraction upgrade that restores document structure; or tables (U-11), which this
  sweep did not model at all and which fixed-width chunking will certainly shred.

## Rejected alternatives

### A. No overlap

The cheapest option, and clearly wrong. Dropping overlap at 1,000 chars costs **0.110 span
integrity** (0.965 → 0.855, p = 0.0001): 22 more of 200 answer spans get cut across a boundary
and become uncitable. The saving is 21 chunks — 14% of the index, or roughly 5 MB at the
10,000-chunk scale against ADR-0002's 36.8 MB. Buying back 11 percentage points of citability
for 14% more index is not a close call. Rejected.

### B. 1,200 characters with overlap — the best recall in the sweep

Significantly better masked recall than the chosen configuration (+0.070, p = 0.0125) and
statistically indistinguishable span integrity. It loses on a hard constraint rather than a
preference: it produced a 524-token chunk against ADR-0002's 512-token ceiling. Encoder
truncation is not a graceful degradation — the chunk's stored `char_end` would claim coverage of
text the embedding never saw, which breaks FR-7's guarantee that offsets resolve to the indexed
content. It also has the loosest citations in the sweep (0.174). Rejected on correctness, and the
recall it would have bought is recorded here as the measured price of that decision.

### C. 800 characters with overlap — the tighter-citation option

Genuinely attractive: 21% tighter citations (0.247 vs 0.204) and 19% less context per top-5
prompt. Rejected because it costs **0.120 masked recall** (p = 0.0009), the largest significant
quality gap in the sweep. Tightness only matters for answers the retriever actually finds, so
recall wins at this step. It becomes the natural fallback if context budget ever binds.

### D. Clause-aware packing

Tested rather than assumed, and the structure is partly real: 74 validated clause boundaries
across 16 of 21 documents, found by taking the longest run of inline `N.` markers incrementing by
one — a sequential check, because a naive regex also matches dates, amounts and section letters.
But the extracted text has **zero newlines**; layout did not survive pypdf, so clause detection is
inference, not parsing. It loses significantly on span integrity (0.910 vs 0.965, p = 0.0433),
gains nothing on recall (p = 0.4869), and degrades worst exactly where structure is weakest —
doc 12, the bilingual circular, yields no boundaries at all. Its tighter citations are a real
advantage, which is why this is parked for re-evaluation behind a better extractor rather than
rejected outright.

### E. 400 or 600 characters — "small chunks, precise citations"

The received wisdom, and the sweep refutes it for this corpus. At 400 chars span integrity
collapses to **0.575**: four in ten answer spans are split across a boundary before retrieval even
starts, and masked recall is 0.245. Regulatory sentences are long — the probe spans average 182
characters (62–321) — so small windows cut through the middle of the very sentences that answer questions.
Rejected.

### F. Small-to-retrieve, large-to-read (retrieve small chunks, expand context at read time)

The strongest untested alternative, and it would genuinely dissolve the recall-versus-tightness
trade: index 400-char chunks for precise citation, then expand to neighbouring text before
generation. The schema already supports it, since `char_start`/`char_end` make expansion a
substring operation. Rejected for this iteration on scope and sequencing — it is a retrieval
*and* generation design, it interacts with U-10 fusion and the context budget, and committing to
it now would decide those by implication. Recorded as the first thing to try if citation tightness
becomes the binding constraint at M4.

### G. Semantic or embedding-based chunking

Split where embedding similarity between adjacent sentences drops. Rejected on cost and
determinism: it requires embedding every sentence before chunking (roughly 4× the ingest cost at
the ADR-0002 rate), makes chunk boundaries depend on the embedding model — re-coupling U-8 to U-9
after ADR-0002 deliberately ordered them — and makes re-ingestion non-deterministic across model
versions, which `EVAL_PROTOCOL.md` §7 reproducibility forbids. Not justified by anything observed
in this corpus.
