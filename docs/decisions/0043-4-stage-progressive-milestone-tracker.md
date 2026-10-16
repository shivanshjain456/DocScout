# ADR-0043: 4-Stage Progressive Milestone Tracker (FEAT-052)

## Status
Accepted

## Context
Each of the 12 statutory compliance playbooks decomposes into 4 progressive stages (Stage 1 Decouple/Establish, Stage 2 Bound/Contain, Stage 3 Automate, Stage 4 Self-Govern). Organizations need granular milestone tracking within each stage, with evidence artifact grounding and audit verification notes, before stage exit gates are unlocked. Without dedicated relational storage and validation logic for milestone deliverables, milestone completion data remains untracked or orphaned, and premature advancement to downstream automation stages cannot be systematically prevented.

## Decision
1. **Schema Migration (`migrations/0037_playbook_milestones.up.sql`)**:
   - Create `playbook_milestones` table capturing `run_id`, `tenant_id`, `playbook_id`, `stage_number`, `milestone_id`, `completed`, `evidence_doc_id`, `notes`, `completed_at`, and `created_at`.
   - Enforce uniqueness on `(run_id, stage_number, milestone_id)`.
   - Establish multi-tenant Row-Level Security (RLS) on `playbook_milestones`.

2. **Milestone Tracking Engine (`app/workflows/milestone_tracker.py`)**:
   - `MilestoneConfig`: Configurable validation rules including `require_evidence_attachment: bool = True`.
   - `StageProgress`: Data model exposing `stage_number`, `stage_name`, `total_milestones`, `completed_milestones`, `completion_ratio`, and `exit_ready` (True only when `completion_ratio == 1.0`).
   - `MilestoneTracker`: Evaluates milestone completions, validates that completed milestones belong to the active stage of the active run, enforces minimum note length (>= 10 chars), and calculates stage exit readiness with sub-4ms execution latency.
   - Prevents orphaned milestone records on reset.

3. **REST API Extensions (`app/api/app.py`)**:
   - `POST /v1/playbooks/{run_id}/milestones/{milestone_id}`: Records milestone completion with evidence document reference and audit verification notes; returns updated `StageProgress`.
   - `GET /v1/playbooks/{run_id}/stages/{stage_number}/progress`: Returns stage completion metrics, milestone counts, and exit criteria readiness.
   - `GET /v1/playbooks/{run_id}/progress`: Returns summary progress across all 4 stages.

4. **Observability (`app/api/metrics.py`)**:
   - Counter `docscout_milestones_completed_total{playbook_id, stage}` tracking deliverable sign-offs by statutory playbook and stage.

5. **Console UI Component (`ui/src/components/MilestoneList.tsx`)**:
   - Granular milestone checklist rendering deliverable description, role assignment badge, evidence attachment input, and audit note fields with real-time completion gauge.

## Consequences
- Strict prerequisite verification stops premature advancement to advanced automation stages.
- Every completed milestone retains cryptographic or document reference evidence and structured notes for statutory auditor review.
- Execution latency remains strictly bounded under 4.0ms p95.
