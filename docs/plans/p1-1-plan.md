# Plan: P1-1 — Durable Retrieval Audit Log + Corpus Secret/PII Scan

## Context and Problem Statement
- **Audit Findings G12 & G13 (OWASP LLM09 & LLM02)**:
  - **G12 (Retrieval Audit Log)**: Query events are currently logged only as ephemeral stdout log lines. There is no durable, tamper-resistant, append-only record of retrieval events (timestamp, key fingerprint, query hash, mode, returned chunk IDs, latency). Without this, forensic questions ("what was retrieved for whom?") are unanswerable.
  - **G13 (Corpus Secret/PII Scan)**: `gitleaks` only scans repository source code and commit history. It does not scan ingested regulatory text, which is parsed from PDFs and web documents and could carry incidental API keys, credentials, or PII (emails, phone numbers, PAN/Aadhaar) into chunks and downstream responses.
- **Goal**:
  1. Implement an append-only, durable retrieval audit log with documented retention window, zero raw API keys (key fingerprint only), and query privacy (query text hashed via SHA-256 by default).
  2. Implement an ingestion-time secret and PII scanner for extracted corpus text that flags candidate secrets and PII, records findings in the ingest report, and adheres to a documented policy (quarantine/warn on secrets without blocking on PII false positives).
  3. Create migration `0004_retrieval_audit_log.up.sql` granting `docscout_app` `INSERT` and `SELECT` but strictly denying `DELETE`/`TRUNCATE` (least-privilege append-only guarantee).
  4. Write comprehensive integration tests in `tests/test_audit_and_pii_scan.py` and schema tests in `tests/test_schema.py`.
  5. Author ADR-0015 documenting the architectural choices, security boundaries, and retention policy.

---

## Architecture & Design

### 1. Retrieval Audit Log (`retrieval_audit_log`)
- **Schema (Migration 0004)**:
  - `id`: `bigserial PRIMARY KEY`
  - `timestamp`: `timestamptz NOT NULL DEFAULT now()`
  - `key_fingerprint`: `varchar(16) NOT NULL` (first 12 chars of SHA-256 of API key)
  - `query_hash`: `char(64) NOT NULL` (SHA-256 hex of query)
  - `mode`: `text NOT NULL` ('hybrid', 'dense', 'bm25')
  - `k`: `integer NOT NULL` (limit)
  - `returned_chunk_ids`: `uuid[] NOT NULL` (ordered array of chunk UUIDs)
  - `latency_ms`: `numeric(10, 2) NOT NULL`
  - `cache_hit`: `boolean NOT NULL DEFAULT false`
  - `has_generated_answer`: `boolean NOT NULL DEFAULT false`
  - `corpus_generation`: `integer NOT NULL DEFAULT 1`
  - Constraints:
    - Check on `query_hash ~ '^[0-9a-f]{64}$'`
    - Check on `mode IN ('hybrid', 'dense', 'bm25')`
    - Check on `k > 0 AND k <= 100`
    - Check on `latency_ms >= 0`
  - Indexing:
    - `CREATE INDEX idx_retrieval_audit_timestamp ON retrieval_audit_log (timestamp DESC)`
    - `CREATE INDEX idx_retrieval_audit_key_fp ON retrieval_audit_log (key_fingerprint, timestamp DESC)`
  - Permissions:
    - `GRANT SELECT, INSERT ON retrieval_audit_log TO docscout_app;`
    - **NO DELETE, NO TRUNCATE** to `docscout_app` (guarantees append-only retention).
- **Module `app/api/audit.py`**:
  - `RetrievalAuditRecord` dataclass.
  - `record_retrieval_audit()` helper:
    - Inserts into `retrieval_audit_log` via connection pool.
    - Also optionally appends to JSONL file sink (`DOCSCOUT_AUDIT_LOG_FILE`).
    - Catches exceptions and logs warnings so audit logging failures never break search serving.
    - Query text is strictly hashed: `hashlib.sha256(query.strip().encode("utf-8")).hexdigest()`.
    - Key is strictly fingerprinted: `fingerprint` (12 hex characters).
  - Configurable retention:
    - `DOCSCOUT_AUDIT_RETENTION_DAYS` (default: 90 days). Documented in ADR-0015.

### 2. Corpus Secret & PII Scanner (`app/ingest/scanner.py`)
- **Detection Rules**:
  - **Secrets**:
    - High-entropy API keys (AWS `AKIA...`, OpenAI `sk-...`, GitHub `ghp_...`, generic token patterns).
    - Private key headers (PEM format private keys).
    - Password / credential assignments (`password = ...`, `secret = ...`).
  - **PII**:
    - Email addresses (`[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+`).
    - Phone numbers (Indian/international formats).
    - Indian Financial / Tax IDs:
      - PAN (`[A-Z]{5}[0-9]{4}[A-Z]`).
      - Aadhaar (`\d{4}\s\d{4}\s\d{4}`).
- **Data Model**:
  - `ScanFinding`:
    - `category`: `"secret"` | `"pii"`
    - `rule_id`: str
    - `description`: str
    - `char_start`: int
    - `char_end`: int
    - `sample_redacted`: str (masked representation)
    - `severity`: `"critical"` | `"high"` | `"medium"` | `"low"`
- **Ingestion Policy**:
  - Configurable via `DOCSCOUT_CORPUS_SECRET_POLICY`: `"warn"`, `"quarantine"`, or `"fail"` (default: `"warn"` or `"quarantine"`).
  - PII findings are recorded as informational warnings and NEVER block ingestion (public regulatory circulars legitimately contain contact emails and phone numbers).
  - Secret findings are tracked in `DocumentResult.secret_findings` and `IngestReport.totals["total_secret_findings"]`.
  - In `pipeline.py`: if `secret_findings` exist and policy is `"quarantine"`, document is quarantined rather than written to DB.
  - Canaries: `canary-001-synthetic.txt` or dedicated test canaries with synthetic secrets are caught and reported.

---

## Implementation Steps
1. **Migrations**:
   - Create `migrations/0004_retrieval_audit_log.up.sql` and `migrations/0004_retrieval_audit_log.down.sql`.
   - Run `uv run python scripts/migrate.py up`.
2. **Scanner & Audit Modules**:
   - Create `app/ingest/scanner.py`.
   - Create `app/api/audit.py`.
3. **Integrate Ingestion Scanner**:
   - Update `app/ingest/pipeline.py` and `app/ingest/store.py` to run scanner and record `secret_findings` and `pii_findings` in `DocumentResult` and `IngestReport`.
4. **Integrate Retrieval Audit Logging**:
   - Update `app/api/app.py` in `search()` to invoke `record_retrieval_audit()` with `key_fingerprint`, `query_hash`, `mode`, `chunk_ids`, `latency_ms`.
   - Update `app/api/metrics.py` with `docscout_retrieval_audits_total`.
5. **Testing**:
   - Add schema tests to `tests/test_schema.py` for migration 0004 (table constraints, append-only permissions, rejection of delete).
   - Create `tests/test_audit_and_pii_scan.py` testing:
     - Audit log insertion on search.
     - Query privacy: query hash stored, raw query NOT stored.
     - Key privacy: key fingerprint stored, raw key NOT stored.
     - Least-privilege append-only: application role cannot delete audit rows.
     - Scanner correctly catches secrets, PII (emails, phones, PAN), and masks samples.
     - Synthetic canary secret correctly flagged in ingest report.
     - Gitleaks distinction: repo scanning vs corpus text scanning.
6. **Documentation**:
   - Author ADR-0015 at `docs/decisions/0015-retrieval-audit-log-and-corpus-pii-scan.md`.
   - Update `docs/plans/master-todo.md` and `README.md`.
7. **Verification Gates**:
   - Run `ruff`, `mypy`, `pytest`, `gate`.
   - Atomically commit and push to `origin/master`.
