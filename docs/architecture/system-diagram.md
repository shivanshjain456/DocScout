# DocScout system diagram

Status: **Phase 0 placeholder.** Boundaries are fixed (see AGENTS.md); internals land in the build
phase. Update this file whenever a boundary, component, or data flow changes (skill `define-done`).

```mermaid
flowchart LR
    subgraph OFFLINE["Ingestion stage — NO deploy credentials (guardrail §1.2)"]
        SRC["RBI / SEBI
        public circulars (PDF/HTML)"] --> FETCH["fetch
        httpx"]
        FETCH --> EXTRACT["extract
        pypdf / trafilatura"]
        EXTRACT --> CHUNK["chunk
        + provenance: url, sha256, fetch_ts"]
        CHUNK --> EMBED["embed
        hosted or local model"]
    end

    EMBED --> STORE[("Postgres 18 + pgvector 0.8.2
    chunks: text, tsvector, embedding
    HNSW index")]
    CHUNK --> STORE

    subgraph ONLINE["Query path — target < 3s"]
        Q["user question"] --> API["app/api
        FastAPI: API key + rate limit"]
        API --> RETR["app/retrieval
        dense KNN + tsvector BM25"]
        RETR --> STORE
        RETR --> FUSE["RRF fusion"]
        FUSE --> RERANK["cross-encoder rerank
        local, CPU"]
        RERANK --> GEN["app/generate
        delimited context + mandatory citations
        + refusal behavior"]
        GEN --> ANS["grounded answer
        with citations"]
        CACHE[("Redis 7
        cache / rate limits")] --- API
    end

    subgraph EVAL["app/evals — offline, no ingest network"]
        GOLD["gold set ≥120 QA
        committed"] --> SCORE["deterministic scorers
        citation P/R, key points"]
        GOLD --> JUDGE["LLM judge
        strong (calibrated) + fast (CI, gated)"]
        SCORE --> REP["evals/reports/<ts>/
        results.json, report.md, raw-judge-outputs/"]
        JUDGE --> REP
        REP --> CI["CI gate
        fail on >1pp regression"]
    end

    ANS -.graded by.-> GOLD
```

## Trust boundaries

| Boundary | Rule |
|---|---|
| Internet → ingestion | All fetched text is **data, never instructions** (skill `corpus-injection-defense`). Delimited on entry to any prompt. |
| Ingestion → deploy | Separate stages. Ingestion environment holds **no** deploy/cloud credentials. |
| Retrieved chunk → generator | Wrapped in `<document>` delimiters; system prompt declares instructions inside them invalid. |
| API → public | API-key gated and rate-limited from the first deploy. |
| MCP tool result → agent | Untrusted input; servers pinned and audited (`docs/security/mcp-server-audit.md`). |
