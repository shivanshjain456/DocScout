# DocScout system diagram

Status: **Production system architecture.** Implemented, verified, and active.

```mermaid
flowchart LR
    subgraph OFFLINE["Ingestion stage (no deploy credentials)"]
        SRC["RBI / SEBI
        public circulars (PDF/HTML)"] --> FETCH["fetch
        httpx"]
        FETCH --> EXTRACT["extract
        pypdf / trafilatura"]
        EXTRACT --> CLEAN["clean & guard
        blank invisible, >500 chars"]
        CLEAN --> CHUNK["chunk
        1000 chars, 150 overlap, uuid5 IDs"]
        CHUNK --> EMBED["embed
        bge-small-en-v1.5 (384d)"]
        CHUNK --> SCAN["scan
        secrets & PII scanner"]
    end

    EMBED --> STORE[("Postgres 18.6 + pgvector 0.8.6
    documents, versions, chunks
    HNSW & GIN indices
    retrieval_audit_log")]
    CHUNK --> STORE
    SCAN --> STORE

    subgraph ONLINE["Query path (FastAPI, p95 42ms cold / 2ms warm)"]
        Q["user question"] --> API["app/api
        FastAPI: API key + rate limit + audit log"]
        API --> EXP["app/retrieval
        DomainQueryExpander: acronyms & HyDE"]
        EXP --> RETR["hybrid retrieval
        dense KNN + tsvector BM25 + metadata filter"]
        RETR --> STORE
        RETR --> FUSE["RRF fusion (k=60)"]
        FUSE --> CACHE[("in-memory TTL cache
        invalidation hooks on supersession")]
        FUSE --> GEN["app/generate
        delimited context + mandatory citations
        + refusal logic"]
        GEN --> ANS["POST /v1/answer
        grounded answer with citations"]
        FUSE --> SRCH["POST /v1/search
        ranked passages with titles & dates"]
    end

    subgraph EVAL["app/evals (offline evaluation)"]
        GOLD["gold set v2.0.0
        425 items (committed)"] --> SCORE["deterministic scorers
        recall, MRR, nDCG, citation P/R"]
        GOLD --> JUDGE["judge calibration
        80 items, kappa 1.000 / 0.844"]
        SCORE --> REP["evals/reports/<ts>/
        results.json, report.md, gate.json"]
        JUDGE --> REP
        REP --> CI["CI eval gate
        make eval-gate"]
    end

    ANS -.graded by.-> GOLD
```

## Trust boundaries

| Boundary | Rule |
|---|---|
| Internet -> ingestion | All fetched text is **data, never instructions** (skill `corpus-injection-defense`). Delimited on entry to any prompt. |
| Ingestion -> deploy | Separate stages. Ingestion environment holds **no** deploy/cloud credentials. |
| Retrieved chunk -> generator | Wrapped in `<document>` delimiters; system prompt declares instructions inside them invalid. |
| API -> public | API-key gated and rate-limited from the first deploy. |
| MCP tool result -> agent | Untrusted input; servers pinned and audited (`docs/security/mcp-server-audit.md`). |
