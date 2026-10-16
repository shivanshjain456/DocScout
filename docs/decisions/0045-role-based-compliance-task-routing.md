# ADR-0045: Role-Based Compliance Task Routing (FEAT-054)

## Status
Accepted

## Context
Enterprise compliance workflows involve cross-functional teams with distinct responsibilities spanning systems engineering, software development, quality assurance, management oversight, and statutory compliance. Presenting flat, unassigned deliverable lists creates cognitive overload and assignment ambiguity, delaying critical milestones. Compliance playbooks must automatically dispatch tasks to specific taxonomy roles (developer, qa-engineer, sre, engineering-manager, compliance-officer), generating role-tailored action checklists while preventing arbitrary user role sprawl.

## Decision
1. **Schema Migration (`migrations/0039_playbook_tasks.up.sql`)**:
   - Create `playbook_tasks` table tracking `task_id`, `run_id`, `tenant_id`, `playbook_id`, `stage_number`, `role`, `title`, `term_reference`, `estimated_hours`, `completed`, `completed_at`, and `created_at`.
   - Constrain `role` to canonical taxonomy roles: `developer`, `qa-engineer`, `sre`, `engineering-manager`, `compliance-officer`.
   - Implement multi-tenant Row-Level Security (RLS) on `playbook_tasks`.
   - Index by `(run_id, role)` and `(tenant_id)`.

2. **Task Routing Engine (`app/workflows/task_router.py`)**:
   - `TaskRouterConfig`: Configures task dispatch options including `notify_on_assignment: bool = True` and `default_estimated_hours: int = 8`.
   - `RoleTask`: Data model capturing granular task attributes, stage reference, statutory term link, estimated effort, and completion status.
   - `RoleTaskList`: Aggregated checklist partitioned by role with pending/completed segregation and total estimated hours.
   - `TaskRouter`: Dispatches and filters tasks by taxonomy role with 100% role assignment accuracy across all 12 statutory playbooks. Rejects non-taxonomy roles with HTTP 422.
   - Strictly bounds lookup latency to under 2.0ms p95 with zero extra memory overhead.

3. **REST API Extensions (`app/api/app.py`)**:
   - `GET /v1/playbooks/{run_id}/tasks`: Returns role-partitioned tasks for a specific role or across all roles with stage filtering.
   - `GET /v1/playbooks/runs/{run_id}/tasks`: Canonical alias matching existing playbook run route conventions.
   - Validates role parameter and returns HTTP 422 if an unsupported role is requested.

4. **Observability (`app/api/metrics.py`)**:
   - Counter `docscout_tasks_dispatched_total{role}` tracking task assignments across each functional role.
   - Structured JSON audit events via structlog on task routing invocations.

5. **Console UI Component (`ui/src/components/RoleTaskView.tsx`)**:
   - Role switcher tabs with functional role badges, effort estimates, statutory term chips, and pending task checklists.

## Consequences
- 100% of playbook deliverables across all 12 playbooks are deterministically mapped to appropriate functional owners.
- Eliminates deliverable ambiguity and prevents tasks from being orphaned without clear ownership.
- Dispatch latency remains well below the 2.0ms p95 SLA.
