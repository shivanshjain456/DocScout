# ADR-0024: Brevo Transactional Email, OCR.Space Fallback, Auth0 Identity, and Synthetic Provenance Governance

- **Status:** accepted
- **Date:** 2026-10-10
- **Deciders:** Principal Engineer & Technical Lead
- **Related:** ADR-0004 (persistence schema), ADR-0008 (serve evidence not answers), ADR-0013 (scheduled corpus refresh), ADR-0015 (retrieval audit log), ADR-0020 (knowledge graph provisions), ADR-0022 (pluggable extraction chain)

---

## Context

DocScout serves compliance officers, risk managers, and legal analysts navigating complex Indian regulatory environments governed by the Reserve Bank of India (RBI) and Securities and Exchange Board of India (SEBI). To transition DocScout from an internal retrieval prototype into an enterprise-ready regulatory intelligence platform, three core external integrations were required:

1. **Transactional Notification Channel:** Regulatory updates demand push delivery. Analysts cannot poll search dashboards constantly; they require tailored email notifications and periodic regulatory digests reflecting their specific research watchlists.
2. **Optical Character Recognition (OCR) Fallback:** Indian regulatory bodies frequently publish scanned gazettes, notifications, or circulars that contain image-only pages or corrupted embedded fonts. Standard text extraction pipelines (`pypdf`, `pdfplumber`) fail on such scans, causing critical regulatory omissions unless a bounded OCR fallback is available.
3. **Enterprise Identity & Role Separation:** Research interests, customized alert subscriptions, and administrative crawler controls require verified cryptographic identities, role-based access control (`reader` vs `admin`), and strict multi-tenant boundaries.

Furthermore, an internal audit revealed that 14 regulatory circulars in the evaluation set were generated via synthetic scripts (`scripts/experiments/generate_p0_3_corpus.py`) without runtime separation from authoritative regulator-issued texts, and the LLM calibration harness (`scripts/calibrate_judge.py`) relied on simulated judgment distributions without clear diagnostic disclosure.

---

## Decision

We introduce three production-grade integration subsystems alongside strict evidence provenance corrections:

### 1. Brevo Transactional Email Service (Sendinblue v3)

- **Subscription & Watchlist Data Model (`migrations/0009`):**
  - Analysts subscribe to specific regulatory topics (`digital_lending`, `kyc_aml`, `cyber_resilience`, `nbfc_scale_based`, `priority_sector`, `compromise_settlement`, `green_finance`, `it_outsourcing`).
  - Supported delivery frequencies: `realtime`, `daily`, `weekly`.
  - Double consent tracking via `consent_ts` and IP origin logging.
  - Cryptographic tamper-proof unsubscribe tokens (`HMAC-SHA256(secret, subscription_id:user_id)`) enabling RFC-8058 one-click unsubscription.
- **Delivery Engine & Quota Governance (`app/digests/`):**
  - Grounded digest formatting with mandatory regulator source verification: every digest item must cite an authoritative regulator URL (`rbi.org.in` or `sebi.gov.in`) and extract specific statutory provisions. Synthetic documents are hard-excluded.
  - Restart-safe deduplicated delivery logging using unique constraint `uq_digest_delivery_version(subscription_id, document_id, version_id)`.
  - Brevo Free-Tier Governance: Tracks daily send volumes against the 300 emails/day ceiling. Warns at 80% capacity and blocks non-critical dispatches at 100%.
  - Inbound webhook processing (`app/digests/webhook.py`): Handles Brevo callbacks (`delivered`, `opened`, `clicks`, `bounce`, `spam`) with signature verification and updates delivery state machines.

### 2. OCR.Space Regulatory Fallback Engine

- **Bounded Fallback Pipeline (`app/ingest/ocr_space.py` & `app/ingest/extract_chain.py`):**
  - Integrated as Stage 3 in the pluggable extraction chain (following `pypdf` and `pdfplumber`).
  - Strict Free-Tier Pre-Flight Eligibility:
    - Payload size $\le$ 1,024 KB (1 MB).
    - Page count $\le$ 3 pages.
    - Rate quota $\le$ 500 requests/day.
    - If a document exceeds these limits, the extractor refuses execution with `OCREligibilityError` rather than silently truncating regulatory content.
  - Persistent Hash-Indexed Database Cache (`ocr_extractions`):
    - Indexed by `sha256` of document bytes.
    - Redundant OCR calls for identical circular versions are completely eliminated (0 ms latency, 0 external API calls on subsequent runs).
  - Provenance & Evidence Traceability:
    - Extractions record exact parsed text, OCR processing time, engine version, and line-level confidence metadata.

### 3. Auth0 OpenID Connect & OAuth 2.0 Identity

- **Cryptographic Token Verification (`app/api/auth0.py`):**
  - Verifies RS256 JWT tokens using Auth0 JSON Web Key Sets (JWKS).
  - Employs cached `PyJWKClient` with automatic key rotation handling and 1-hour in-memory caching.
  - Validates `iss` (Auth0 domain) and `aud` (DocScout API Identifier).
- **Identity Derivation & Role Enforcement:**
  - Derives user identity strictly from token `sub` (e.g. `auth0|...`, `google-oauth2|...`).
  - Automatically provisions and synchronizes analyst profiles in the `users` table upon initial authenticated request.
  - Role-Based Access Control:
    - `reader`: Read-only queries, research workspace generation, interest management, digest subscriptions.
    - `admin`: Requires `docscout:admin` scope or custom claim `https://docscout.gov.in/roles` containing `admin`. Protects crawler execution, cache invalidation, and system configuration.
  - Local Dev Fallback: When `AUTH0_DOMAIN` is unconfigured, falls back to a deterministic development persona (`dev-local-analyst`) with explicit warning headers, ensuring zero blockers during offline development.

### 4. Evidence Foundation Corrections & Live Regulatory Discovery

- **Synthetic Artifact Segregation (`migrations/0010` & `manifest.json`):**
  - Added `documents.is_synthetic` flag and `provenance_class`.
  - Formally classified documents 21–34 (`NOTI280` through `1788600678901`) and document 0 (canary) as `SYNTHETIC_EVAL_FIXTURE`.
  - All production retrieval queries (`app/retrieval/dense.py`, `app/retrieval/lexical.py`) enforce `WHERE NOT d.is_synthetic` by default.
- **Judge Calibration Diagnostic Disclosure (`scripts/calibrate_judge.py`):**
  - Clearly documented and designated as a simulated synthetic distribution fixture harness for test pipelines, ensuring no ungrounded claims of production human inter-rater reliability.
- **Live Regulatory Discovery Engine (`app/ingest/discovery.py`):**
  - Real-time crawler monitoring RBI Notifications (`rbi.org.in/Scripts/BS_CircularIndexDisplay.aspx`) and SEBI Legal Framework Circulars (`sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&smid=0&ssid=7`).
  - Classifies newly discovered items into `NEW_DOCUMENT`, `CONTENT_REVISION`, or `UNCHANGED` based on content hashing and canonical URL matching.
  - Emits structured discovery manifests with full provenance metadata.

---

## Consequences

### Positive
- **Complete End-to-End User Experience:** Analysts can log in, select topics of interest, subscribe to grounded email digests, preview OCR extractions, and inspect live regulatory circular discovery directly from the interactive frontend console.
- **Production Resilience & Cost Control:** Bounded pre-flight limits, daily quota tracking, and persistent hashing ensure DocScout never incurs unexpected SaaS billing or rate exhaustion on Brevo or OCR.Space free tiers.
- **Regulatory Integrity:** Zero synthetic fixtures can contaminate production search results or analyst digests. Every citation traces back to verified regulatory gazettes.

### Negative / Trade-Offs
- Large scanned PDFs (>3 pages or >1 MB) cannot be processed via free-tier OCR.Space and require operator notification or local OCR fallbacks.
- Token verification requires outbound network connectivity to Auth0 JWKS endpoint upon initial key fetch (mitigated by key caching).
