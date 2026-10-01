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

### Not yet measured

Listed as absent rather than shown as zeros or dashes that could be misread as results.

| Metric | Status |
|---|---|
| Faithfulness | no generator yet |
| Context precision | no generator yet |
| Citation precision / recall | no generator yet |
| LLM-judge agreement (Cohen's kappa) | blocked — no API keys (U-1); the gold set's labelling is self-agreement, not inter-rater |
| End-to-end p95 | no API yet; the figure above is retrieval only |
| Cost per 1,000 queries | no generator yet |

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

```bash
cp .env.example .env          # fill in: DB_PASSWORD, DB_APP_PASSWORD (openssl rand -hex 24)
docker compose up -d          # Postgres 18 + pgvector 0.8.2, Redis 7
uv sync --frozen              # Python 3.12 environment from the lockfile
make verify-setup             # run the V1–V17 verification matrix
```

Requires: Docker, [uv](https://astral.sh/uv), Node 22 (for the UI), k6 (for load tests).

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

**There is no generator, so there are no generation metrics.** Faithfulness, context precision,
citation precision and recall, answer-level hallucination rates and end-to-end latency do not
exist yet. They are listed as absent above rather than shown as zeros.

**There is no LLM judge and no Cohen's kappa.** No API keys are available (U-1), and the gold
set's second labelling pass was performed by the same agent that wrote the items. That is
self-agreement, not inter-rater reliability; a test asserts that no kappa is claimed anywhere.

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

## Security posture

Corpus documents are fetched from the public internet and are treated as **untrusted data, never
instructions**. Ingestion runs without deploy credentials; the eval set ships a prompt-injection
canary as a graded negative test; MCP servers and agent skills are pinned and audited
(`docs/security/`). Secrets never enter the repo — enforced by gitleaks in pre-commit.

## License

MIT — see `LICENSE`.
