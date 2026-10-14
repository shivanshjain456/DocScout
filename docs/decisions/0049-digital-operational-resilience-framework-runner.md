# ADR-0049: Digital Operational Resilience (DORA) Framework Runner (FEAT-058)

## Status
Accepted

## Context
Financial entities operating in the European Union and internationally under converging regulatory standards (including the EU Digital Operational Resilience Act - Regulation (EU) 2022/2554, and Reserve Bank of India Master Directions on Cyber Resilience) must demonstrate comprehensive ICT operational resilience. Unlike fragmented point-in-time security audits, DORA establishes a unified, legally binding framework across five distinct operational pillars:

1. ICT Risk Management (Articles 5-16)
2. ICT-Related Incident Management, Classification and Reporting (Articles 17-23)
3. Digital Operational Resilience Testing (Articles 24-27, including Threat-Led Penetration Testing / TLPT)
4. Managing of ICT Third-Party Risk (Articles 28-44, including Critical ICT Third-Party Providers / CTPPs)
5. Information-Sharing Arrangements (Article 45)

DocScout requires an automated DORA Framework Runner operationalizing `playbook.resilience`. The engine must ingest ICT system architecture profiles, evaluate compliance across all five statutory pillars, verify Threat-Led Penetration Testing (TLPT/TIBER-EU) cadences, track critical third-party dependencies and exit strategies, enforce strict evidence gating, and persist resilience test records with multi-tenant isolation.

## Decision
1. **Database Schema (`migrations/0043_dora_framework.up.sql`)**:
   - Create `dora_systems` table: `system_id` (VARCHAR PK), `tenant_id` (VARCHAR), `name` (VARCHAR), `criticality` (VARCHAR: CRITICAL, HIGH, MEDIUM, LOW), `is_third_party` (BOOLEAN), `third_party_provider` (VARCHAR), `is_critical_third_party` (BOOLEAN), `has_exit_strategy` (BOOLEAN), `last_tlpt_date` (DATE), `rto_minutes` (INT), `rpo_minutes` (INT), `metadata` (JSONB), and `created_at` (TIMESTAMPTZ).
   - Create `resilience_tests` table: `test_id` (UUID PK), `tenant_id` (VARCHAR), `system_id` (VARCHAR FK), `test_type` (VARCHAR), `executed_at` (TIMESTAMPTZ), `passed` (BOOLEAN), `evidence_hash` (VARCHAR), `findings` (JSONB), and `created_at` (TIMESTAMPTZ).
   - Multi-tenant Row-Level Security (RLS) policies scoped by `tenant_id`.
   - Indexes on `(tenant_id, criticality)` and `(tenant_id, executed_at)`.
   - Permissions granted to `docscout_app`.

2. **DORA Engine (`app/compliance/dora_runner.py`)**:
   - `DORAConfig`: Policy configuration (`strict_critical_ict_third_party_rules: bool = True`, `max_tlpt_interval_years: int = 3`, `max_critical_rto_minutes: int = 240`).
   - Pillar 1 (ICT Risk Management): Evaluates system inventory, criticality categorization, governance frameworks, and RTO/RPO boundaries.
   - Pillar 2 (Incident Reporting): Validates major incident management protocols and statutory notification readiness.
   - Pillar 3 (Digital Operational Resilience Testing): Evaluates regular testing schedules and enforces mandatory TLPT/TIBER-EU every 3 years for all critical systems.
   - Pillar 4 (ICT Third-Party Risk): Enforces contractual exit strategies and concentration risk controls for Critical Third-Party Providers (CTPPs).
   - Pillar 5 (Information Sharing): Evaluates threat intelligence and cyber indicator exchange agreements.
   - Zero False Claims Guarantee: Compliance scores require verified empirical test records and structural controls; unverified claims are rejected.
   - Assessment latency bounded to p95 <= 15.0 ms with memory footprint <= 8 MB.

3. **REST API Extensions (`app/api/app.py`)**:
   - `POST /v1/compliance/dora/assess`: Evaluates enterprise ICT systems against DORA Pillars 1-5 and returns comprehensive compliance reports with gap analyses.
   - `GET /v1/compliance/dora/report`: Retrieves latest institutional DORA readiness scorecard for the authenticated tenant.
   - `POST /v1/compliance/dora/tests/record`: Logs verified operational resilience test executions and updates audit records.

4. **Observability (`app/api/metrics.py`)**:
   - Counter `docscout_dora_assessments_completed_total{tenant_id}`: Total resilience assessments executed.
   - Counter `docscout_resilience_tests_recorded_total{status}`: Total resilience stress tests logged.

5. **Console UI Component (`ui/src/components/DORAConsole.tsx`)**:
   - Interactive dashboard presenting overall readiness gauges, 5-pillar scorecards, critical gap alerts, third-party risk matrices, and TLPT schedule timelines.

## Consequences
- Provides full operational coverage across all 5 statutory pillars of EU DORA Regulation 2022/2554.
- Prevents compliance blind spots by strictly requiring verified test evidence for critical infrastructure.
- High-performance evaluation (<= 15.0 ms) allows continuous CI/CD gating and real-time posture tracking.
