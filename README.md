# DocScout

Citation-grounded question answering over Indian financial-regulatory circulars (RBI + SEBI), with
hybrid retrieval (BM25 + dense vectors), cross-encoder reranking, and a versioned evaluation harness.

> **Status: Phase 0 (environment) complete, pending human sign-off. No feature code exists yet.**
> See `docs/setup/SETUP_REPORT.md` for the verified environment and its known issues.

## Results

Retrieval baseline, 2026-10-01T19:29:25Z. Every number below is macro-averaged over the
131 answerable items of gold set `1.0.0` and comes from the raw file linked
beside it. Nothing here is estimated, rounded up, or carried over from a previous run.

**Serving configuration: `hybrid-rrf`** (BM25 + dense, RRF k=60, arm depth 50). See
[ADR-0006](docs/decisions/0006-hybrid-retrieval-bm25-dense-rrf.md) — it is *not* the
configuration with the best headline number, and the ADR explains why it is still the choice.

| Metric | Value | Reproduce | Raw output |
|---|---|---|---|
| Recall@1 (quote groups) | 0.695 | `make eval` | [`results.json`](evals/reports/20261001T204628Z/results.json) |
| Recall@5 | 0.966 | `make eval` | [`results.json`](evals/reports/20261001T204628Z/results.json) |
| Recall@10 | 1.000 | `make eval` | [`results.json`](evals/reports/20261001T204628Z/results.json) |
| MRR | 0.825 | `make eval` | [`results.json`](evals/reports/20261001T204628Z/results.json) |
| nDCG@5 | 0.845 | `make eval` | [`results.json`](evals/reports/20261001T204628Z/results.json) |
| Retrieval p95 latency | 42 ms | `make eval` | [`report.md`](evals/reports/20261001T204628Z/report.md) |

Hardware for the latency figure: 2 vCPU / 1.94 GiB, PostgreSQL 18.6 (Debian 18.6-1.pgdg13+2).
Retrieval only — the embedding model is loaded once per run, not per query.

### Retrieval A/B

| config | recall@5 | MRR | p95 | verdict |
|---|---|---|---|---|
| `bm25-only` | 0.970 | 0.838 | 1 ms | best headline, **not chosen** — see below |
| `hybrid-rrf` | 0.966 | 0.825 | 42 ms | **serving** |
| `dense-only` | 0.947 | 0.762 | 38 ms | weakest on every retrieval metric |

Every pairwise difference's 95% bootstrap CI includes zero: `bm25-only` leads `hybrid-rrf` by
**one item out of 131**. This benchmark cannot currently tell these three apart, and the
report says so rather than crowning a winner. Worse, the gold set's questions were written from
the evidence quotes, so they share 73.3% of their terms with the chunk they point at (9.4% for a
random chunk) — a 7.8x handicap in BM25's favour. In the least-contaminated band BM25 is the
*worst* of the three. Full working: [`report.md`](evals/reports/20261001T204628Z/report.md).

### Regression gate

`make eval-gate` fails the build when the serving configuration's recall, MRR or nDCG@5 drops
more than 1pp against the mean of the last three accepted baselines, and fails hard on
invariants that make a comparison meaningless at all — a gold set mutated without a version
bump, a changed corpus, or items that quietly vanished. Drilled against a real 1.90pp
degradation: exit 1. Raw output: [`docs/setup/verify/m4-eval-gate.txt`](docs/setup/verify/m4-eval-gate.txt).

The gate publishes its own noise floor beside each verdict. On a 131-item gold set one item is
0.76pp and the minimum detectable effect is 3.24pp, so 1pp sits inside the noise. The threshold
is enforced as specified rather than quietly widened.

### Verification story

[A retrieval miss the harness caught](docs/verification/0001-g038-fusion-miss.md): BM25 ranked
a chunk **first**, RRF fused it to rank 14, and the item scored zero recall at every cutoff.
Diagnosed to rank-only fusion discarding an arm's certainty, fixed with a bounded guarantee
([ADR-0007](docs/decisions/0007-arm-anchored-fusion.md)) chosen over constant-tuning on measured
evidence, and pinned by a regression test that fails when the fix is removed.
Recall@10 0.9924 → **1.0000**; 0 items worse, 1 better.

### Live demo and serving

```bash
make serve      # http://localhost:8000  — demo UI, /docs, /healthz
```

`POST /v1/search` returns ranked passages with **resolvable citations** — every passage
carries a stable `chunk_id`, its source document and its character span, so a caller can
open the original PDF and find the bytes. **No model generates text anywhere in the request
path**, so the endpoint cannot hallucinate: every character of regulatory text in a response
is a substring of a stored chunk, and a test re-reads each one from the database to prove it
([ADR-0008](docs/decisions/0008-serve-evidence-not-answers.md)).

The endpoint is API-key gated (`X-API-Key`, constant-time compare, rotation supported) and
rate limited per key. Missing key configuration stops startup rather than defaulting to open.

### Cost and latency

Measured over HTTP with real gold-set questions on 2 vCPU / 1.9 GiB, 200 requests per phase.
Reproduce with `make serve` then `make bench`; raw output
[`bench.json`](evals/bench/20261002T053217Z/bench.json).

| phase | mean | p50 | p95 | p99 |
|---|---|---|---|---|
| cold (cache bypassed) | 39.07 ms | 37.94 ms | **48.11 ms** | 53.19 ms |
| warm (cache hit) | 1.71 ms | 1.64 ms | **2.11 ms** | 2.68 ms |

| measure | value | reproduce |
|---|---|---|
| Cache effect on p95 | **22.8x** (46.0 ms saved) | `make bench` |
| Sustained throughput | 39.8 q/s at concurrency 4 | `make bench` |
| Cost per 1,000 queries | **$0.000078** (= about $0.08 per million) | `make bench` |
| LLM cost | $0.00 — no model in the request path | — |

Cost assumes one AWS t4g.small (2 vCPU / 2 GiB), ap-south-1, Linux on-demand at $0.0112/hour serving continuously at the
measured throughput. The price is a third-party listing, not an AWS quotation — see the
script for the source and the caveat. With no model in the request path that figure is the
*entire* query cost; any future generation step becomes the whole bill, which is why the
retrieval tier is kept separately measurable.

### Effect of reranking

A cross-encoder rerank stage is **built, tested and measured — and switched off**
([ADR-0009](docs/decisions/0009-cross-encoder-reranking.md)). Reproduce with
`uv run python -m scripts.experiments.u10_rerank_ablation`; raw output
[`results.json`](evals/experiments/u10-rerank-20261002T062322Z/results.json).

| config | recall@1 | recall@5 | recall@10 | MRR | p95 | CI excludes 0 |
|---|---|---|---|---|---|---|
| **no rerank (serving)** | 0.695 | 0.966 | **1.000** | 0.825 | **39 ms** | — |
| rerank top 10 | 0.718 | 0.977 | 1.000 | 0.850 | 1185 ms | **no** |
| rerank top 20 | 0.718 | 0.977 | 0.992 | 0.848 | 2455 ms | no |
| rerank top 50 | 0.718 | 0.977 | 0.992 | 0.848 | 6276 ms | no |

Reranking buys **+2.3pp recall@1 — three items out of 131 — for 30× to 160× the p95**, and the
bootstrap CI spans zero. Beyond the serving depth it is actively harmful: at top-20 and top-50
recall@10 falls from 1.000 to 0.992, because the cross-encoder promotes deep candidates over
evidence fusion had already placed correctly. It stays off.

**A documented cost figure was wrong by ~20×, and building this found it.** `ARCHITECTURE.md`
recorded the reranker at a *verified* 4.56 ms/pair. That was measured on short synthetic
sentences. On real corpus chunks (946 chars / 267 tokens mean) the same model on the same
hardware costs **102–126 ms/pair** — so Phase 0's ">50 ms/pair ⇒ downgrade" gate actually
**failed by 2×** rather than passing with a wide margin. Every affected document is corrected,
and `EVAL_PROTOCOL.md` E-16 now requires model costs to be quoted from real corpus chunks —
a rule the project already applied to the embedder and had not carried across.

### Not yet measured

Listed as absent rather than shown as zeros or dashes that could be misread as results.

| Metric | Status |
|---|---|
| Faithfulness | no generator — nothing generates text, so there is nothing to be faithful about ([ADR-0008](docs/decisions/0008-serve-evidence-not-answers.md)) |
| Answer-level citation precision / recall | no generator; retrieval-side citation coverage is measured above as recall over quote groups |
| LLM-judge agreement (Cohen's kappa) | **withdrawn, not pending** — U-1 closed as outcome (b) on 2026-10-02 (`EVAL_PROTOCOL.md` §4.2). No keys, and with no generator a judge would have nothing to evaluate. Enforced by `tests/test_rescope.py` |
| Cost of generation | $0.00 measured, because no model is called. A future generation step becomes the entire bill |

## Architecture

See `docs/architecture/system-diagram.md` (mermaid: ingest → store → retrieve → generate → eval).

```
Internet (RBI/SEBI)                  [untrusted data]
   └─ fetch → extract → chunk → embed → Postgres 18 + pgvector 0.8.2
                                              │
   question → API (key + rate limit) → hybrid retrieval (HNSW + tsvector)
                                     → RRF fusion → cross-encoder rerank
                                     → generation with mandatory citations
```

## Quickstart

Two scripts from a bare machine to a queryable corpus. Measured end to end at **~2 minutes**,
against the ten-minute budget.

```bash
cp .env.example .env                 # set DB_PASSWORD, DB_APP_PASSWORD, DOCSCOUT_API_KEY
                                     #   (each: openssl rand -hex 24)
bash scripts/bootstrap.sh            # ~20s  uv, Python 3.12, pre-commit, gitleaks, .venv, hooks
bash scripts/dev_db_native.sh        # ~20s  PostgreSQL 18 + pgvector 0.8.6, roles, extensions
make migrate && make ingest          # ~50s  2 migrations; 21 documents, 170 chunks
make serve                           #       http://localhost:8000
```

The corpus payloads are committed, so `make ingest` runs offline and reproduces the exact
bytes every published number was measured on — see `.gitignore` for why that reversal was
necessary.

There is no `docker compose up`. This project runs Postgres natively via
`scripts/dev_db_native.sh`, which executes the same `infra/initdb/` files a compose mount
would; the reasoning is in the `build(dev)` commit that introduced it. Docker is not
required and the script installs PostgreSQL and pgvector itself if they are absent.

Verify the install:

```bash
make verify-setup    # the V1–V17 verification matrix
make test            # 196 tests
make eval            # the retrieval baseline -> evals/reports/<UTC-ts>/
make eval-gate       # fails the build on a >1pp regression
```

Requires: `uv`, `sudo` for the two apt packages the database script installs. Nothing else.

## Repo map

| Path | Contents |
|---|---|
| `app/ingest/` | offline: fetch → extract → chunk → embed → store (runs without deploy creds) |
| `app/retrieval/` | hybrid search, RRF fusion, reranking |
| `app/generate/` | prompt assembly, citations, refusal behavior |
| `app/evals/` | gold set, scorers, judges, reports |
| `app/api/` | FastAPI surface; API keys and rate limits |
| `evals/goldset/` | the hand-built QA gold set (committed — the crown-jewel artifact) |
| `evals/reports/` | timestamped eval runs (gitignored) |
| `loadtests/` | k6 scripts; `reports/` gitignored |
| `infra/` | DB init SQL; deploy IaC lands here in the deploy phase |
| `docs/decisions/` | ADRs (Context / Decision / Consequences / **Rejected alternatives**) |
| `docs/security/` | MCP + skills audits, injection canary log, memory write log |
| `docs/setup/` | SETUP_REPORT.md and Phase 0 evidence |
| `.claude/skills/` | project skills + vendored Superpowers (pinned) |

## Commands

| Command | Does |
|---|---|
| `make dev` | compose up + uvicorn with reload |
| `make test` | pytest |
| `make lint` / `make typecheck` | ruff / mypy |
| `make eval` | full eval run → `evals/reports/<ts>/` |
| `make load` | k6 load test → `loadtests/reports/<ts>/` |
| `make secret-scan` | gitleaks over the full history |
| `make verify-setup` | the V1–V17 environment matrix |
| `make destroy` | tear down all cloud resources (deploy phase) |

## Limitations

Written to be read by someone deciding whether to trust the numbers above. Everything here
is a known gap, not a discovered one, and each line says what would close it.

**The retrieval A/B cannot currently pick a winner.** Every pairwise 95% bootstrap CI in the
published baseline includes zero. `bm25-only` leads `hybrid-rrf` by one item out of 131. Any
statement stronger than "these three are indistinguishable on this gold set" would be
unsupported. Closing it needs a larger gold set and a larger corpus.

**The gold set leaks vocabulary to the lexical arm.** Items were authored from their evidence
quotes, so a question shares 73.3% of its analyzed terms with the chunk it cites, against 9.4%
for a random chunk. That is a 7.8x advantage handed to BM25 before retrieval starts. Results
are reported stratified by that overlap so the effect is visible rather than averaged away.
Tracked as U-18; closing it needs paraphrased query variants.

**The corpus is 21 documents and 170 chunks, and the benchmark is saturated at depth 10.**
Recall@10 is 1.000 for the serving configuration and ~0.99 for every other one. That is a
ceiling effect of a tiny corpus, not a solved retrieval problem: it means recall@10 has no
power left to discriminate between architectures, and the gate's useful signal is now recall@5
and MRR. These numbers will fall when the corpus grows, and that is expected rather than a
regression.

**The regression gate runs below its own noise floor.** The gate enforces the specified 1pp
threshold, but on 131 items one item is 0.76pp and the measured minimum detectable effect is
3.24pp. The gate reports this beside every verdict. The fix is a bigger gold set, not a looser
gate.

**The API is not deployed to a public cloud URL.** It runs locally with `make serve`, and
in review it is reachable through a sandbox preview. No cloud resources have been created
for this project, by design. The 30–90 second demo video the brief asks for also does not
exist.

**The serving process is single-worker, and its cache and rate limiter live in memory.**
Neither survives a restart and neither coordinates across processes. `/healthz` reports
`single_process: true` so these counters are never mistaken for cluster-wide figures. A
multi-worker deployment needs Redis — `REDIS_URL` is already in `.env.example` — and the
in-process versions should be replaced rather than scaled.

**The cost figure is compute only, and its price is a third-party listing.** $0.08 per
million queries covers one t4g.small serving retrieval; it is not an AWS quotation and does
not include storage, egress or the LLM that does not exist yet. Re-check the price before
anyone acts on it.

**There are nine ADRs, one more than the eight the brief suggests as an upper bound.** Every
topic it names has one — pgvector over the alternatives (0004), hybrid over dense-only (0006),
the embedding arm (0002), chunk size (0003), the reranker and why-not-HyDE (0009) — plus three
that earned their place by being decisions the project actually had to make and defend:
content-derived chunk ids (0005), arm-anchored fusion (0007), and serving evidence rather than
generated answers (0008). None is filler; each has a Rejected Alternatives section with measured
reasons.

**Reranking is implemented but disabled, and that verdict is corpus-specific.** On 170 chunks
retrieval already returns every piece of required evidence (recall@10 = 1.000), so a reranker
can only reorder. It buys three items of recall@1 for 30x the latency, which is not a trade
worth making — but the benchmark is saturated and has little power to detect what a reranker
would do on a corpus where retrieval actually struggles. Re-run
`scripts/experiments/u10_rerank_ablation.py` when the corpus grows.

**There is no generator, so there are no generation metrics.** Faithfulness, context precision,
citation precision and recall, answer-level hallucination rates and end-to-end latency do not
exist yet. They are listed as absent above rather than shown as zeros.

**The LLM judge is withdrawn, not pending.** U-1 closed on 2026-10-02 as outcome (b)
(`EVAL_PROTOCOL.md` §4.2): faithfulness, answer relevance and context precision are formally
dropped as headline metrics, and no Cohen's kappa is published. Two reasons, either sufficient —
no paid API keys are available and none will be acquired; and with no generator in the request
path, faithfulness has no subject, so the honest value is *undefined* rather than 1.0. The
optional local judge that the protocol permits was declined for the same reason. The gold set's
second labelling pass was performed by the same agent that wrote the items, which is
self-agreement and not inter-rater reliability. `tests/test_rescope.py` fails the build if any of
these metrics reappears as a published number.

**No deployed demo and no CI badge.** This repository has no remote (no PAT), so the
`eval-gate` workflow has never run. The badge is deliberately absent rather than linked to a
workflow nobody has seen pass; the same commands are verified locally with raw output committed
at `docs/setup/verify/m4-eval-gate.txt`.

**The BM25 arm holds its term table in memory.** One query at startup, ~30k rows at this corpus
size. Correct now, wrong at a million chunks, where the lexical arm should move to a real BM25
index (ParadeDB `pg_search`, OpenSearch). The interface does not change when it does.

**Citations are chunk IDs, not human-readable references.** `title` and `published_date` are
NULL for the current corpus, so FR-14's "cite the document title and date" cannot be satisfied
and citations resolve to `chunk_id` instead.

**Latency figures are retrieval only, on 2 vCPU / 1.9 GiB.** The embedding model is loaded once
per run and excluded. They are not end-to-end numbers and must not be read as a service SLO.

### Logs and request correlation

Every record — the application's, uvicorn's and psycopg's — renders through one structlog
pipeline. JSON when stderr is not a TTY, human-readable when it is.

```bash
DOCSCOUT_LOG_JSON=1 DOCSCOUT_LOG_LEVEL=INFO make serve
```

Each request binds a correlation id that appears on every line it produces and is returned
as `X-Request-ID`, so a caller reporting a bad answer can quote something that joins to the
logs:

```json
{"key_fingerprint":"afae76d828ca","mode":"hybrid","duration_ms":37.3,"retrieval_ms":37.18,
 "passages":2,"event":"search.completed","request_id":"recruiter-demo-1","path":"/v1/search"}
{"status":200,"duration_ms":40.81,"event":"http.request","request_id":"recruiter-demo-1"}
```

An inbound `X-Request-ID` is honoured only if it is short and free of control characters —
it is attacker-controlled text that ends up in every log line for the request. API keys are
redacted by a pipeline processor rather than by convention, so a forgetful call site cannot
leak one; only the truncated fingerprint above is ever written.

### Rebuilding derived data

Ingestion skips any document whose source `sha256` is unchanged, which is what makes
re-running it cheap (21 documents skipped in 0.013 s). The consequence: a change to
**cleaning, chunking or the embedding model** is not picked up by `make ingest`, because
the source bytes did not move. Those changes require a deliberate rebuild:

```bash
psql "$MIGRATION_DATABASE_URL" -c "TRUNCATE chunks, document_versions, documents CASCADE;"
make ingest && python -m app.ingest verify && make eval && make eval-gate
```

Chunk ids are derived from content offsets (ADR-0005), so a length-preserving cleaning
change leaves every id — and every pinned gold citation — intact. The gate is what proves
the rebuild did not move the numbers.

## Security posture

Corpus documents are fetched from the public internet and are treated as **untrusted data, never
instructions**. Ingestion runs without deploy credentials; the eval set ships a prompt-injection
canary as a graded negative test; MCP servers and agent skills are pinned and audited
(`docs/security/`). Secrets never enter the repo — enforced by gitleaks in pre-commit.

## License

MIT — see `LICENSE`.
