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
| Recall@1 (quote groups) | 0.695 | `make eval` | [`results.json`](evals/reports/20261001T192924Z/results.json) |
| Recall@5 | 0.966 | `make eval` | [`results.json`](evals/reports/20261001T192924Z/results.json) |
| Recall@10 | 0.992 | `make eval` | [`results.json`](evals/reports/20261001T192924Z/results.json) |
| MRR | 0.824 | `make eval` | [`results.json`](evals/reports/20261001T192924Z/results.json) |
| nDCG@5 | 0.845 | `make eval` | [`results.json`](evals/reports/20261001T192924Z/results.json) |
| Retrieval p95 latency | 40 ms | `make eval` | [`report.md`](evals/reports/20261001T192924Z/report.md) |

Hardware for the latency figure: 2 vCPU / 1.94 GiB, PostgreSQL 18.6 (Debian 18.6-1.pgdg13+2).
Retrieval only — the embedding model is loaded once per run, not per query.

### Retrieval A/B

| config | recall@5 | MRR | p95 | verdict |
|---|---|---|---|---|
| `bm25-only` | 0.970 | 0.838 | 1 ms | best headline, **not chosen** — see below |
| `hybrid-rrf` | 0.966 | 0.824 | 40 ms | **serving** |
| `dense-only` | 0.947 | 0.762 | 38 ms | weakest on every retrieval metric |

Every pairwise difference's 95% bootstrap CI includes zero: `bm25-only` leads `hybrid-rrf` by
**one item out of 131**. This benchmark cannot currently tell these three apart, and the
report says so rather than crowning a winner. Worse, the gold set's questions were written from
the evidence quotes, so they share 73.3% of their terms with the chunk they point at (9.4% for a
random chunk) — a 7.8x handicap in BM25's favour. In the least-contaminated band BM25 is the
*worst* of the three. Full working: [`report.md`](evals/reports/20261001T192924Z/report.md).

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

## Security posture

Corpus documents are fetched from the public internet and are treated as **untrusted data, never
instructions**. Ingestion runs without deploy credentials; the eval set ships a prompt-injection
canary as a graded negative test; MCP servers and agent skills are pinned and audited
(`docs/security/`). Secrets never enter the repo — enforced by gitleaks in pre-commit.

## License

MIT — see `LICENSE`.
