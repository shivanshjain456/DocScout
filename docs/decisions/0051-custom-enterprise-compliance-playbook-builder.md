# ADR-0051: Custom Enterprise Compliance Playbook Builder (FEAT-060)

## Status
Accepted

## Context
Enterprise compliance programs (e.g. cross-border data transfer, cryptographic migration, third-party vendor audits, and regulatory incident response) often require bespoke operational workflows tailored to specific organizational structures, regulatory jurisdictions, and risk tolerances. Previously, DocScout only supported hardcoded built-in playbook templates.

To empower compliance officers and security leads to author, validate, and execute custom workflows without modifying core code or deploying new releases, DocScout requires an interactive playbook builder and validation engine (`CustomPlaybookBuilder`) backed by strict schema enforcement, multi-tenant database isolation, quota management, and seamless runtime execution on the standard `PlaybookEngine`.

## Decision
1. **Core Validation and Builder Engine (`app/workflows/custom_builder.py`)**:
   - `validate_custom_playbook_schema`: Validates custom playbook definitions against structural invariants:
     - Minimum 2 stages and maximum 6 stages per playbook.
     - Strictly sequential stage numbering starting at 1.
     - Non-empty stage names and at least one exit criterion per stage.
     - Non-empty milestone IDs with strict global uniqueness across the entire playbook.
     - Payload size bounded to <= 256 KB (`max_template_bytes = 262144`).
   - `convert_custom_to_runtime_template`: Converts a validated `CustomPlaybookDefinition` into a standard `PlaybookTemplate` consumable by `PlaybookEngine`.
   - `CustomPlaybookBuilder`: Manages persistence in PostgreSQL `custom_playbook_templates`, tenant quota enforcement (`max_custom_playbooks_per_tenant = 25`), in-memory fallback, and runtime template registration.

2. **Unified Runtime Execution**:
   - Implements `PlaybookEngine.register_template` allowing custom playbooks to register directly into the runtime catalog.
   - Custom playbooks run on the exact same lifecycle endpoints (`/v1/playbooks/start`, `/v1/playbooks/{run_id}/milestones/{milestone_id}`, `/v1/playbooks/{run_id}/promote`) as standard built-in playbooks with zero special casing.

3. **API Endpoints (`app/api/app.py`)**:
   - `POST /v1/playbooks/custom`: Validates, persists, and publishes a new custom compliance playbook. Returns HTTP 422 with detailed error lists on schema failure; returns HTTP 429 when tenant quota is exceeded.
   - `GET /v1/playbooks/custom`: Lists all custom playbooks authored by the authenticated tenant.
   - `GET /v1/playbooks/custom/{playbook_id}`: Retrieves the detailed definition of a specific custom playbook.

4. **Multi-Tenant Database Persistence (`migrations/0044_custom_playbooks.up.sql`)**:
   - Table `custom_playbook_templates` indexed on `(tenant_id, created_at DESC)`.
   - Row-level security enabled with tenant isolation policy.

5. **Console UI Component (`ui/src/components/PlaybookBuilder.tsx`)**:
   - Interactive multi-stage composer allowing users to add/remove stages, define exit criteria, add milestones, configure assigned roles, and set estimated hours.
   - Real-time client-side validation with highlighted error callouts.
   - Direct JSON template import/export capability for template version control.
   - Immediate publish action interfacing with `POST /v1/playbooks/custom`.

6. **Observability and SLA**:
   - Prometheus counter `docscout_custom_playbooks_created_total{tenant_id}`.
   - Validation and persistence latency SLA <= 12.0 ms.

## Consequences
- Compliance officers can author, test, and deploy customized compliance workflows independently.
- Runtime safety is guaranteed via upfront structural and quota validation.
- Zero schema drift or runtime crashes from malformed custom definitions.
