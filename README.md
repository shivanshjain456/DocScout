# DocScout

Citation-grounded question answering over Indian financial-regulatory circulars (RBI + SEBI), with
hybrid retrieval (BM25 + dense vectors), cross-encoder reranking, and a versioned evaluation harness.

> **Status: Phase 0 (environment) complete, pending human sign-off. No feature code exists yet.**
> See `docs/setup/SETUP_REPORT.md` for the verified environment and its known issues.

## Results

**Populated at first full eval run — no numbers before raw outputs exist.**

This section stays empty until `evals/reports/<UTC-timestamp>/results.json` exists. Every figure
published here will link to the raw report directory that produced it, including the judge's raw
outputs. Numbers without artifacts are not published (skill `rag-eval-protocol`).

| Metric | Value | Raw output |
|---|---|---|
| Faithfulness | — | — |
| Context precision | — | — |
| Citation precision | — | — |
| Citation recall | — | — |
| p95 query latency | — | — |

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
