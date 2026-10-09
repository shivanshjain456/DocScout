# ADR-0002: Pin the embedding model and the vector dimension

- **Status:** accepted
- **Date:** 2026-10-01
- **Deciders:** DocScout agent operator; human sign-off pending (same gate as `docs/setup/SETUP_REPORT.md` §15)
- **Closes:** **U-9** · **Related:** `SPEC.md` FR-16, NFR-5, OUT-6 · `docs/architecture/ARCHITECTURE.md` §4 · `docs/corpus/CORPUS_SPEC.md` C-5 · `docs/MILESTONES.md` M1 · U-1, U-8, U-10, U-17
- **Evidence:** `docs/decisions/evidence/u9-embedding-bakeoff.json` · harness `scripts/experiments/u9_embedding_bakeoff.py`

## Context

`chunks.embedding` is declared `vector(D)`. `D` is fixed by the embedding model, and
`ARCHITECTURE.md` already calls it a one-way door. Nothing downstream  -  schema, HNSW index,
ingest, eval baselines  -  can be built until it is pinned.

Phase 0 established that `BAAI/bge-small-en-v1.5` **runs**: 384 dimensions, 112.4 sentences/s,
129 MB, CPU-only (V12). It established nothing about whether the model **retrieves** anything
useful from RBI and SEBI circulars, because the smoke test embedded 1,000 generic sentences.
`config/models.json` additionally claims the model was "chosen over all-MiniLM-L6-v2: stronger
retrieval quality on MTEB at comparable size and speed". That is a leaderboard argument about
other people's corpora, not a measurement on ours  -  exactly the kind of claim `SPEC.md` §1
forbids treating as VERIFIED.

**Why decide now rather than after U-8 (chunking).** Two reasons, both about sequencing.

1. **U-9 constrains U-8, not the reverse.** The model's maximum sequence length bounds how large
   a chunk may be. Chunking can be re-tuned freely inside a fixed `D`; `D` cannot be re-tuned
   inside a fixed chunker.
2. **The one-way door is cheap to walk through today and expensive next month.** The real cost of
   changing `D` is not compute  -  it is that every historical evaluation run becomes incomparable
   (`EVAL_PROTOCOL.md` §7) and the ">1pp regression against the mean of the last 3 baselines" gate
   needs three fresh baselines. **That cost is zero right now, because no gold set and no baseline
   exist yet.** The window closes the moment U-17 lands. Deciding `D` before the gold set is the
   difference between a configuration change and a migration.

So an experiment was run on the real corpus, on the real hardware floor.

### What was measured

149 chunks from all 21 corpus documents (139,140 chars; fixed-width 1,000-char non-overlapping
chunks  -  a placeholder that decides nothing about U-8, held constant so the model is the only
variable). Four candidate models plus a **BM25 lexical control arm**, scored on two independent
probe sets:

- **Probe A  -  21 hand-written queries**, document-level gold, each label verified by reading the
  source circular. Split into `lex` (reuses the document's own terminology) and `para`
  (deliberately avoids it), because lexical overlap flatters BM25 and a single blended number
  would mislead.
- **Probe B  -  141 masked-sentence known-item probes.** A sentence is lifted out of a chunk to
  serve as the query **and deleted from the indexed copy**, so no model can win by matching a
  sentence to itself. Sentences occurring more than once corpus-wide are rejected, so gold labels
  are unambiguous. Chunks are non-overlapping precisely so the masked sentence cannot leak into a
  neighbour.
- **Harness control.** The same 141 probes run against the *unmasked* corpus. If that does not
  score far higher than the masked run, the harness is broken and no number means anything.

Each model's documented instruction prefix was applied (`Represent this sentence for searching
relevant passages: ` for BGE, `query: `/`passage: ` for E5, none for MiniLM). Omitting them is a
silent handicap, and applying them is itself a production requirement  -  see Consequences.

### Results

Control first, because everything else depends on it:

| arm | unmasked control R@1 | masked R@1 |
|---|---|---|
| bm25-okapi | 0.8794 | 0.2199 |
| bge-small-en-v1.5 | 0.8227 | 0.1844 |
| all-MiniLM-L6-v2 | **0.6738** | 0.1844 |
| bge-base-en-v1.5 | 0.8582 | 0.1986 |
| multilingual-e5-small | 0.7376 | 0.2128 |

The control lands at 0.67–0.88 against 0.18–0.22 masked. The harness works, and masking is doing
real work. The control does not reach 1.0 because adjacent chunks of templated regulatory prose
are near-duplicates, which is itself a finding: **chunk-level gold is intrinsically ambiguous in
this corpus**, and M2 retrieval metrics should be reported at document level or at Recall@5+.

| arm | D | disk | max seq | truncated | q p95 | A R@1 | B R@1 | B R@5 | B MRR |
|---|---|---|---|---|---|---|---|---|---|
| bm25-okapi |  -  |  -  |  -  | 0/149 | 0.42 ms | 0.9524 | **0.2199** | 0.5603 | **0.3434** |
| **bge-small-en-v1.5** | **384** | 128.3 MB | 512 | **0/149** | 39 ms | 0.9048 | 0.1844 | 0.4681 | 0.3070 |
| all-MiniLM-L6-v2 | 384 | 87.3 MB | **256** | **72/149** | 20 ms | 1.0000 | 0.1844 | 0.4397 | 0.3048 |
| bge-base-en-v1.5 | 768 | 418.7 MB | 512 | 0/149 | 91 ms | 1.0000 | 0.1986 | 0.5390 | 0.3338 |
| multilingual-e5-small | 384 | 470.4 MB | 512 | 1/149 | 39 ms | 0.9524 | 0.2128 | 0.5106 | 0.3363 |

Paired bootstrap (10,000 resamples) and exact McNemar on the same 141 probes, against bge-small:

| vs bge-small | Δ R@1 | 95% CI | Δ MRR | 95% CI | McNemar p | significant |
|---|---|---|---|---|---|---|
| bm25-okapi | +0.0355 | [−0.035, +0.106] | +0.0364 | [−0.020, +0.093] | 0.4244 | **no** |
| all-MiniLM-L6-v2 | +0.0000 | [−0.050, +0.050] | −0.0022 | [−0.044, +0.040] | 1.0000 | **no** |
| bge-base-en-v1.5 | +0.0142 | [−0.035, +0.064] | +0.0268 | [−0.009, +0.064] | 0.7744 | **no** |
| multilingual-e5-small | +0.0284 | [−0.028, +0.085] | +0.0293 | [−0.024, +0.081] | 0.4807 | **no** |

**Not one difference is statistically significant. Every confidence interval straddles zero.**

Three findings matter more than the rankings:

1. **MiniLM truncates 72 of 149 chunks  -  48%  -  at its 256-token limit**, and has by far the worst
   control score (0.674). Probe A still gave it 1.0, because a document's subject line sits in the
   first 256 tokens; the easy metric completely hid a structural defect. This is the real reason
   to reject it, and it is a better reason than the MTEB hand-wave currently in
   `config/models.json`.
2. **BM25 alone matches or beats every neural embedder on this corpus** (highest masked R@1 and
   MRR, 0.42 ms per query, zero model to ship). Not significantly better  -  but a free lexical
   baseline that ties the field is decisive evidence that **a vector-only retriever would be a
   regression**, and that the hybrid design in `ARCHITECTURE.md` is earned rather than assumed.
   It raises the stakes on U-10 (fusion and depths).
3. **Latency is not the constraint.** Worst single-query encode p95 is 91 ms against a 3 s
   end-to-end budget (NFR). Quality and footprint decide this, not speed.

### Two corrections this experiment forces

**Token density, and the chunk ceiling it implies.** Measured over 146 windows with the bge
tokenizer: mean 0.2854 tokens/char (3.5 chars/token), p95 0.4190, worst observed 0.4860 (2.1
chars/token  -  doc 12, 486 tokens in 1,000 chars). A 512-token budget therefore permits ~1,786
chars at mean density but only **~1,217 chars at p95 density and ~1,049 at worst observed**.
Devanagari-bearing documents run 0.3191 tokens/char against 0.2226 for English-only text  -  **the
Hindi masthead costs ~43% more tokens per character.** Stripping it at ingest roughly doubles the
safe chunk size. This is a hard input to U-8.

**`CORPUS_SPEC.md` C-5's embedding-throughput extrapolation is wrong by ~16×.** It reasons from
112.4 *sentences*/s to "~10,000 chunks ≈ 90 s". Measured on real 1,000-char regulatory chunks,
bge-small does **6.9 chunks/s**, so 10,000 chunks is **~24 minutes**, not 90 seconds. The Phase 0
measurement was correct; the extrapolation silently swapped "short generic sentence" for
"1,000-character chunk of dense regulatory prose". Corrected in `CORPUS_SPEC.md`; the signed
Phase 0 report keeps its original wording with a pointer here.

## Decision

**Pin `BAAI/bge-small-en-v1.5` at `D = 384`.** `chunks.embedding` becomes `vector(384)`, indexed
HNSW with `vector_cosine_ops`.

Normative, because each one silently degrades retrieval if dropped:

- Query embeddings **MUST** be prefixed with `Represent this sentence for searching relevant
  passages: `. Passage embeddings **MUST NOT** be prefixed.
- All embeddings **MUST** be L2-normalised, so cosine distance and inner product agree, matching
  the `vector_cosine_ops` index and the V2 cosine check.
- Chunk length **MUST NOT** exceed 1,200 characters while bilingual mastheads remain in the text;
  the ingest pipeline **SHOULD** strip them, after which the ceiling rises to ~2,200.
- The model ID **MUST** be recorded in every evaluation run's provenance block
  (`EVAL_PROTOCOL.md` §6), because `D` is not inferable from results alone.

The choice is explicitly **not** "bge-small is the most accurate model". Nothing in this
experiment can support that claim. It is: *no candidate is measurably better, so take the one with
the fewest structural defects and the lowest cost.* bge-small is the only candidate with zero
truncation at the working chunk size, the smallest index at 384 d, 128 MB on disk, free, CPU-only,
and English-only in line with OUT-6.

## Consequences

- **U-9 closes.** FR-16 moves from UNRESOLVED to SPECIFIED; the schema can be written and M2 can
  start. `config/models.json` keeps the same model but its rationale is replaced with a measured
  one.
- **U-8 inherits a hard bound** (≤1,200 chars now, ~2,200 after masthead stripping) and an
  explicit warning that adjacent-chunk ambiguity is high in this corpus.
- **Hybrid retrieval is now evidence-backed.** BM25 must be in the retriever, not an optional
  extra. U-10 should be tuned against the BM25-only numbers recorded here as the floor to beat.
- **Index budget is known.** 384 d costs 1,544 bytes/vector → ~37 MB at 10k chunks and ~368 MB at
  100k (HNSW included, ~2.5× raw). At 768 d those become 73 MB and 734 MB; on the 1.9 GiB floor
  the 100k case is a material fraction of RAM. This is the quantitative reason 768 was rejected.
- **Re-embedding cost is now real**: ~24 min per 10k chunks on the 2 vCPU floor, not 90 s.
- **This decision is revisable until U-17 lands**, and expensive afterwards. Revisit triggers:
  (a) a gold set exists and shows retrieval recall below the `QUALITY_BAR.md` thresholds;
  (b) the corpus stops being predominantly English; (c) U-1 unblocks a hosted embedder and a
  measured comparison becomes possible.
- **A dependency is added in spirit, not in code**: nothing in `app/` imports the harness. The
  experiment script is kept as evidence, not as a module.

## Rejected alternatives

### A. `sentence-transformers/all-MiniLM-L6-v2` (384 d)

The incumbent's named rival, and the only candidate rejected on a *structural* rather than
statistical basis. Its 256-token window truncates 48% of 1,000-char chunks, silently discarding
the second half of every substantial chunk, and it posts the worst unmasked control score of the
field (0.674 against 0.823 for bge-small). It is the fastest and smallest option, and on the
saturated document-level probe it scored a perfect 1.0  -  which is precisely how a defect like this
survives a casual benchmark. Rejected.

### B. `BAAI/bge-base-en-v1.5` (768 d)  -  the "just use a bigger model" option

Numerically the best embedder on probe B (R@1 0.1986, MRR 0.3338), and genuinely better than
bge-small on the unmasked control (0.858 vs 0.823). But the gap is **not significant**
(Δ R@1 +0.014, CI [−0.035, +0.064], p = 0.77), and it costs 2× index bytes, 2.3× query latency,
3.3× disk, and 2.9× encode time. Doubling `D` on an unproven quality gain, through a door that
only opens one way, is the wrong trade at this stage. Rejected  -  revisit if a gold set shows a
real deficit.

### C. `intfloat/multilingual-e5-small` (384 d)

Hypothesis worth testing rather than assuming, given 2.52% of the corpus is Devanagari and doc 12
is 33% Hindi interleaved throughout. It did score second-best on probe B  -  but again not
significantly (Δ R@1 +0.028, p = 0.48), while costing 470 MB on disk against 128 MB. The
bilingual problem is better solved upstream: the Hindi is a masthead in 9 of the 10 affected
documents and duplicates the English, so stripping it at ingest removes the noise *and* buys back
43% of the token budget. Rejected, with doc 12 logged as a genuine exception to revisit under
U-16.

### D. A hosted embedder (OpenAI `text-embedding-3-small`, 1536 d)

Not evaluated, and honestly recorded as such rather than dismissed. It is **BLOCKED by U-1**: no
API keys are available and the operator has ruled out paid keys, so there is no way to measure it
and no way to run it in CI. It would also reintroduce a per-query credential dependency and
network hop into the hot path (K-1), and at 1536 d would quadruple the index against 384 d. If
U-1 ever unblocks, this ADR should be reopened with a measured comparison  -  not replaced by a
leaderboard argument.

### E. Defer U-9 until the gold set exists

Superficially the rigorous choice: decide with real evaluation data instead of 141 synthetic
probes. Rejected because it inverts the cost curve. Building the gold set (U-17) requires an
embedded, indexed corpus to retrieve against, so deferring `D` blocks the very work that would
inform it; and once baselines exist, changing `D` invalidates them. Deferring does not buy better
evidence  -  it buys the same decision later, at a higher price. The honest alternative is what this
ADR does instead: decide now, state plainly that quality is unmeasured at this scale, and write
down the triggers that would reopen it.

### F. Matryoshka-style truncatable embeddings (e.g. `nomic-embed-text-v1.5`)

Genuinely attractive, because they would defuse the one-way door: train at 768, store a truncated
prefix, change `D` later without re-embedding. Rejected for this iteration on scope  -  it adds a
model family nobody here has measured, and the door it defuses is, by the argument in Context,
already cheap to walk through today. Worth revisiting at M3 if `D` becomes contested.
