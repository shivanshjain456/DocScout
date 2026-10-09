# DocScout: Security

**Status:** authoritative security policy and threat model. Last updated **2026-10-09**.
**Implementation status:** application and repository security controls are **IMPLEMENTED AND VERIFIED**.

Status tags (**VERIFIED / SPECIFIED / PROPOSED / BLOCKED / RESOLVED**) are defined in `SPEC.md` §1.
Audit records live in `docs/security/`.

---

## 1. What is being protected

| Asset | Why it matters | Exposure |
|---|---|---|
| **Answer integrity** | Cited answers are used by compliance analysts; hallucinations must be prevented | Prompt injection, retrieval failure, extraction loss |
| **Credentials** | Database passwords, API keys | Repository history, logs, CI, agent tool surfaces |
| **The corpus pipeline** | Ingests untrusted third-party PDFs into model contexts | Malformed or adversarial documents |
| **The gold set** | The project's quality baseline and regression ruler | Tampering or silent drift |
| **Query privacy** | Analyst questions may carry sensitive compliance context | Logs, databases, analytics |

---

## 2. Threat model

| ID | Threat | Realistic? | Control | Status |
|---|---|---|---|---|
| T-1 | **Indirect prompt injection** via untrusted PDF instructions | Yes (primary threat) | S-7, S-8 | VERIFIED (100% canary defense) |
| T-2 | **Secret committed to git** | Yes | S-1, S-2 | VERIFIED (gitleaks in pre-commit & CI) |
| T-3 | **Fabricated or unresolvable citation** reaching users | Yes | S-9 | VERIFIED (deterministic citation check) |
| T-4 | **Supply-chain compromise** via dependencies or skills | Yes | S-10, S-11, S-12 | VERIFIED (pip-audit & SBOM in CI) |
| T-5 | **Credential bleed between stages** (ingest vs deploy) | Yes | S-4 | VERIFIED (fail-fast guard in ingest) |
| T-6 | **API abuse** (unauthenticated or unbounded requests) | Yes | S-5, S-6 | VERIFIED (API key auth & rate limiting) |
| T-7 | **Data exfiltration through logs** | Yes | S-13 | VERIFIED (structlog key & query redaction) |
| T-8 | **SQL injection** via user input in search queries | Yes | S-15 | VERIFIED (parameterized SQL in psycopg) |
| T-9 | **Agent-caused damage** (destructive bash commands) | Yes | S-16 | VERIFIED (executable bash denylist hook) |
| T-10 | **PII and secret leakage in corpus** | Yes | S-21 | VERIFIED (ingestion scanner with masking) |

---

## 3. Trust boundaries

Five explicit boundaries with dedicated controls:
1. **Internet -> ingestion**: All fetched text is treated as untrusted data, never instructions.
2. **Ingestion -> deploy**: Ingestion runs with no deploy credentials in its environment.
3. **Retrieved chunk -> generator**: Wrapped in `<document>` delimiters; system prompt declares enclosed text to be data only.
4. **API -> public**: API-key gated and rate-limited.
5. **MCP tool result -> agent**: Untrusted input; servers pinned and audited (`docs/security/mcp-server-audit.md`).

---

## 4. Controls

### 4.1 Secrets: VERIFIED

- **S-1**: No secret in repository or history. `gitleaks` runs as pre-commit hook and CI job with full history scan.
- **S-2**: `.env` and `.env.*` are gitignored; `.env.example` is tracked and contains only placeholder strings.
- **S-3**: Secrets are referred to by name and scope only in documentation, never by value.
- **S-4**: Ingestion fails fast if deploy credentials (`AWS_SECRET_ACCESS_KEY`, etc.) are detected in environment.

### 4.2 Application surface: VERIFIED

- **S-5**: Every protected endpoint requires an API key via `X-API-Key` using constant-time comparison. Missing keys fail startup.
- **S-6**: Rate limiting enforced per key.
- **S-9**: Citation validation is server-side and deterministic: an answer citing a chunk absent from context is rejected.
- **S-13**: Structured logs (`app/observability.py`) redact API keys and raw queries.
- **S-15**: Parameterized SQL queries throughout `psycopg` database interactions.
- **S-18**: Database application role (`docscout_app`) is least-privilege: SELECT, INSERT, UPDATE on application tables; no DELETE, no DDL.
- **S-20**: Append-only retrieval audit log (`retrieval_audit_log`) records query hashes (SHA-256) and key fingerprints without storing raw queries or keys (ADR-0015).
- **S-21**: Ingestion secret and PII scanner (`app/ingest/scanner.py`) flags candidate secrets and PII with automatic sample masking.

### 4.3 Prompt injection: VERIFIED

- **S-7**: Delimiter discipline wrapping retrieved context in `<document>` tags.
- **S-8**: Graded canary defense: evaluated across 3 canary documents and gold-set items, demonstrating 100% defense.

### 4.4 Supply chain: VERIFIED

- **S-10**: Dependencies locked via `uv.lock`; installed via `uv sync --frozen`.
- **S-11**: Automated dependency vulnerability scanning via `pip-audit` and CycloneDX SBOM generation in CI (`make audit-deps`).
- **S-12**: MCP servers pinned by version in `.mcp.json` and audited in `docs/security/mcp-server-audit.md`.

### 4.5 Agent safety: VERIFIED

- **S-16**: Command denylist hook blocks destructive commands before execution, enforced by `check-shebang-scripts-are-executable` pre-commit hook.

---

## 5. Verification status summary

| Control area | Enforced | Evidence |
|---|---|---|
| Secret scanning | Yes | Gitleaks pre-commit and CI |
| Dependency pinning & SBOM | Yes | `uv.lock`, `make audit-deps`, `sbom.cdx.json` |
| Agent command denylist | Yes | `.claude/hooks/dangerous-bash.sh`, pre-commit hook |
| Ingestion credential isolation | Yes | `app/ingest/guards.py`, `tests/test_ingest.py` |
| API authentication and rate limit | Yes | `app/api/app.py`, `tests/test_api.py` |
| Prompt injection defense | Yes | `app/generate/prompt.py`, canary tests (100% defense) |
| Citation validation | Yes | `app/generate/answer.py`, `tests/test_api_answer.py` |
| Log redaction | Yes | `app/observability.py`, unit tests |
| Retrieval audit logging | Yes | `retrieval_audit_log` table, ADR-0015, `tests/test_audit_and_pii_scan.py` |
| Ingestion PII/secret scanning | Yes | `app/ingest/scanner.py`, `tests/test_audit_and_pii_scan.py` |
| Container security | Yes | Non-root `app` user, pinned digests in Dockerfile |
