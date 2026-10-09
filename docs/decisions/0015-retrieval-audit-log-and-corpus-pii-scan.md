# ADR-0015: Durable Retrieval Audit Log and Ingestion-Time Secret/PII Scanning

- **Status:** accepted
- **Date:** 2026-10-09
- **Deciders:** DocScout Principal Engineer
- **Related:** ADR-0004 (Postgres persistence & least-privilege roles), ADR-0008 (serving API), ADR-0014 (cache invalidation & generation tagging)
- **Evidence:** `migrations/0004_retrieval_audit_log.up.sql`, `app/api/audit.py`, `app/ingest/scanner.py`, `app/ingest/pipeline.py`, `app/api/app.py`, `app/api/metrics.py`, `tests/test_audit_and_pii_scan.py`, `tests/test_schema.py`

---

## 1. Context

DocScout is an operational RAG service retrieving over regulatory circulars from the Reserve Bank of India (RBI) and Securities and Exchange Board of India (SEBI).

Prior to this decision, two security and compliance deficiencies existed (identified in `AUDIT-2026-10-02.md` as G12 and G13):

1. **G12: Absence of a Durable Retrieval Audit Log (OWASP LLM09)**:
   - Queries were logged only as ephemeral stdout lines via an in-process logger.
   - Once process log buffers rolled over or container instances terminated, there was zero durable record of retrieval events.
   - Forensic questions ("what documents were retrieved for which API key?", "did a compromised client attempt data exfiltration or systematic index probing?", "what was the query volume and latency profile over time?") could not be answered with non-repudiation.
2. **G13: Absence of Ingestion-Time Secret/PII Scanning in Corpus Text (OWASP LLM02)**:
   - `gitleaks` strictly scans git repository commits and tracked files in version control.
   - It did NOT scan ingested regulatory text extracted from external PDFs or HTML pages. Regulatory text scraped from the public web could carry incidental internal API keys, database credentials, or Personally Identifiable Information (personal emails, mobile numbers, PAN, Aadhaar) directly into chunk embeddings and downstream answers.

---

## 2. Decision

### 2.1 Append-Only Durable Retrieval Audit Log (`retrieval_audit_log`)
1. **Schema Design (Migration 0004)**:
   - Table `retrieval_audit_log`:
     - `id`: `bigserial PRIMARY KEY`
     - `timestamp`: `timestamptz NOT NULL DEFAULT now()`
     - `key_fingerprint`: `varchar(16) NOT NULL` (12 hex chars derived from `hashlib.sha256(api_key).hexdigest()[:12]`)
     - `query_hash`: `char(64) NOT NULL` (`hashlib.sha256(query.strip().encode()).hexdigest()`)
     - `mode`: `text NOT NULL` ('hybrid' | 'dense' | 'bm25')
     - `k`: `integer NOT NULL`
     - `returned_chunk_ids`: `uuid[] NOT NULL DEFAULT '{}'` (ordered list of chunk UUIDs served)
     - `latency_ms`: `numeric(10, 2) NOT NULL`
     - `cache_hit`: `boolean NOT NULL DEFAULT false`
     - `has_generated_answer`: `boolean NOT NULL DEFAULT false`
     - `corpus_generation`: `integer NOT NULL DEFAULT 1`
2. **Privacy by Default**:
   - Query text is hashed via SHA-256 before insertion. Plaintext query strings are **never stored** in the database by default, safeguarding confidential queries and incidental PII while enabling exact query forensics and repetition detection.
   - API keys are **never stored**; only non-reversible truncated fingerprints (`key_fingerprint`) are recorded.
3. **Least-Privilege Append-Only Guarantee**:
   - `docscout_app` is granted `SELECT` and `INSERT` on `retrieval_audit_log`.
   - `docscout_app` is strictly **DENIED `UPDATE`, `DELETE`, and `TRUNCATE`**. Even if the web application process is compromised, historical audit records cannot be rewritten, truncated, or tampered with.
4. **Resilience & Fallback Sink**:
   - In `app/api/app.py`, audit insertion is wrapped in resilience boundaries. Transient database connection issues never abort or crash user queries.
   - If `DOCSCOUT_AUDIT_LOG_FILE` is configured, records are simultaneously appended to a local JSONL file sink.
   - Metrics counter `docscout_retrieval_audits_total{status="ok"|"error"}` tracks audit ingestion health.
5. **Retention Policy**:
   - Standard audit retention policy is set to **90 days** (`DEFAULT_AUDIT_RETENTION_DAYS`). Periodic pruning is executed via maintenance jobs using table owner credentials (`docscout_owner`), preventing the application role from acquiring delete permissions.

---

### 2.2 Ingestion-Time Secret and PII Scanning (`app/ingest/scanner.py`)
1. **Pattern Detection (OWASP LLM02)**:
   - Implemented high-precision regex detectors for:
     - **Secrets**: AWS access keys (`AKIA...`), Private Keys (`BEGIN RSA/EC PRIVATE KEY`), GitHub PATs/tokens (`ghp_...`, `github_pat_...`), SaaS API keys (`sk-...`), credential assignments (`api_key = ...`, `password = ...`), and synthetic canary tokens (`SYNTH-SECRET-...`, `CANARY-SECRET-...`).
     - **PII**: Email addresses, Indian mobile/landline phone numbers (`+91...`, `022...`), Indian Permanent Account Numbers (PAN: `[A-Z]{5}[0-9]{4}[A-Z]`), and Aadhaar numbers (`\d{4} \d{4} \d{4}`).
2. **Sample Masking by Default**:
   - Detected candidate secrets and PII are masked immediately in memory (`mask_sample()`). Masked samples (e.g., `AKIA********MPLE`, `n***@bank.co.in`, `AB***4F`) are recorded in findings; raw strings are never emitted into `IngestReport` or logs.
3. **Policy Separation: Secrets vs PII**:
   - **PII False-Positive Protection**: Public regulatory circulars frequently contain departmental contact addresses (`helpdesk@rbi.org.in`, `022-22601000`). PII findings are logged as informational warnings and **never block or quarantine ingestion**.
   - **Secret Policy Enforcement**: Ingestion evaluates `DOCSCOUT_CORPUS_SECRET_POLICY` (`warn`, `quarantine`, `fail`):
     - `quarantine` (or `fail`): Documents with candidate secret findings are quarantined immediately (`Action.QUARANTINED`, `chunks = 0`), preventing unvetted credentials from entering chunk storage and embeddings.
     - `warn`: Records findings in `DocumentResult.secret_findings` and `IngestReport.totals["total_secret_findings"]`.
4. **Disjoint Responsibilities**:
   - Git repository security remains guarded by `gitleaks` (pre-commit hook and CI action).
   - Ingested text security is guarded at runtime by `app.ingest.scanner`.

---

## 3. Consequences

### Positive
- **Forensic Non-Repudiation**: Operators can inspect `retrieval_audit_log` to reconstruct exactly which chunks were served to which API key fingerprint at any point in time.
- **Query Privacy Guaranteed**: Plaintext queries are never stored in the database, preventing query surveillance while preserving forensic joinability via `query_hash`.
- **Tamper-Resistant Storage**: Enforced by Postgres permissions — `docscout_app` cannot modify or delete past audit entries.
- **Corpus Leak Prevention**: Extracted text containing accidental credentials or API keys is caught prior to chunking and vector storage.
- **Zero Ingestion Outages from PII**: Legitimate circular contact emails/phones do not halt ingestion runs.

### Negative / Trade-offs
- Each `/v1/search` and cache hit incurs one fast SQL INSERT (`< 1 ms`) into `retrieval_audit_log`.
- `retrieval_audit_log` accumulates rows over time (~80 bytes/row), requiring periodic retention pruning after 90 days.
