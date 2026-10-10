# DocScout Operational Integrations Guide

This guide details the architecture, configuration, runtime behavior, quota governance, and verification procedures for DocScout's three core production integrations:
1. **Brevo Transactional Email Service (Sendinblue v3)**
2. **OCR.Space High-Value Regulatory Fallback**
3. **Auth0 OpenID Connect & OAuth 2.0 Identity Governance**
along with the **Evidence Foundation & Provenance Corrections** and **Live Regulatory Discovery Engine**.

---

## 1. System Architecture Overview

```
                                      +--------------------------+
                                      |     Auth0 Tenant / JWKS  |
                                      +-------------+------------+
                                                    | (RS256 JWT)
                                                    v
+-------------------------+            +------------+------------+            +--------------------------+
|  Analyst Web Console    | <--------> |   FastAPI App Backend   | ---------> |  Brevo API (Sendinblue)  |
|  (Interactive Dashboard)|            +------------+------------+            |  - Digest Dispatch       |
+-------------------------+                         |                         |  - RFC-8058 Unsubscribe  |
                                                    |                         |  - Webhook Callbacks     |
                                                    v                         +--------------------------+
                                      +-------------+------------+
                                      |   PostgreSQL 18 + Vector |
                                      |  - users / subscriptions |
                                      |  - digest_deliveries     |
                                      |  - ocr_extractions       |
                                      |  - documents / chunks    |
                                      +-------------+------------+
                                                    ^
                                                    | (Fallback Cache)
                                      +-------------+------------+
                                      |   OCR.Space API Engine   |
                                      |  - Bounded 1MB/3-page    |
                                      |  - SHA-256 Hash Cache    |
                                      +--------------------------+
```

---

## 2. Environment Configuration & Secret Management

All integration parameters are defined in `.env.example` and read securely via `app/config.py`. Under no circumstances are credentials exposed to client bundles or hardcoded in source.

### Key Configuration Variables

| Variable | Required | Default / Format | Description |
|---|---|---|---|
| `AUTH0_DOMAIN` | Yes (in prod) | `dev-docscout.us.auth0.com` | Auth0 tenant domain for JWKS discovery (`https://{domain}/.well-known/jwks.json`) |
| `AUTH0_AUDIENCE` | Yes (in prod) | `https://api.docscout.gov.in` | Auth0 API identifier (audience claim) |
| `AUTH0_CLIENT_ID` | Optional | Alphanumeric | Auth0 client application ID |
| `BREVO_API_KEY` | Yes (in prod) | `xkeysib-...` | Brevo v3 Transactional REST API Key |
| `BREVO_SENDER_EMAIL`| Yes | `compliance-alerts@docscout.gov.in` | Verified transactional sender email address |
| `BREVO_SENDER_NAME` | Yes | `DocScout Regulatory Alerts` | Sender display name in email clients |
| `BREVO_WEBHOOK_SECRET` | Optional | Random 32+ hex | Secret key to verify HMAC on inbound Brevo webhook callbacks |
| `OCR_SPACE_API_KEY` | Yes (in prod) | Alphanumeric | OCR.Space Free/Pro Tier API Key |
| `OCR_SPACE_ENGINE` | Optional | `2` | OCR engine (`1` for standard, `2` for advanced multilingual) |
| `DATABASE_URL` | Yes | `postgresql://...:5433/docscout` | Application role database connection string |
| `MIGRATION_DATABASE_URL`| Yes | `postgresql://...:5433/docscout`| Owner role database connection string for DDL |

### Key Rotation & Fallback Protocols
- **Auth0 Key Rotation:** The `Auth0TokenVerifier` employs `jwt.PyJWKClient` with an LRU key cache. When Auth0 rotates signing keys in JWKS, the client automatically re-fetches the JWKS keys without application downtime.
- **Development Fallback Mode:** When `AUTH0_DOMAIN` is omitted or unset, the system defaults to a deterministic local analyst persona (`dev-local-analyst`), allowing rapid local feature development and offline testing without external internet dependencies.

---

## 3. Free-Tier Quota & Boundary Governance

DocScout is designed to operate safely within free-tier API quotas with zero unexpected overages:

### 1. Brevo Transactional Email
- **Daily Quota Ceiling:** 300 emails per UTC calendar day.
- **Quota Tracking:** `app/digests/engine.py` maintains an atomic daily delivery counter in memory and cross-verifies against `digest_deliveries` in PostgreSQL.
- **Threshold Warnings:**
  - **$\ge$ 80% (240 emails):** Emits structured warning logs (`logger.warning("brevo.quota.near_limit")`).
  - **100% (300 emails):** Refuses non-urgent dispatches, returning `QuotaExceededError`.
- **Deduplication:** The PostgreSQL database enforces a strict unique constraint:
  ```sql
  CONSTRAINT uq_digest_delivery_version UNIQUE (subscription_id, document_id, version_id)
  ```
  If a digest dispatch pass is rerun or restarted, previously delivered circular versions are immediately skipped, preventing redundant email dispatches.

### 2. OCR.Space Regulatory Fallback
- **Free-Tier Limits:**
  - Maximum File Size: **1,024 KB (1 MB)**.
  - Maximum Page Count: **3 pages**.
  - Daily Request Limit: **500 requests per day**.
- **Pre-Flight Eligibility Checks:**
  - Before sending any bytes over the network, `evaluate_ocr_eligibility` evaluates document size and PDF page count.
  - If a scanned circular exceeds 1 MB or 3 pages, it is refused with `OCREligibilityError` rather than silently truncated. Silent truncation in regulatory compliance is fatal.
- **Persistent Database Cache (`ocr_extractions`):**
  - All OCR results are permanently cached by SHA-256 hash in PostgreSQL.
  - Subsequent ingestion passes for identical files execute in **0 ms** with **0 external API calls**.

---

## 4. Subsystem Implementations

### A. Auth0 Authentication & RBAC (`app/api/auth0.py`)
- **RS256 Signature Verification:** Tokens passed via `Authorization: Bearer <token>` are verified using the tenant's public keys.
- **User Identity Synchronization:** `sync_user_in_db` provisions the analyst in `users` upon their first authenticated request, mapping `sub` to `user_id`.
- **Role-Based Authorization:**
  - `require_authenticated_user`: Grants `reader` privileges (search, interests, digests).
  - `require_admin_user`: Requires `docscout:admin` scope or `https://docscout.gov.in/roles` including `admin` (crawler runs, cache purges).

### B. Brevo Digests & Unsubscribe (`app/digests/`)
- **Supported Regulatory Topics:**
  - `digital_lending`, `kyc_aml`, `cyber_resilience`, `nbfc_scale_based`, `priority_sector`, `compromise_settlement`, `green_finance`, `it_outsourcing`.
- **Grounded Delivery Content:**
  - Every digest item includes the authoritative regulator URL (`rbi.org.in` or `sebi.gov.in`), title, issuance date, and exact statutory provisions extracted from the document.
  - Synthetic documents are strictly excluded.
- **RFC-8058 One-Click Unsubscribe:**
  - Unsubscribe URLs contain an HMAC-SHA256 signature (`app/digests/brevo_client.py:generate_unsubscribe_token`).
  - Analysts can unsubscribe with one click without logging in.

### C. Live Regulatory Discovery Engine (`app/ingest/discovery.py`)
- Crawls live indexes from the RBI and SEBI official portals.
- Compares hashes against known versions in PostgreSQL.
- Categorizes updates into `NEW_DOCUMENT`, `CONTENT_REVISION`, or `UNCHANGED`.

### D. Evidence Foundation Corrections
- **Synthetic Separation:** 14 synthetic circulars generated in offline testing are classified as `is_synthetic = true`.
- **Default Exclusion:** All production search and retrieval queries filter out synthetic documents (`WHERE NOT d.is_synthetic`) unless explicitly overridden in eval test modes.
- **Judge Calibration:** Clarified as a synthetic distribution diagnostic test harness.

---

## 5. Verification & Test Suite

The integration suite contains comprehensive automated tests covering all integration contracts:

```bash
# Run all integration tests
.venv\Scripts\pytest.exe tests/test_auth0.py tests/test_ocr_space.py tests/test_digests_brevo.py tests/test_discovery.py -v
```

### Test Verification Summary
- `tests/test_auth0.py`: 6 passed (JWKS verification, invalid tokens, role authorization, DB sync).
- `tests/test_ocr_space.py`: 7 passed (Pre-flight limits, DB hash caching, fallback extraction).
- `tests/test_digests_brevo.py`: 6 passed (Subscriptions, HMAC unsubscribe, grounded digests, quota limit).
- `tests/test_discovery.py`: 4 passed (RBI & SEBI index parsing, classification logic).
- `tests/test_goldset.py`: 23 passed (Gold set validation and citation resolution).
- Total integration test runtime: < 15 seconds.

---

## 6. Incident Response & Troubleshooting

1. **Brevo Delivery Failures / HTTP 401/403:**
   - Verify `BREVO_API_KEY` validity in Brevo Dashboard.
   - Verify `BREVO_SENDER_EMAIL` is an authorized sender domain in Brevo.
2. **Brevo Daily Quota Hit (300/300):**
   - The engine logs a warning and queues non-critical alerts until 00:00 UTC.
   - For urgent high-priority alerts, upgrade the Brevo plan or register an additional sender IP.
3. **Scanned PDF Rejection (`OCREligibilityError`):**
   - Confirm file size is $\le$ 1 MB and page count $\le$ 3 pages.
   - For multi-page circulars, split into individual scanned annexures or process via local high-capacity OCR tools.
4. **Auth0 JWT Verification Fails (`401 Unauthorized`):**
   - Verify client token `iss` matches `https://{AUTH0_DOMAIN}/` and `aud` matches `AUTH0_AUDIENCE`.
   - In local offline dev environments, remove `AUTH0_DOMAIN` from `.env` to enable the dev-local bypass.
