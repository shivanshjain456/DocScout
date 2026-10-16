# Pillar 6 Specification: Playbook-Guided Compliance & Workflow Engines
*DocScout Enterprise Regulatory Intelligence Engine*

---

## FEAT-051: Interactive Compliance Playbook Runtime
- **Objective:** Operationalize the 12 structured playbooks from `term-taxonomy.json.playbooks` (e.g., `playbook.foundations-30d`, `playbook.deploy-confidence-60d`, `playbook.ai-assurance`, `playbook.incident-readiness`) as active state-machine compliance workflows.
- **In-scope behavior:** Instantiating active playbook runs per tenant; maintaining state transitions between stages; recording milestone completions; validating exit criteria before advancing.
- **Excluded behavior:** Arbitrary untracked process modeling not defined in the formal taxonomy.
- **Implementation boundaries:** `migrations/0015_playbook_workflows.up.sql`, `app/workflows/engine.py`, `app/api/app.py` (`/v1/playbooks/*`).
- **Integration points:** REST API endpoints `/v1/playbooks/*`; Playbook runtime view in React console.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`playbooks`), `app/workflows/engine.py`.
- **Supported inputs:** `StartPlaybookRequest(playbook_id: str, tenant_id: str, assigned_lead: str)`.
- **Input validation rules:** `playbook_id` must match one of the 12 taxonomy playbook IDs; `tenant_id` valid UUID.
- **Output schema:** `PlaybookRun(run_id: UUID, playbook_id: str, title: str, current_stage: int, total_stages: int, status: Literal["ACTIVE", "BLOCKED", "COMPLETED"], created_at: datetime)`.
- **Configuration schema:** `PlaybookEngineConfig(allow_stage_skipping: bool = False, auto_verify_exit_criteria: bool = True)`.
- **Default values:** `allow_stage_skipping = False`, `auto_verify_exit_criteria = True`.
- **Dependencies:** PostgreSQL tables `playbook_templates` and `playbook_runs`.
- **Compatibility requirements:** Multi-tenant architecture with PostgreSQL Row-Level Security.
- **Authorization rules:** Requires authenticated user token with `compliance:write` or `compliance:admin` scope.
- **Data isolation rules:** Playbook execution instances strictly partitioned by `tenant_id`.
- **Error behavior:** Invalid state transition returns HTTP 400 with "Exit criteria for Stage N not yet satisfied".
- **Fallback behavior:** Transaction rolls back; workflow state remains in current valid stage.
- **Observability requirements:** Counter `docscout_playbook_runs_started_total{playbook_id}`, gauge `docscout_active_playbooks_count`.
- **Performance limits:** State transition evaluation latency $\le 8.0\text{ ms}$ p95.
- **Resource limits:** Connection pool usage $\le 2$ connections per active workflow update.
- **Acceptance criteria:** Successfully instantiates, transitions, and completes all 12 taxonomy playbooks with zero invalid state transitions.
- **Evaluation dataset:** 24 simulated enterprise playbook execution runs covering all 12 playbooks.
- **Evaluation baseline:** 0% interactive workflow guidance in baseline.
- **Required improvement threshold:** 100% adherence to state transition constraints across all test runs.
- **Regression limits:** Zero database race conditions during concurrent milestone updates.
- **Completion criteria:** Database migrations and workflow tests pass in `tests/test_playbook_engine.py`.

---

## FEAT-052: 4-Stage Progressive Milestone Tracker
- **Objective:** Track organizational progression across the 4 discrete stages of each playbook (Stage 1 Decouple/Establish, Stage 2 Bound/Contain, Stage 3 Automate, Stage 4 Self-Govern), providing granular milestone checklists.
- **In-scope behavior:** Decomposing playbook stages into concrete term-driven milestones; recording evidence artifacts against each milestone; tracking milestone completion percentage per stage.
- **Excluded behavior:** Premature advancement to Stage 3 or 4 before foundational stages are certified.
- **Implementation boundaries:** `app/workflows/milestone_tracker.py`, `ui/src/components/MilestoneList.tsx`.
- **Integration points:** API endpoint `POST /v1/playbooks/{run_id}/milestones/{milestone_id}`; UI checklist view.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`playbooks[].stages`), `app/workflows/milestone_tracker.py`.
- **Supported inputs:** `CompleteMilestoneRequest(milestone_id: str, evidence_doc_id: Optional[str], notes: str)`.
- **Input validation rules:** `milestone_id` must belong to active stage of current run; `notes` min 10 chars.
- **Output schema:** `StageProgress(stage_number: int, stage_name: str, total_milestones: int, completed_milestones: int, completion_ratio: float, exit_ready: bool)`.
- **Configuration schema:** `MilestoneConfig(require_evidence_attachment: bool = True)`.
- **Default values:** `require_evidence_attachment = True`.
- **Dependencies:** Relational table `playbook_milestones`.
- **Compatibility requirements:** Real-time WebSocket or polling update to React console UI.
- **Authorization rules:** Requires `compliance:write` role.
- **Data isolation rules:** Milestone evidence partitioned by tenant.
- **Error behavior:** Attempting to complete milestone from inactive stage returns HTTP 400.
- **Fallback behavior:** Milestone remains unchecked; user is alerted to complete prerequisites.
- **Observability requirements:** Counter `docscout_milestones_completed_total{playbook_id, stage}`.
- **Performance limits:** Milestone update execution $\le 4.0\text{ ms}$.
- **Resource limits:** Zero extra memory.
- **Acceptance criteria:** Accurately renders and tracks milestones across all 4 stages for any active playbook run.
- **Evaluation dataset:** 10 end-to-end milestone lifecycle test runs.
- **Evaluation baseline:** Zero structured milestone tracking in baseline.
- **Required improvement threshold:** 100% data integrity and audit logging of milestone updates.
- **Regression limits:** Zero orphaned milestone records on playbook reset.
- **Completion criteria:** Passes `tests/test_milestones.py`.

---

## FEAT-053: Automated Stage Exit Criteria Validator
- **Objective:** Automatically verify that stage exit criteria (e.g., "Every production change can be exposed to a bounded population first") are empirically met via test results or logs before permitting stage promotion.
- **In-scope behavior:** Evaluating automated verification rules against ingested telemetry, test suites, or policy scans; computing exit readiness score; blocking stage promotion if exit criteria fail.
- **Excluded behavior:** Bypassing exit criteria via administrative override without recorded audit exception.
- **Implementation boundaries:** `app/workflows/exit_validator.py`.
- **Integration points:** Stage promotion gate in `app/workflows/engine.py`.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`playbooks[].stages[].exit`), `app/workflows/exit_validator.py`.
- **Supported inputs:** `PromoteStageRequest(run_id: UUID, current_stage: int)`.
- **Input validation rules:** `current_stage` must match active stage of run.
- **Output schema:** `ExitValidationResult(can_advance: bool, exit_statement: str, checks_evaluated: list[CriterionCheck(criterion: str, status: Literal["PASSED", "FAILED"], evidence_ref: str)], blocking_issues: list[str])`.
- **Configuration schema:** `ExitValidatorConfig(enforce_strict_exit: bool = True)`.
- **Default values:** `enforce_strict_exit = True`.
- **Dependencies:** Python rule evaluator, link to `compliance_telemetry` and `audit_log`.
- **Compatibility requirements:** Enforced synchronously during stage promotion API call.
- **Authorization rules:** Requires `compliance:admin` scope.
- **Data isolation rules:** Strictly scoped to tenant's private evidence records.
- **Error behavior:** If exit criteria not met, returns HTTP 412 (Precondition Failed) with blocking issues list.
- **Fallback behavior:** Stage promotion rejected; workflow remains in current stage with actionable fix list.
- **Observability requirements:** Counter `docscout_stage_promotions_attempted_total{status}`, structlog audit event.
- **Performance limits:** Exit criteria evaluation $\le 6.0\text{ ms}$.
- **Resource limits:** Memory footprint $\le 2\text{ MB}$.
- **Acceptance criteria:** Blocks stage promotion 100% of the time when simulated exit criteria evidence is missing or failing.
- **Evaluation dataset:** 20 stage promotion test cases (10 valid, 10 lacking exit evidence).
- **Evaluation baseline:** Subjective manual self-certification without automated evidence checks.
- **Required improvement threshold:** 100% enforcement of exit criteria preconditions.
- **Regression limits:** Zero false blocks when all criteria are genuinely fulfilled.
- **Completion criteria:** Unit and workflow tests pass in `tests/test_exit_validator.py`.

---

## FEAT-054: Role-Based Compliance Task Routing
- **Objective:** Dispatches playbook tasks to specific taxonomy roles (`developer`, `qa-engineer`, `sre`, `engineering-manager`, `compliance-officer`), generating role-tailored action checklists.
- **In-scope behavior:** Parsing role tags from `term-taxonomy.json.terms[].roles`; filtering playbook tasks by user's assigned role; delivering role-specific views in the UI console and digest notifications.
- **Excluded behavior:** Arbitrary user role creation outside the taxonomy role model without admin approval.
- **Implementation boundaries:** `app/workflows/task_router.py`, `ui/src/components/RoleTaskView.tsx`.
- **Integration points:** API endpoint `GET /v1/playbooks/{run_id}/tasks?role={role}`; React console role switcher.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`terms[].roles`), `app/workflows/task_router.py`.
- **Supported inputs:** Playbook run `run_id: UUID`, role query parameter `role: str`.
- **Input validation rules:** `role` must be one of `{"developer", "qa-engineer", "sre", "engineering-manager", "compliance-officer"}`.
- **Output schema:** `RoleTaskList(role: str, pending_tasks: list[RoleTask(task_id: str, title: str, stage: int, term_reference: str, estimated_hours: int)])`.
- **Configuration schema:** `TaskRouterConfig(notify_on_assignment: bool = True)`.
- **Default values:** `notify_on_assignment = True`.
- **Dependencies:** Relational table `playbook_tasks` joined with `taxonomy_terms`.
- **Compatibility requirements:** Integrated with Auth0 RBAC user roles.
- **Authorization rules:** Callers view tasks matching their authenticated role or all tasks if `compliance:admin`.
- **Data isolation rules:** Task assignments partitioned strictly by tenant ID.
- **Error behavior:** Invalid role returns HTTP 422 with supported role list.
- **Fallback behavior:** Returns all stage tasks unpartitioned with diagnostic warning.
- **Observability requirements:** Counter `docscout_tasks_dispatched_total{role}`.
- **Performance limits:** Task dispatch lookup $\le 2.0\text{ ms}$.
- **Resource limits:** Zero extra memory.
- **Acceptance criteria:** Correctly routes technical implementation tasks (e.g. kill switches, ACA) to SREs/Developers and governance tasks to Compliance Officers.
- **Evaluation dataset:** 50 tasks generated across all 12 taxonomy playbooks.
- **Evaluation baseline:** Flat unassigned task lists overwhelming compliance and engineering teams.
- **Required improvement threshold:** 100% role assignment accuracy matching `term-taxonomy.json` specifications.
- **Regression limits:** Zero tasks left unassigned to any role.
- **Completion criteria:** Verified in `tests/test_task_router.py`.

---

## FEAT-055: Regulatory Cyber Incident Response Playbook
- **Objective:** Operationalize `playbook.incident-readiness` for banking cyber incidents, enforcing strict evidence preservation, root-cause isolation, and RBI reporting within the statutory 6-hour window.
- **In-scope behavior:** Interactive incident crisis workflow; automated 6-hour regulatory countdown timer; generating statutory incident disclosure forms; step-by-step forensic evidence capture checklist.
- **Excluded behavior:** Auto-submitting reports to RBI portals without compliance officer final sign-off.
- **Implementation boundaries:** `app/workflows/incident_playbook.py`, `ui/src/components/CrisisConsole.tsx`.
- **Integration points:** API endpoint `POST /v1/incidents/declare`; Crisis Mode toggle in UI console.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`playbook.incident-readiness`), `app/workflows/incident_playbook.py`.
- **Supported inputs:** `DeclareIncidentRequest(severity: Literal["SEV1", "SEV2"], summary: str, systems_impacted: list[str], discovery_timestamp: datetime)`.
- **Input validation rules:** `discovery_timestamp` cannot be in the future; `summary` min 20 chars.
- **Output schema:** `IncidentCrisisState(incident_id: UUID, statutory_reporting_deadline: datetime, minutes_remaining: int, required_actions: list[str], disclosure_draft: str)`.
- **Configuration schema:** `IncidentConfig(rbi_deadline_hours: int = 6, emergency_sms_enabled: bool = False)`.
- **Default values:** `rbi_deadline_hours = 6`, `emergency_sms_enabled = False`.
- **Dependencies:** Python `datetime`, Brevo SMS/Email client for urgent notifications.
- **Compatibility requirements:** High-availability execution; zero non-essential DB dependencies during crisis mode.
- **Authorization rules:** Requires `incident:manage` or `compliance:admin` scope.
- **Data isolation rules:** Incident data encrypted at rest with tenant-dedicated keys.
- **Error behavior:** Inability to start crisis workflow logs fatal error and triggers pager alarm.
- **Fallback behavior:** Local fallback JSON file written if database is temporarily unavailable.
- **Observability requirements:** Gauge `docscout_active_crisis_incidents`, counter `docscout_incident_milestones_met_total`.
- **Performance limits:** Crisis initialization $\le 5.0\text{ ms}$.
- **Resource limits:** Zero rate limiting applied to crisis management endpoints.
- **Acceptance criteria:** Enforces 6-hour countdown, alerts risk officer at 4-hour mark, and auto-generates statutory RBI incident report template.
- **Evaluation dataset:** 5 simulated regulatory cyber crisis drill scenarios.
- **Evaluation baseline:** 0% interactive regulatory crisis handling in baseline.
- **Required improvement threshold:** 100% adherence to RBI Cyber Security Framework reporting templates.
- **Regression limits:** Zero downtime or degradation of crisis endpoints under high system load.
- **Completion criteria:** Playwright E2E crisis drill test passes.

---

## FEAT-056: Regulated Release Certification Pipeline
- **Objective:** Operationalize `playbook.regulated-release`, generating a formal Safety Case and Verification Evidence Report prior to deploying updates to core financial switches or payment applications.
- **In-scope behavior:** Collecting CI test verification artifacts, SAST/DAST scans, and structural coverage reports; compiling formal Safety Case in Goal Structuring Notation (GSN); issuing cryptographically signed release certificate.
- **Excluded behavior:** Deploying unverified code bypassing CI release gates.
- **Implementation boundaries:** `app/workflows/release_certifier.py`, `scripts/certify_release.py`.
- **Integration points:** CI/CD pipeline step `.github/workflows/deploy.yml`; `/v1/compliance/certify-release`.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`playbook.regulated-release`), `app/workflows/release_certifier.py`.
- **Supported inputs:** `CertifyReleaseRequest(commit_sha: str, build_id: str, test_report_path: str, coverage_report_path: str)`.
- **Input validation rules:** `commit_sha` valid 40-char hex string; all report files must exist and be valid JSON/XML.
- **Output schema:** `ReleaseCertificate(certificate_id: UUID, commit_sha: str, is_certified: bool, gsn_safety_case_json: dict, signature_sha256: str, certified_at: datetime)`.
- **Configuration schema:** `ReleaseCertConfig(min_mutation_score: float = 0.78, require_slsa_level_3: bool = True)`.
- **Default values:** `min_mutation_score = 0.78`, `require_slsa_level_3 = True`.
- **Dependencies:** Python `cryptography`, `xml.etree.ElementTree` for JUnit/Coverage parsing.
- **Compatibility requirements:** Executable in CLI and as API endpoint.
- **Authorization rules:** Requires CI/CD service account with `release:certify` scope.
- **Data isolation rules:** Certificate signed with institutional OIDC key and published to audit ledger.
- **Error behavior:** If verification reports fail quality thresholds, certificate issuance is rejected with exit code 1.
- **Fallback behavior:** Build pipeline halts; deployment aborted.
- **Observability requirements:** Counter `docscout_releases_certified_total{status}`.
- **Performance limits:** Certificate compilation and signing $\le 1.5\text{ seconds}$.
- **Resource limits:** Memory footprint $\le 32\text{ MB}$.
- **Acceptance criteria:** Automatically generates verifiable GSN Safety Case satisfying SEBI/RBI change management audit requirements.
- **Evaluation dataset:** 10 simulated deployment builds with varying quality bar results.
- **Evaluation baseline:** Manual ad-hoc approval emails lacking verifiable cryptographic evidence.
- **Required improvement threshold:** 100% rejection of builds with failing tests or regressed mutation scores.
- **Regression limits:** Zero false-positive certifications of unverified commits.
- **Completion criteria:** CI workflow verification step green in GitHub Actions.

---

## FEAT-057: Post-Quantum Cryptographic Migration Tracker
- **Objective:** Operationalize `playbook.crypto-migration`, orchestrating inventorying of classical RSA/ECC certificates, hybrid key exchange validation, and post-quantum readiness scoring across banking infrastructure.
- **In-scope behavior:** Tracking cryptographic assets across enterprise endpoints; flagging algorithms vulnerable to Harvest-Now-Decrypt-Later (HNDL) attacks; tracking migration to FIPS 203/204/205 quantum-safe algorithms.
- **Excluded behavior:** Performing cryptanalysis on live network traffic.
- **Implementation boundaries:** `app/compliance/pqc_tracker.py`, `ui/src/components/PQCConsole.tsx`.
- **Integration points:** API endpoint `/v1/compliance/pqc/*`; PQC Migration tab in React console.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`cryptography-post-quantum-readiness`), `app/compliance/pqc_tracker.py`.
- **Supported inputs:** `CryptographicInventoryBatch(endpoints: list[EndpointCryptoSpec(hostname: str, tls_version: str, cipher_suite: str, cert_signature_algo: str, cert_expiry: date)])`.
- **Input validation rules:** `endpoints` list non-empty; valid hostname strings.
- **Output schema:** `PQCReadinessReport(total_assets: int, quantum_vulnerable_count: int, pqc_ready_count: int, hndl_exposure_score: float, migration_milestone: str)`.
- **Configuration schema:** `PQCConfig(flag_rsa_under_3072: bool = True)`.
- **Default values:** `flag_rsa_under_3072 = True`.
- **Dependencies:** Pure Python cipher suite classifier.
- **Compatibility requirements:** Stateless REST API execution.
- **Authorization rules:** Requires `compliance:admin` or `security:audit`.
- **Data isolation rules:** Cryptographic inventory partitioned by tenant; sensitive server names hashed.
- **Error behavior:** Unknown cipher suite flagged as "UNKNOWN_AUDIT_REQUIRED" with diagnostic warning.
- **Fallback behavior:** Returns inventory with unknown classifications highlighted.
- **Observability requirements:** Gauge `docscout_pqc_readiness_score{tenant_id}`.
- **Performance limits:** Evaluation of 1,000 endpoint specs executed in $\le 10.0\text{ ms}$.
- **Resource limits:** Memory allocation $\le 4\text{ MB}$.
- **Acceptance criteria:** Accurately classifies classical vs hybrid vs post-quantum cipher suites and computes HNDL risk score.
- **Evaluation dataset:** 100 real-world TLS cipher suite configurations.
- **Evaluation baseline:** 0% post-quantum cryptographic readiness tracking in baseline.
- **Required improvement threshold:** 100% accuracy on classifying classical vs post-quantum cipher suites.
- **Regression limits:** Zero false classifications of deprecated legacy ciphers as secure.
- **Completion criteria:** Verified in `tests/test_pqc_tracker.py`.

---

## FEAT-058: Digital Operational Resilience (DORA) Framework Runner
- **Objective:** Operationalize `playbook.resilience` aligned with EU DORA and RBI Cyber Resilience guidelines, tracking threat-led penetration testing, ICT risk management, and major incident reporting.
- **In-scope behavior:** Tracking ICT third-party risk dependencies; logging operational resilience stress test results; generating DORA Pillar 1-5 compliance scorecards; managing threat-led testing schedules.
- **Excluded behavior:** Executing live DDoS attacks against external third-party service providers.
- **Implementation boundaries:** `app/compliance/dora_runner.py`, `app/api/app.py`.
- **Integration points:** API endpoint `/v1/compliance/dora/*`; Resilience view in console.
- **Source-of-truth files:** `do not commit!/term-taxonomy.json` (`standardsRegistry` ["EU DORA"]), `app/compliance/dora_runner.py`.
- **Supported inputs:** `DORAAssessmentRequest(tenant_id: str, ict_systems: list[ICTSystemSpec])`.
- **Input validation rules:** `ict_systems` non-empty list; valid system criticality ratings.
- **Output schema:** `DORAComplianceReport(pillars: dict[str, PillarStatus(pillar_name: str, compliance_pct: float, gaps: list[str])], overall_readiness: float)`.
- **Configuration schema:** `DORAConfig(strict_critical_ict_third_party_rules: bool = True)`.
- **Default values:** `strict_critical_ict_third_party_rules = True`.
- **Dependencies:** Relational database tables `dora_systems` and `resilience_tests`.
- **Compatibility requirements:** Multi-tenant PostgreSQL support.
- **Authorization rules:** Requires `compliance:admin` scope.
- **Data isolation rules:** Strictly scoped to tenant's private infrastructure records.
- **Error behavior:** Schema failure returns HTTP 422 with validation errors.
- **Fallback behavior:** Returns descriptive failure details.
- **Observability requirements:** Counter `docscout_dora_assessments_completed_total`.
- **Performance limits:** Assessment generation latency $\le 15.0\text{ ms}$ p95.
- **Resource limits:** Memory footprint $\le 8\text{ MB}$.
- **Acceptance criteria:** Accurately evaluates compliance against all 5 pillars of the Digital Operational Resilience Act.
- **Evaluation dataset:** 10 simulated financial institution ICT architecture profiles.
- **Evaluation baseline:** 0% DORA operational resilience framework execution in baseline.
- **Required improvement threshold:** 100% control coverage across DORA Articles 5-16.
- **Regression limits:** Zero false claims of resilience compliance without verified test evidence.
- **Completion criteria:** Unit tests pass in `tests/test_dora_runner.py`.

---

## FEAT-059: Playbook Progress Dashboard in Console UI
- **Objective:** Dedicated React console dashboard displaying visual progress wheels, active stage milestones, blockers, role allocations, and exportable audit progress for active playbooks.
- **In-scope behavior:** Real-time visual dashboard rendering; interactive milestone checklists; role filter toggles; progress percentage gauges; download progress summary report.
- **Excluded behavior:** Unresponsive UI rendering freezing the main browser thread.
- **Implementation boundaries:** `ui/src/components/PlaybookConsole.tsx`, `ui/src/hooks/usePlaybooks.ts`.
- **Integration points:** Main navigation bar "Playbooks" tab in React console.
- **Source-of-truth files:** `ui/src/components/PlaybookConsole.tsx`, `app/api/app.py`.
- **Supported inputs:** Active user session context, active playbook run ID.
- **Input validation rules:** Valid authenticated session.
- **Output schema:** Interactive React DOM component hierarchy with WCAG 2.2 AA accessibility.
- **Configuration schema:** `PlaybookUIPreferences(refresh_interval_seconds: int = 30)`.
- **Default values:** `refresh_interval_seconds = 30`.
- **Dependencies:** React, Tailwind CSS, Lucide icons, Recharts for progress rings.
- **Compatibility requirements:** Responsive design supporting mobile, tablet, and desktop viewports.
- **Authorization rules:** Requires authenticated user session.
- **Data isolation rules:** Displays only data associated with caller's authorized tenant.
- **Error behavior:** API fetch error displays friendly error state with "Retry" button.
- **Fallback behavior:** Displays cached local state if background network refresh fails.
- **Observability requirements:** Client-side interaction telemetry via opt-in events.
- **Performance limits:** Initial component mount and render $\le 80\text{ ms}$; 60fps interaction.
- **Resource limits:** JavaScript bundle size $\le 45\text{ KB}$ gzipped.
- **Acceptance criteria:** Intuitive, responsive dashboard allowing users to inspect stages, complete milestones, and view audit exit criteria.
- **Evaluation dataset:** React Testing Library component tests covering all user interaction paths.
- **Evaluation baseline:** Zero visual workflow management in legacy console UI.
- **Required improvement threshold:** 100% component test pass rate; zero accessibility contrast violations.
- **Regression limits:** Zero layout thrashing or cumulative layout shift (CLS = 0.00).
- **Completion criteria:** Playwright E2E test `tests_e2e/test_playbook_console.spec.ts` passes.

---

## FEAT-060: Custom Enterprise Compliance Playbook Builder
- **Objective:** Interactive workflow builder allowing compliance leads to compose custom multi-stage internal playbooks by chaining taxonomy terms, exit criteria, and formulas.
- **In-scope behavior:** Drag-and-drop / JSON template composer; validating custom playbook schemas against `term-taxonomy.schema.json`; publishing custom playbooks to tenant workspace; executing custom playbooks in runtime.
- **Excluded behavior:** Creating unvalidated circular dependency workflows.
- **Implementation boundaries:** `app/workflows/custom_builder.py`, `ui/src/components/PlaybookBuilder.tsx`.
- **Integration points:** API endpoint `POST /v1/playbooks/custom`; UI Playbook Builder view.
- **Source-of-truth files:** `do not commit!/term-taxonomy.schema.json`, `app/workflows/custom_builder.py`.
- **Supported inputs:** `CustomPlaybookDefinition(id: str, name: str, goal: str, stages: list[StageDefinition])`.
- **Input validation rules:** Must validate 100% against `term-taxonomy.schema.json`; minimum 2 stages, maximum 6 stages.
- **Output schema:** `PlaybookTemplateResponse(template_id: str, is_valid: bool, stages_count: int, created_at: datetime)`.
- **Configuration schema:** `CustomBuilderConfig(max_custom_playbooks_per_tenant: int = 25)`.
- **Default values:** `max_custom_playbooks_per_tenant = 25`.
- **Dependencies:** Python `jsonschema` for template validation.
- **Compatibility requirements:** Custom playbooks run on the exact same engine as built-in playbooks.
- **Authorization rules:** Requires `compliance:admin` scope.
- **Data isolation rules:** Custom playbooks private to creating tenant; never shared cross-tenant.
- **Error behavior:** Schema validation failure returns HTTP 422 with specific JSON path validation errors.
- **Fallback behavior:** Template not saved; user alerted with highlighted invalid schema nodes.
- **Observability requirements:** Counter `docscout_custom_playbooks_created_total{tenant_id}`.
- **Performance limits:** Template validation and database save $\le 12.0\text{ ms}$.
- **Resource limits:** Max template JSON size $\le 256\text{ KB}$.
- **Acceptance criteria:** Compliance leads can compose, validate, save, and immediately execute custom internal playbooks.
- **Evaluation dataset:** 10 custom enterprise playbook template definitions.
- **Evaluation baseline:** Fixed hardcoded playbooks only without enterprise customization.
- **Required improvement threshold:** 100% valid execution of custom playbooks in the standard runtime.
- **Regression limits:** Zero database schema corruption from malformed user-defined templates.
- **Completion criteria:** Verified in `tests/test_custom_playbook_builder.py`.
