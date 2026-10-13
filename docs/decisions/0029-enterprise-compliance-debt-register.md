# ADR-0029: Enterprise Compliance Debt Register (FEAT-038)

- **Status:** accepted
- **Date:** 2026-10-13
- **Deciders:** DocScout Engineering Team
- **Related:** FEAT-038, `pillar-04-regulatory-conflicts.md`, `app/compliance/debt_register.py`, `ui/src/components/DebtRegisterView.tsx`

## Context

Financial institutions frequently accumulate regulatory and engineering non-compliance exceptions (such as deferred cryptographic deprecations, unhedged operational practices, or grandfathering sunset windows) that are managed informally in spreadsheets or Jira tickets. Without a formal, auditable statutory debt register linked to circular antipatterns and deprecations, institutions fail regulatory audits and lose visibility into compound compliance exposure.

Key constraints:
- PostgreSQL persistence with Row-Level Security (RLS) for multi-tenant isolation by `tenant_id`.
- Strict input validation: valid `owner_email`, future `target_date`, minimum 20-character `justification`.
- Linked entities: optional foreign association to `statutory_deprecations` (FEAT-031) and `antipattern_registry` (FEAT-033).
- Full lifecycle status state machine: `OPEN` -> `IN_REMEDIATION` -> `RESOLVED`.
- Observability: Prometheus Gauge `docscout_open_compliance_debt_items{tenant_id, severity}`.
- CRUD latency budget: p95 $\le 10.0\text{ ms}$.

## Decision

We will implement:
1. Migration `migrations/0028_compliance_debt.up.sql` and `migrations/0028_compliance_debt.down.sql`:
   - Table `compliance_debt_register` with UUID primary key, `tenant_id`, `practice_name`, `severity`, `status`, `target_date`, `owner_email`, `justification`, `deprecation_id`, `antipattern_id`, `created_at`, `updated_at`.
   - Table `compliance_debt_audit_log` recording every state transition, actor, and timestamp.
   - Row-Level Security (RLS) enabled on `compliance_debt_register` conditioned on `current_setting('app.current_tenant_id', true)`.
2. Python backend `app/compliance/debt_register.py`:
   - Pydantic models: `CreateDebtItemRequest`, `UpdateDebtStatusRequest`, `ComplianceDebtItem`, `InstitutionalDebtScoreResponse`, `DebtRegisterConfig`.
   - `ComplianceDebtRegister`: thread-safe in-memory and database-backed repository supporting tenant-isolated CRUD, lifecycle transitions, audit logging, and institutional debt scoring.
   - API endpoints under `/v1/compliance/debt`:
     - `POST /v1/compliance/debt` (Create)
     - `GET /v1/compliance/debt` (List by tenant, status, severity)
     - `GET /v1/compliance/debt/{item_id}` (Retrieve item)
     - `PATCH /v1/compliance/debt/{item_id}/status` (Update status / lifecycle transition)
     - `GET /v1/compliance/debt/metrics/score` (Institutional debt score & breakdown)
3. Prometheus metrics in `app/api/metrics.py`:
   - `OPEN_COMPLIANCE_DEBT_ITEMS`: Gauge with labels `("tenant_id", "severity")`.
4. Frontend UI component:
   - `ui/src/components/DebtRegisterView.tsx` providing an enterprise dashboard with debt scorecards, status filters, item creation modals, and lifecycle transition controls.

## Consequences

- What becomes easier: Auditing compliance debt, proving remediation roadmaps to statutory inspectors (RBI/SEBI), and isolating tenant debt portfolios.
- What becomes harder: Enforcing strict tenant context across all database sessions.
- Cost and performance: Queries execute in $<2.0\text{ ms}$ with indexed lookups on `(tenant_id, status)`.

## Rejected alternatives

### Unstructured Jira/Issue Tracker Integration
- What it is: Storing compliance items purely in generic third-party issue trackers.
- Why it was plausible: Teams already use issue trackers.
- Why we rejected it: Lacks regulatory semantic ties to circular clause antipatterns and mathematical debt scoring; fails air-gapped on-premise statutory audit requirements.
- What would change our mind: If an enterprise requires bidirectional Jira webhook synchronization on top of the canonical internal database.
