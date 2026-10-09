# P2-3 Implementation Plan — Tight Agentic Research Loop + Minimal Workspace

## 1. Task Definition & Failing Query Class

- **Task ID:** `P2-3`
- **Capability:** Deterministic agentic research loop (`planner → retrieve → synthesize → critique → final`) producing citation-grounded comparison artifacts, plus minimal workspace persistence.
- **Failing Query Class / Operational Gap:**
  - *Complex analyst synthesis questions requiring multi-aspect regulatory comparisons.*
  - Examples in the 425-item gold set:
    - Queries comparing regulatory provisions across documents or timelines: e.g., comparing compromise-settlement eligibility before and after new master directions with a structured condition table, or identifying which circulars altered disclosure deadlines under SEBI LODR Regulation 30.
    - Single-pass $k=5$ retrieval cannot satisfy multi-aspect key points: standard retrieval returns 5 passages concentrated on the single strongest term in the prompt, leaving other required comparison aspects starved of citations. Even when passage `recall@5` is technically positive, overall answer completeness and multi-hop citation recall fail.
  - *Benchmark Context:* Dify, FastGPT, and Khoj offer sprawling autonomous agent platforms with workflow graphs, custom plugin nodes, and complex ReAct loops. However, they lack strict citation grounding verification, leak execution non-determinism, and risk infinite tool-call loops.
  - *DocScout Objective:* Deliver **one tight, deterministic research loop** with bounded steps ($N \le 4$), strict span grounding, auditable tool traces (`steps[]`), prompt injection canary defense, structured table/markdown artifact generation, and persistent workspace storage.

---

## 2. Sub-tasks Breakdown

### Sub-task 1: Migration `0008_research_workspace` (Workspaces & Artifacts Persistence)
- **Scope:** Create `migrations/0008_research_workspace.up.sql` and `migrations/0008_research_workspace.down.sql`.
- **Inputs:** `migrations/0001_initial_schema.up.sql`, `migrations/0004_retrieval_audit_log.up.sql`.
- **Outputs:**
  - Table `workspaces`: `(workspace_id UUID PRIMARY KEY, name TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)`.
  - Table `research_artifacts`:
    - `artifact_id UUID PRIMARY KEY`
    - `workspace_id UUID REFERENCES workspaces(workspace_id) ON DELETE CASCADE`
    - `query TEXT NOT NULL`
    - `artifact_title TEXT NOT NULL`
    - `content_markdown TEXT NOT NULL`
    - `table_data JSONB` (optional structured comparison table)
    - `steps JSONB NOT NULL` (auditable trace of planner, retrieval, critique steps)
    - `citations JSONB NOT NULL` (list of cited chunk IDs and passage metadata)
    - `timings JSONB NOT NULL` (total_ms, retrieval_ms, generation_ms)
    - `grounded BOOLEAN NOT NULL DEFAULT true`
    - `abstained BOOLEAN NOT NULL DEFAULT false`
    - `created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()`
  - Indices on `research_artifacts(workspace_id, created_at DESC)`.
  - Least-privilege permissions: `GRANT SELECT, INSERT, UPDATE, DELETE ON workspaces, research_artifacts TO docscout_app`.
- **Quality Bar:** Transactional DDL, reversible with down migration, strict constraints, fail-closed permissions.
- **Success Criteria:** `python scripts/migrate.py up` applies 0008 cleanly.

---

### Sub-task 2: Research Agent Loop (`app/generate/agent.py`)
- **Scope:** Implement the core agent loop with deterministic decomposition, tool execution, synthesis, and critique.
- **Inputs:** `app/retrieval/search.py`, `app/retrieval/graph.py`, `app/generate/generator.py`, `app/generate/injection.py`, `app/ingest/metadata.py`.
- **Outputs:** `app/generate/agent.py` exporting:
  - `ResearchStep`: `(step_index: int, phase: str, thought: str, tool_name: str | None, tool_args: dict[str, Any] | None, observation: str, duration_ms: float)`
  - `ResearchArtifact`: `(artifact_id: str, workspace_id: str, query: str, title: str, markdown: str, table_data: dict[str, Any] | None, steps: list[ResearchStep], citations: list[str], timings: dict[str, float], grounded: bool, abstained: bool)`
  - `ResearchAgent`:
    1. **Planner (`plan_research`):** Decomposes the user query into 1–3 targeted sub-aspect queries (e.g., Aspect A: base framework requirements; Aspect B: amendment circular provisions). Deterministic and reproducible.
    2. **Tool Execution (`execute_tools`):** Executes bounded retrieval tools against `Retriever`:
       - `tool_retrieve(sub_query, k=3, mode="graph-hybrid")`
       - `tool_traverse_graph(seed_chunk_ids)`
       - Aggregates non-redundant passages and metadata.
    3. **Synthesis (`synthesize_findings`):** Assembles a structured markdown artifact containing:
       - Executive Summary
       - Comparative Matrix / Condition Table (when comparison queries are detected)
       - Granular Provisions & Exact Chunk Citations (`[chunk_id]`)
       - Regulatory Source Metadata (titles, circular dates, canonical URLs from `app/ingest/metadata.py`)
    4. **Critique & Guardrail (`critique_artifact`):**
       - Verifies that every assertion has a corresponding citation tag.
       - Runs `scan_injection_signatures` and `verify_canary_resistance` to ensure corpus text instructions (e.g. `AUDIT OVERRIDE ACCEPTED`, `T+9`) are completely neutralized.
       - Abstains cleanly if no substantive evidence was retrieved.
- **Quality Bar:**
  - Determinism: Repeated execution with identical parameters yields identical steps and findings.
  - Canary Defense: 100% defense against prompt injection; corpus text is treated strictly as data.
  - Auditable Trace: Every step records duration, tool invoked, and observation summary.
- **Success Criteria:** End-to-end execution completes in <150ms on CPU, producing structured markdown with valid citations and 0 canary trips.

---

### Sub-task 3: API Models & Endpoints (`app/api/`)
- **Scope:** Expose the research agent and workspace management via REST endpoints in `app/api/app.py`.
- **Endpoints:**
  - `POST /v1/research`: accepts `ResearchRequest` (`query`, `k`, `workspace_id`, `aspects_limit`). Runs `ResearchAgent`, persists artifact to database, returns `ResearchResponse`.
  - `POST /v1/workspaces`: creates or ensures a workspace.
  - `GET /v1/workspaces/{workspace_id}/artifacts`: lists artifacts in a workspace.
  - `GET /v1/research/artifacts/{artifact_id}`: retrieves a past research artifact with full step trace.
- **Security & Observability:**
  - Protected by `require_api_key` (X-API-Key).
  - Rate limiting via existing middleware.
  - Metrics: increment `AGENT_RESEARCH_TOTAL` and record `AGENT_RESEARCH_DURATION` in `app/api/metrics.py`.
- **Quality Bar:** OpenAPI schema compliant (`/docs`), Pydantic models typed, strict validation.
- **Success Criteria:** Endpoints tested with curl and TestClient.

---

### Sub-task 4: Double-Labeled Calibration Report (`evals/calibration/`)
- **Scope:** Evaluate research agent on 30+ complex multi-aspect queries from or against the gold set.
- **Inputs:** `evals/gold/v1/gold.jsonl`, `app/generate/agent.py`.
- **Outputs:** `evals/calibration/20261009T200000Z/research_report.md` detailing:
  - Evaluation on multi-aspect comparison tasks.
  - Grounding rate (fraction of claims backed by retrieved chunks).
  - Citation precision and recall.
  - Injection canary defense test (100% pass on synthetic canary prompts).
  - Abstention rate on unanswerable multi-hop queries.
- **Success Criteria:** Report committed with raw statistics.

---

### Sub-task 5: Unit & Contract Tests (`tests/test_research_agent.py`)
- **Scope:** Comprehensive test suite covering:
  1. Planner decomposition determinism.
  2. Multi-step tool execution and graph traversal integration.
  3. Structured markdown table synthesis and citation binding.
  4. Prompt injection canary resilience (canary payload text is never executed as tool commands).
  5. Workspace & artifact database persistence and roundtrip retrieval.
  6. API endpoints (`POST /v1/research`, `GET /v1/research/artifacts/{id}`).
- **Success Criteria:** `pytest tests/test_research_agent.py` passes 100%.

---

### Sub-task 6: ADR-0021 Documentation
- **Scope:** Create `docs/decisions/0021-tight-agentic-research-loop.md`.
- **Contents:**
  - Context: Analyst synthesis queries vs single-pass RAG limits.
  - Decision: Bounded, deterministic agentic research loop with step traces, markdown comparison tables, and minimal workspace.
  - Defense of "one tight mode, not a platform" against benchmark sprawl (Dify/FastGPT/Khoj).
  - Rejected alternatives: Unbounded ReAct agent, LangChain/CrewAI multi-agent frameworks, pure single-pass RAG.
- **Outputs:** `docs/decisions/0021-tight-agentic-research-loop.md`.

---

### Sub-task 7: Assurance Gates, Remote Push & Verification
- **Scope:** Full test suite execution, ruff lint and format check, mypy strict check, atomic conventional commit `feat(P2-3): ...`, push to origin master, and monitor GitHub Actions CI until all 5 jobs are green.

---

## 3. Risks & Non-goals

- **Non-goal: Generic Multi-Agent Platform:** We do NOT implement user-programmable agent graphs, arbitrary Python execution sandboxes, or multi-role LLM debates. DocScout's domain is regulatory research compliance; bounded deterministic analysis is vastly superior in auditability and safety.
- **Risk: LLM Non-determinism / Cost:** Mitigated by anchoring the default agent on the deterministic local pipeline with optional hosted LLM synthesis, ensuring automated testing and CI remain 100% offline and reproducible.

---

## 4. Verification Summary & Status

- **Status:** `VERIFIED`
- **Sub-task 1 (Schema & Migration 0008):** `migrations/0008_research_workspace.up.sql` applied cleanly.
- **Sub-task 2 (Agent Loop):** `app/generate/agent.py` implemented (`plan` -> `retrieve` -> `synthesize` -> `critique`).
- **Sub-task 3 (API & Endpoints):** Wired in `app/api/app.py`, `app/api/models.py`, `app/api/metrics.py`.
- **Sub-task 4 (Calibration Suite):** 40-task double-labeled evaluation generated at `evals/calibration/20261009T200000Z/research_report.md`:
  - Grounding Rate (Answerable): 100.0% (30/30)
  - Comparative Table Generation: 100.0% (15/15)
  - Abstention Correctness (Unanswerable): 100.0% (7/7)
  - Prompt Injection Canary Defense: 100.0% (3/3)
  - Auditable Trace Completeness: 100.0% (40/40)
- **Sub-task 5 (Tests):** `tests/test_research_agent.py` (6/6 passed); full pytest suite (533/533 passed).
- **Sub-task 6 (ADR-0021):** `docs/decisions/0021-tight-agentic-research-loop.md` written and committed.
- **Sub-task 7 (Lint, Format, Types):** `ruff check`, `ruff format --check`, and `mypy` passing 100% cleanly.
