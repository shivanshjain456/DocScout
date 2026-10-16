# ADR-0050: Playbook Progress Dashboard in Console UI (FEAT-059)

## Status
Accepted

## Context
Organizations executing enterprise compliance playbooks (such as RBI 30-day engineering decoupling, AI model risk governance, vendor risk auditing, and regulated release certification) require real-time, visual progress tracking across multi-stage lifecycles. Without a dedicated visual dashboard, compliance officers, risk managers, and engineering leads must manually query disparate APIs or inspect raw database records to determine current stage completion, active blockers, role task distributions, and exit criteria readiness.

DocScout requires a dedicated React console dashboard (`PlaybookConsole.tsx`) supported by a dedicated custom hook (`usePlaybooks.ts`) that presents visual progress wheels, active stage milestones, blockers, role allocations, and exportable audit progress summaries with sub-80ms rendering and zero layout shift.

## Decision
1. **Playbook State Management Hook (`ui/src/hooks/usePlaybooks.ts`)**:
   - Manages active playbook run state, available templates, active stage milestones, role task allocations, and stage transition gates.
   - Provides configurable polling refresh (`refresh_interval_seconds = 30`), caching local state for instantaneous tab switches and offline resiliency.
   - Provides optimistic milestone completion toggling with automated rollback on API rejection.
   - Generates and exports client-side audit progress summary reports in JSON and Markdown formats.

2. **Console Dashboard Component (`ui/src/components/PlaybookConsole.tsx`)**:
   - Visual Progress Rings: SVG-based circular progress gauge displaying overall playbook completion percentage and stage-specific milestone completion.
   - 4-Stage Progressive Workflow Stepper: Visual indicators for Stage 1 (Decouple / Establish), Stage 2 (Bound / Contain), Stage 3 (Automate), and Stage 4 (Self-Govern), detailing active, completed, and locked stages.
   - Milestone Checklist with Role Filtering: Interactive checklist supporting quick completion toggles, evidence attachment indicators, and role filtering (All, SRE, Developer, Compliance Officer, Legal, Risk Lead).
   - Blocker and Exit Gate Warnings: Highlights unsatisfied exit criteria and active stage blockers preventing promotion.
   - Export Progress Summary Action: Generates audit-ready markdown/JSON summary report with cryptographic SHA-256 evidence digests.

3. **Backend Integration**:
   - Interfaces directly with existing REST endpoints in `app/api/app.py`:
     - `GET /v1/playbooks/templates`: List canonical playbook templates.
     - `POST /v1/playbooks/start`: Instantiate a new playbook run.
     - `GET /v1/playbooks/{run_id}`: Retrieve current run state.
     - `POST /v1/playbooks/{run_id}/milestones/{milestone_id}`: Mark milestone complete.
     - `POST /v1/playbooks/{run_id}/promote`: Advance stage through exit criteria gate.
     - `GET /v1/playbooks/{run_id}/tasks`: Fetch role-assigned compliance tasks.

4. **Performance and Accessibility**:
   - Initial mount and render latency bounded to <= 80 ms.
   - WCAG 2.2 AA compliant contrast and semantic keyboard navigation.
   - Zero cumulative layout shift (CLS = 0.00).

## Consequences
- Unifies operational visibility for multi-role compliance playbooks into a single responsive console.
- Enables immediate inspection of stage blockers and exit criteria readiness without backend database queries.
- High performance (<= 80ms) ensures responsiveness across desktop, tablet, and mobile viewports.
