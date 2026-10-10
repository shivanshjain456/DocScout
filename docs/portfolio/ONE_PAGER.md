# DocScout — Executive Summary & Portfolio One-Pager

> **Headline:** DocScout — citation-grounded RBI/SEBI RAG, hybrid-rrf MRR 0.854 @ p95 42ms, 448 fns (555 cases), 5/5 green.

DocScout is a production-grade, citation-grounded retrieval-augmented generation engine engineered specifically for complex Indian financial-regulatory circulars (RBI and SEBI).

---

## Core Architectural Pillars

- **Hybrid Retrieval with Arm-Anchored RRF ([ADR-0007](../../docs/decisions/0007-arm-anchored-fusion.md)):** Fuses dense semantic vector search (BGE-small-en-v1.5, 384d) with BM25 lexical search using reciprocal rank fusion. Bounded guarantee prevents top lexical matches from being washed out by semantic rank dilution.
- **Production Subsystems with Provenance Guard ([ADR-0024](../../docs/decisions/0024-external-integrations-governance.md) / [ADR-0025](../../docs/decisions/0025-synthetic-data-quarantine.md) → E-18):** Auth0 identity (`PyJWKClient`), Brevo transactional digests (`300/d` quota, `uq_digest_delivery_version` dedup invariant), and OCR.Space inspection (`1MB/3p` eligibility), hard-guarded against synthetic contamination via `NOT d.is_synthetic`.
- **Offline Ingest & Calibrated Online Eval Harness:** Versioned 425-item gold set (365 scored items, ADR-0012) with calibrated automated judge (84 items) and double-labelled research synthesis (40 tasks), ensuring 100% citation grounding and 0% hallucination.

---

## Technology Stack

| Layer | Technologies & Specifications |
|---|---|
| **Embeddings & Search** | BGE-small-en-v1.5 (384d), pgvector 0.8.6 HNSW indexing, PostgreSQL 18.6 full-text BM25 |
| **Backend & Serving** | Python 3.12, FastAPI, Uvicorn, Pydantic v2, strict typing (Mypy 106 source files clean) |
| **Frontend & UI** | React 19, TypeScript, Vite, Tailwind CSS, Playwright E2E smoke tests |
| **Persistence & Cache** | PostgreSQL 18.6 + pgvector 0.8.6 triple-pin, in-memory LRU cache, optional Redis backend |
| **Observability & Ops** | Prometheus `/metrics`, zero-DB `/healthz`, readiness `/readyz`, GitHub Actions 5/5 CI workflows |

---

## Production Evidence & Verifiable Artifacts

- **Retrieval Baseline Report:** [`evals/reports/20261010T050559Z/results.json`](../../evals/reports/20261010T050559Z/results.json) (Recall@5: 0.966, MRR: 0.854 @ p95 42ms).
- **CI/CD Quality Gates:** GitHub Actions run [`38037523415`](https://github.com/shivanshjain456/DocScout/actions/runs/38037523415) (5/5 green: `quality`, `supply-chain`, `secrets`, `eval-gate`, `deploy-smoke`).
- **User Interface Proof:** Interactive console surfacing Search, Auth0 Identity, Brevo Digests, and OCR Inspector:
  - System Demo: [`docs/assets/demo.png`](../assets/demo.png)
  - Full-Stack Console: [`docs/assets/ui-console.png`](../assets/ui-console.png)

---

## Deployment & Distribution

- **Pre-built OCI Container:** `docker run -p 8000:8000 ghcr.io/shivanshjain456/docscout:1.0.1` (or `ghcr.io/shivanshjain456/docscout:latest`)
- **Deterministic Local Stack:** `cp .env.example .env && make deploy` (reproducible offline stack under 90s)
- **API Documentation & Metrics:** OpenAPI Swagger UI at `http://localhost:8000/docs`, Prometheus telemetry at `http://localhost:8000/metrics`

---

## Resume Bullets (copy-paste)

- Architected citation-grounded RAG over RBI/SEBI circulars; hybrid BM25+dense RAG achieved MRR 0.854 at 42ms p95 across 365 gold evaluations.
- Engineered Auth0 identity, Brevo digests (300/day quota), and OCR pipelines guarded by strict synthetic-data provenance invariant in CI/CD.
- Enforced deterministic CI eval gate (1pp drop threshold), strict typing across 106 files, containerized GHCR deployment, and 5/5 green workflows.
