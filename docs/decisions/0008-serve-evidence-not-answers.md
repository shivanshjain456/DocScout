# ADR-0008: Serve retrieved evidence, not generated answers

- **Status:** accepted, with an explicit reversal condition
- **Date:** 2026-10-02
- **Deciders:** DocScout agent operator; human sign-off pending (same gate as `docs/setup/SETUP_REPORT.md` §15)
- **Related:** ADR-0005 (stable chunk ids, which is what makes a citation checkable later) · ADR-0006 / ADR-0007 (the retrieval configuration this endpoint serves) · `EVAL_PROTOCOL.md` §4.1 and U-1 (judge feasibility) · `SPEC.md` FR-14 (citation format)
- **Evidence:** `app/api/` · `tests/test_api.py` (35 cases) · `scripts/bench_api.py` and `evals/bench/20261002T054058Z/bench.json`

## Context

DocScout is specified as a RAG service, and the obvious shape for its API is
`question in, answer out, citations attached`. The generation half of that cannot be built
honestly right now: there are no LLM API keys (U-1), there is no calibrated judge, and
there is therefore no measurement of whether a generated answer is faithful to its sources.

The project's whole claim is that its numbers are honest. Shipping prose that nothing
measures  -  over regulatory text, where a wrong number is the entire failure mode  -  would
contradict that claim in the one place a reader looks first.

The corpus is also unusually unforgiving. Documents are withdrawn (gold item g-038 is about
a withdrawn circular), amounts and dates carry legal weight, and a plausible-sounding
paraphrase of a settlement timeline is worse than no answer at all.

## Decision

**`POST /v1/search` returns ranked passages with resolvable citations. No model generates
text anywhere in the request path.**

Each passage carries its `chunk_id`, `document_id`, source authority, canonical URL and
character span, so a caller can open the original PDF and find the bytes. ADR-0005 made
those ids stable across re-ingests, which is what keeps a saved response checkable months
later rather than merely checkable today.

Three consequences of the "no generation" choice are deliberate, not accidental:

1. **The endpoint cannot hallucinate.** Not "is unlikely to"  -  it has no generative
   component. Every character of regulatory text in a response is a substring of a stored
   chunk, and `tests/test_api.py::test_search_returns_checkable_citations` asserts exactly
   that by re-reading each returned chunk from the database and comparing text and span.
2. **The published numbers describe this code path.** The eval harness measures retrieval
   over the same `SERVING_CONFIG`, so the README's recall and MRR are properties of the
   thing being served, not of a different pipeline that shares a name.
3. **Nothing is claimed that is not measured.** There is no faithfulness figure, because
   there is nothing to be faithful about.

### Reversal condition

When API keys exist: add generation *behind* this endpoint, not instead of it  -  the
passages stay in the response, the generated answer is an additional field, and it ships
only once the judge is calibrated against 60–100 human labels with Cohen's κ reported
(EVAL_PROTOCOL §4.1 and §5). Until κ exists, a generated answer would be an unmeasured
claim, which is the failure this ADR exists to avoid.

## Operational decisions, and why

**Shared-secret API key, not OAuth or JWT.** There is one kind of caller and no user
identity to model. A JWT would add a signing key, an expiry policy and a refresh path to
protect read-only search over public documents. The threat is an open endpoint on a public
URL burning CPU, not impersonation. Comparison is `secrets.compare_digest`, keys are
comma-separated so one can be rotated without downtime, and only a truncated SHA-256
fingerprint is ever logged.

**Missing key configuration stops startup.** `load_keys()` raises rather than defaulting to
"no auth". An API that disables its own authentication when an environment variable is
absent looks healthy, serves everything and explains nothing in the logs. Tested.

**Everything expensive loads once.** The encoder (~13 s) and the BM25 term table load in the
lifespan handler, before the first request is accepted. Doing either per request would make
the published p95 a measurement of initialisation rather than of retrieval.

**A connection pool, not a shared connection.** FastAPI runs synchronous handlers in a
worker thread pool, so one shared `psycopg` connection would be used concurrently from
several threads. `max_size=4` is sized against 2 vCPU, where more concurrent retrievals
queue on CPU regardless and each idle backend costs memory on a 1.9 GiB host.

**Errors are generic to the caller and detailed in the log.** An unexpected exception
returns `internal error (reference <id>)`; the traceback and the correlation id go to the
log. The 422 handler also strips Pydantic's `input` field, which would otherwise reflect
caller data back into a response body. Both are tested, including that a connection string
raised from inside a handler never appears in the response.

## Measured

`scripts/bench_api.py`, 200 requests per phase over HTTP, real gold-set questions, on
2 vCPU / 1.9 GiB:

| phase | mean | p50 | p95 | p99 |
|---|---|---|---|---|
| cold (cache bypassed) | 39.07 ms | 37.94 ms | **48.11 ms** | 53.19 ms |
| warm (cache hit) | 1.71 ms | 1.64 ms | **2.11 ms** | 2.68 ms |

Caching is worth **22.8× on p95** (46.0 ms saved). Sustained throughput is 39.8 q/s at
concurrency 4, which puts compute cost at **$0.000078 per 1,000 queries  -  about $0.08 per
million** on an AWS t4g.small in ap-south-1 at $0.0112/hour.

The relevant observation for the "your LLM bill is too high" question: with no model in the
request path, that $0.08 per million *is the entire query cost*. Any future generation step
is the whole bill, which is the argument for keeping the retrieval tier separately
measurable rather than folding it into one opaque endpoint.

## Rejected alternatives

### A. Return a generated answer now, using a local small model

Technically possible  -  the machine already runs a 384-dim encoder and a cross-encoder  -  and
it would make the demo look complete. Rejected: a small local model over regulatory text
produces exactly the confident, wrong, unverifiable prose this project exists to measure,
and there is no judge to catch it. It would also mean the README's numbers described
retrieval while the demo showed generation.

### B. Extractive "answers"  -  return the single best sentence as the answer

Tempting, since it adds no model and looks like an answer. Rejected: selecting one sentence
is itself an unmeasured claim about which sentence answers the question, and the gold set
scores *citations*, not sentence selection. It would manufacture a metric-free assertion in
a system whose point is that every assertion has a metric. Returning the ranked passages
says the same thing without pretending to more precision than has been measured.

### C. No authentication, since the corpus is public

The data is public; the CPU is not. An unauthenticated retrieval endpoint on a public URL
is an open invitation to exhaust a 2 vCPU box, and a demo that falls over is worse than one
that asks for a key. The key also makes per-caller rate limiting possible at all.

### D. Redis for the cache and the rate limiter

Correct for more than one process, and `REDIS_URL` is already in `.env.example` for when
that day comes. Rejected now: it adds a service to the quickstart  -  which has to stay under
ten minutes and currently runs with two scripts  -  to solve a problem a single worker does
not have. The in-process limitation is not hidden: `/healthz` reports `single_process: true`
precisely so nobody reads these counters as cluster-wide.

### E. Streaming responses

Nothing to stream. Retrieval returns in one step, and p95 is 51 ms cold. Streaming matters
when a generator emits tokens over seconds, so this belongs with the reversal condition
above, not before it.

### F. Serving the demo UI from a CDN-backed framework

Rejected for two reasons, one practical and one about habit. The page is reviewed inside a
sandboxed frame with no network, where a CDN reference degrades silently to an unstyled
page. And a page where someone pastes an API key should not be loading third-party
JavaScript, regardless of how reputable the CDN is. The UI is one self-contained HTML
string with inline CSS, and a test asserts it references no external asset.
