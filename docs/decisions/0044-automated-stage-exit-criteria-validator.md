# ADR-0044: Automated Stage Exit Criteria Validator (FEAT-053)

## Status
Accepted

## Context
Compliance playbooks decompose into 4 sequential stages. In conventional compliance audits, stage advancement relies on subjective manual attestation, leading to premature promotion into operational containment and automation stages without verified evidence. Organizations require automated verification of stage exit criteria against ingested telemetry, milestone deliverables, and attached grounding artifacts before permitting stage promotion. Furthermore, any administrative bypass must require recorded audit justification rather than silent overrides.

## Decision
1. **Schema Migration (`migrations/0038_stage_exit_validations.up.sql`)**:
   - Create `stage_exit_validations` table recording `validation_id`, `run_id`, `tenant_id`, `playbook_id`, `stage_number`, `can_advance`, `exit_statement`, `checks_evaluated`, `blocking_issues`, `override_applied`, `override_justification`, and `validated_at`.
   - Implement multi-tenant Row-Level Security (RLS) on `stage_exit_validations`.
   - Index by `(run_id, stage_number)` and `(tenant_id)`.

2. **Exit Criteria Validation Engine (`app/workflows/exit_validator.py`)**:
   - `ExitValidatorConfig`: Supports `enforce_strict_exit: bool = True`.
   - `CriterionCheck`: Structured evaluation of individual exit statements with `status: Literal["PASSED", "FAILED"]` and `evidence_ref`.
   - `ExitValidationResult`: Contains `can_advance`, `exit_statement`, `checks_evaluated`, `blocking_issues`, and `override_applied`.
   - `ExitCriteriaValidator`: Evaluates stage exit criteria against completed milestones and attached evidence records. Rejects promotion when evidence is missing or incomplete, returning HTTP 412 Precondition Failed.
   - Enforces recorded audit exceptions for administrative overrides (minimum 15 characters justification).
   - Guarantees evaluation latency under 6.0ms p95 and memory footprint under 2MB.

3. **Engine & REST API Integration (`app/workflows/engine.py` and `app/api/app.py`)**:
   - `POST /v1/playbooks/{run_id}/validate-exit`: Pre-flight verification of stage exit criteria without state mutation.
   - `POST /v1/playbooks/{run_id}/promote`: Synchronously validates stage exit criteria before advancing stage; rejects unverified promotions with HTTP 412.
   - Integrates with `PlaybookEngine.advance_stage` with strict exit criteria enforcement.

4. **Observability (`app/api/metrics.py`)**:
   - Counter `docscout_stage_promotions_attempted_total{status}` capturing promotion attempts by status (`passed`, `failed`, `override`).
   - Structured JSON audit events via structlog for every validation decision.

5. **Console UI Component (`ui/src/components/StageExitGateModal.tsx`)**:
   - Interactive modal presenting individual exit checks, evidence badges, blocking issues, and administrative override workflow.

## Consequences
- Prevents unverified playbook promotion 100% of the time when deliverables or evidence are missing.
- Provides complete audit trail of stage promotion validations and exceptions for external regulators.
- Synchronous evaluation latency remains well within the 6.0ms performance boundary.
