import React, { useState } from 'react'

export interface MilestoneItem {
  id: string
  title: string
  role: string
  mandatory?: boolean
  completed?: boolean
  completed_at?: string | null
  evidence_doc_id?: string | null
  notes?: string
}

export interface StageItem {
  number: number
  name: string
  objective: string
  exit_criteria: string[]
  milestones: MilestoneItem[]
}

export interface PlaybookTemplateData {
  playbook_id: string
  title: string
  description: string
  domain: string
  total_stages: number
  stages: StageItem[]
}

export interface PlaybookRunData {
  run_id: string
  tenant_id: string
  playbook_id: string
  title: string
  assigned_lead: string
  current_stage: number
  total_stages: number
  status: 'ACTIVE' | 'BLOCKED' | 'COMPLETED'
  stage_data: {
    completed_milestones: Array<{
      milestone_id: string
      stage_number: number
      completed_at: string
      evidence_doc_id?: string | null
      notes?: string
    }>
    stage_history: Array<{
      stage_number: number
      entered_at: string
      exited_at?: string
      status: string
    }>
  }
  created_at: string
  updated_at: string
}

export interface PlaybookRuntimeViewProps {
  apiBaseUrl?: string
  apiKey?: string
  className?: string
  initialPlaybookId?: string
  onRunUpdated?: (run: PlaybookRunData) => void
}

const PRESET_TEMPLATES: Record<string, PlaybookTemplateData> = {
  'playbook.foundations-30d': {
    playbook_id: 'playbook.foundations-30d',
    title: 'Foundations 30-Day Engineering Decoupling',
    description: 'Establish decoupled service boundaries, hermetic test fixtures, and modular regulatory controls.',
    domain: 'core-architecture',
    total_stages: 4,
    stages: [
      {
        number: 1,
        name: 'Decouple / Establish',
        objective: 'Catalog existing monorepo boundaries and inventory regulatory dependency edges.',
        exit_criteria: ['Domain interfaces documented with zero circular schema references.'],
        milestones: [
          { id: 'M1-1', title: 'Map database dependencies and domain boundary edges', role: 'sre' },
          { id: 'M1-2', title: 'Draft architectural decoupling ADR and API contracts', role: 'developer' },
        ],
      },
      {
        number: 2,
        name: 'Bound / Contain',
        objective: 'Implement architectural bulkheads and isolate critical transaction pathways.',
        exit_criteria: ['Zero uncontained cross-boundary database queries detected in CI.'],
        milestones: [
          { id: 'M2-1', title: 'Enforce service boundary linting and strict package visibility', role: 'developer' },
          { id: 'M2-2', title: 'Deploy bulkhead concurrency limits for tenant workloads', role: 'sre' },
        ],
      },
      {
        number: 3,
        name: 'Automate',
        objective: 'Deploy continuous compliance verification pipelines and automated policy gates.',
        exit_criteria: ['Automated policy verification gate runs on 100% of pull requests.'],
        milestones: [
          { id: 'M3-1', title: 'Integrate pre-merge compliance check gate in CI', role: 'developer' },
          { id: 'M3-2', title: 'Configure synthetic canary transactions with audit telemetry', role: 'sre' },
        ],
      },
      {
        number: 4,
        name: 'Self-Govern',
        objective: 'Achieve zero-touch compliance auditing with deterministic provenance records.',
        exit_criteria: ['Zero manual audit interventions required for continuous compliance reporting.'],
        milestones: [
          { id: 'M4-1', title: 'Enable self-healing policy enforcement bots', role: 'compliance-officer' },
          { id: 'M4-2', title: 'Certify autonomous compliance reporting dashboard', role: 'compliance-officer' },
        ],
      },
    ],
  },
  'playbook.ai-assurance': {
    playbook_id: 'playbook.ai-assurance',
    title: 'Algorithmic & AI Model Risk Governance Playbook',
    description: 'Operationalize SEBI algorithmic trading guidelines and RBI model governance requirements.',
    domain: 'ai-governance',
    total_stages: 4,
    stages: [
      {
        number: 1,
        name: 'Decouple / Establish',
        objective: 'Establish model inventory, baseline explainability standards, and kill switch mechanisms.',
        exit_criteria: ['Complete algorithmic inventory with signed-off model cards.'],
        milestones: [
          { id: 'M1-1', title: 'Register AI/ML models and data pipelines in catalog', role: 'data-scientist' },
          { id: 'M1-2', title: 'Implement automated kill switch and circuit breakers', role: 'sre' },
        ],
      },
      {
        number: 2,
        name: 'Bound / Contain',
        objective: 'Bound algorithmic risk through pre-trade price collars and latency monitors.',
        exit_criteria: ['Pre-trade risk controls verified across historical extreme volatility events.'],
        milestones: [
          { id: 'M2-1', title: 'Deploy TreeSHAP feature importance pipelines', role: 'data-scientist' },
          { id: 'M2-2', title: 'Implement order-to-trade ratio (OTR) rate limiters', role: 'developer' },
        ],
      },
      {
        number: 3,
        name: 'Automate',
        objective: 'Automate continuous drift detection and demographic fairness audits.',
        exit_criteria: ['Daily population stability index (PSI) monitoring active in production.'],
        milestones: [
          { id: 'M3-1', title: 'Automate daily concept drift and PSI calculations', role: 'data-scientist' },
          { id: 'M3-2', title: 'Configure alert triggers on adverse fairness metrics', role: 'compliance-officer' },
        ],
      },
      {
        number: 4,
        name: 'Self-Govern',
        objective: 'Establish independent algorithmic assurance and board audit reporting.',
        exit_criteria: ['Independent third-party model audit signed off by CERT-In auditor.'],
        milestones: [
          { id: 'M4-1', title: 'Generate statutory SEBI audit certificate report', role: 'compliance-officer' },
          { id: 'M4-2', title: 'Deliver annual model governance review to board', role: 'compliance-officer' },
        ],
      },
    ],
  },
  'playbook.vendor-risk': {
    playbook_id: 'playbook.vendor-risk',
    title: 'Third-Party Vendor Risk Assessment Playbook',
    description: 'Enforce statutory contractual safeguards and operational resilience for outsourcers.',
    domain: 'vendor-risk',
    total_stages: 4,
    stages: [
      {
        number: 1,
        name: 'Decouple / Establish',
        objective: 'Catalog all cloud, SaaS, and payment vendors and audit contract clauses.',
        exit_criteria: ['Vendor inventory completed with 100% contracts uploaded.'],
        milestones: [
          { id: 'M1-1', title: 'Extract all outsourcing contracts into structured catalog', role: 'procurement' },
          { id: 'M1-2', title: 'Map data localization and sub-contractor risks', role: 'compliance-officer' },
        ],
      },
      {
        number: 2,
        name: 'Bound / Contain',
        objective: 'Remediate missing audit rights and enforce step-in guarantees.',
        exit_criteria: ['Zero Tier-1 vendors operating without statutory audit clauses.'],
        milestones: [
          { id: 'M2-1', title: 'Execute addendum for RBI/SEBI regulatory inspection rights', role: 'legal' },
          { id: 'M2-2', title: 'Validate exit strategies and vendor transition plans', role: 'sre' },
        ],
      },
      {
        number: 3,
        name: 'Automate',
        objective: 'Automate vendor security posture monitoring and continuous SLA tracking.',
        exit_criteria: ['Continuous telemetry tracking vendor SOC2 and ISO certificates.'],
        milestones: [
          { id: 'M3-1', title: 'Deploy automated certificate expiry and breach monitors', role: 'security' },
          { id: 'M3-2', title: 'Implement SLA degradation circuit breakers', role: 'sre' },
        ],
      },
      {
        number: 4,
        name: 'Self-Govern',
        objective: 'Autonomous third-party risk rating and executive board dashboards.',
        exit_criteria: ['Annual vendor audit report certified by internal audit committee.'],
        milestones: [
          { id: 'M4-1', title: 'Certify high-risk vendor compliance ratings', role: 'compliance-officer' },
          { id: 'M4-2', title: 'Publish executive risk exposure summary', role: 'compliance-officer' },
        ],
      },
    ],
  },
}

export const PlaybookRuntimeView: React.FC<PlaybookRuntimeViewProps> = ({
  apiBaseUrl = '',
  apiKey = '',
  className = '',
  initialPlaybookId = 'playbook.foundations-30d',
  onRunUpdated,
}) => {
  const [selectedPlaybookId, setSelectedPlaybookId] = useState<string>(initialPlaybookId)
  const [tenantId, setTenantId] = useState<string>('tenant-default')
  const [assignedLead, setAssignedLead] = useState<string>('Chief Compliance Officer')
  const [activeRun, setActiveRun] = useState<PlaybookRunData | null>(null)
  const [milestoneNotes, setMilestoneNotes] = useState<Record<string, string>>({})
  const [evidenceDocIds, setEvidenceDocIds] = useState<Record<string, string>>({})
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [loading, setLoading] = useState<boolean>(false)

  const template = PRESET_TEMPLATES[selectedPlaybookId] || PRESET_TEMPLATES['playbook.foundations-30d']
  const currentStageNum = activeRun ? activeRun.current_stage : 1
  const currentStage = template.stages.find((s) => s.number === currentStageNum) || template.stages[0]

  // Calculate completed milestones for current active run
  const completedMilestoneIds = new Set<string>(
    activeRun?.stage_data?.completed_milestones
      ?.filter((m) => m.stage_number === currentStageNum)
      ?.map((m) => m.milestone_id) || []
  )

  const totalStageMilestones = currentStage.milestones.length
  const completedStageMilestones = currentStage.milestones.filter((m) =>
    completedMilestoneIds.has(m.id)
  ).length
  const stageProgressPct =
    totalStageMilestones > 0
      ? Math.round((completedStageMilestones / totalStageMilestones) * 100)
      : 0

  const handleStartPlaybook = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setErrorMessage(null)
    setSuccessMessage(null)

    try {
      if (apiBaseUrl) {
        const headers: Record<string, string> = { 'Content-Type': 'application/json' }
        if (apiKey) headers['X-API-Key'] = apiKey

        const resp = await fetch(`${apiBaseUrl}/v1/playbooks/start`, {
          method: 'POST',
          headers,
          body: JSON.stringify({
            playbook_id: selectedPlaybookId,
            tenant_id: tenantId,
            assigned_lead: assignedLead,
          }),
        })

        if (!resp.ok) {
          const err = await resp.json()
          throw new Error(err.detail || 'Failed to instantiate playbook run')
        }

        const data: PlaybookRunData = await resp.json()
        setActiveRun(data)
        if (onRunUpdated) onRunUpdated(data)
      } else {
        // Deterministic offline run simulation
        const mockRun: PlaybookRunData = {
          run_id: `run-${Date.now()}`,
          tenant_id: tenantId,
          playbook_id: template.playbook_id,
          title: template.title,
          assigned_lead: assignedLead,
          current_stage: 1,
          total_stages: template.total_stages,
          status: 'ACTIVE',
          stage_data: {
            completed_milestones: [],
            stage_history: [{ stage_number: 1, entered_at: new Date().toISOString(), status: 'ACTIVE' }],
          },
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }
        setActiveRun(mockRun)
        if (onRunUpdated) onRunUpdated(mockRun)
      }
      setSuccessMessage(`Instantiated active compliance run for ${template.title}`)
    } catch (err: unknown) {
      setErrorMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  const handleToggleMilestone = async (milestoneId: string) => {
    if (!activeRun) return
    setErrorMessage(null)
    setSuccessMessage(null)

    const notes = milestoneNotes[milestoneId] || 'Completed via compliance console'
    const evidenceDocId = evidenceDocIds[milestoneId] || null

    try {
      if (apiBaseUrl) {
        const headers: Record<string, string> = { 'Content-Type': 'application/json' }
        if (apiKey) headers['X-API-Key'] = apiKey

        const resp = await fetch(
          `${apiBaseUrl}/v1/playbooks/runs/${activeRun.run_id}/milestones/${milestoneId}?tenant_id=${tenantId}`,
          {
            method: 'POST',
            headers,
            body: JSON.stringify({
              milestone_id: milestoneId,
              evidence_doc_id: evidenceDocId,
              notes,
            }),
          }
        )

        if (!resp.ok) {
          const err = await resp.json()
          throw new Error(err.detail || 'Failed to record milestone')
        }

        const updated: PlaybookRunData = await resp.json()
        setActiveRun(updated)
        if (onRunUpdated) onRunUpdated(updated)
      } else {
        // Offline state update
        const updatedMilestones = [...activeRun.stage_data.completed_milestones]
        if (!updatedMilestones.some((m) => m.milestone_id === milestoneId && m.stage_number === currentStageNum)) {
          updatedMilestones.push({
            milestone_id: milestoneId,
            stage_number: currentStageNum,
            completed_at: new Date().toISOString(),
            evidence_doc_id: evidenceDocId,
            notes,
          })
        }
        const updatedRun: PlaybookRunData = {
          ...activeRun,
          stage_data: {
            ...activeRun.stage_data,
            completed_milestones: updatedMilestones,
          },
          updated_at: new Date().toISOString(),
        }
        setActiveRun(updatedRun)
        if (onRunUpdated) onRunUpdated(updatedRun)
      }
      setSuccessMessage(`Milestone ${milestoneId} recorded with statutory audit evidence.`)
    } catch (err: unknown) {
      setErrorMessage(err instanceof Error ? err.message : String(err))
    }
  }

  const handleAdvanceStage = async () => {
    if (!activeRun) return
    setErrorMessage(null)
    setSuccessMessage(null)

    // Verify exit criteria locally if offline
    if (completedStageMilestones < totalStageMilestones) {
      setErrorMessage(`Exit criteria for Stage ${currentStageNum} not yet satisfied. Complete all milestones first.`)
      return
    }

    setLoading(true)
    try {
      if (apiBaseUrl) {
        const headers: Record<string, string> = { 'Content-Type': 'application/json' }
        if (apiKey) headers['X-API-Key'] = apiKey

        const resp = await fetch(
          `${apiBaseUrl}/v1/playbooks/runs/${activeRun.run_id}/advance?tenant_id=${tenantId}`,
          {
            method: 'POST',
            headers,
            body: JSON.stringify({ target_stage: currentStageNum + 1 }),
          }
        )

        if (!resp.ok) {
          const err = await resp.json()
          throw new Error(err.detail || 'Failed to advance stage')
        }

        const data: PlaybookRunData = await resp.json()
        setActiveRun(data)
        if (onRunUpdated) onRunUpdated(data)
      } else {
        // Offline advance
        const nextStageNum = currentStageNum + 1
        const isComplete = nextStageNum > template.total_stages
        const updatedRun: PlaybookRunData = {
          ...activeRun,
          current_stage: isComplete ? template.total_stages : nextStageNum,
          status: isComplete ? 'COMPLETED' : 'ACTIVE',
          updated_at: new Date().toISOString(),
        }
        setActiveRun(updatedRun)
        if (onRunUpdated) onRunUpdated(updatedRun)
      }
      setSuccessMessage(
        currentStageNum >= template.total_stages
          ? `Playbook run completed successfully! 100% compliance certified.`
          : `Advanced to Stage ${currentStageNum + 1}.`
      )
    } catch (err: unknown) {
      setErrorMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      data-testid="playbook-runtime-container"
      className={`rounded-xl border border-slate-800 bg-slate-900 p-6 text-slate-100 shadow-2xl ${className}`}
    >
      {/* Header */}
      <div className="mb-6 flex flex-col justify-between gap-4 border-b border-slate-800 pb-5 md:flex-row md:items-center">
        <div>
          <div className="flex items-center gap-3">
            <span className="flex h-3 w-3 rounded-full bg-cyan-400 ring-4 ring-cyan-950 animate-pulse" />
            <h2 className="text-xl font-bold tracking-tight text-white">Interactive Compliance Playbook Runtime</h2>
            <span className="rounded bg-cyan-950/80 px-2 py-0.5 text-xs font-semibold text-cyan-300 border border-cyan-800">
              FEAT-051
            </span>
          </div>
          <p className="mt-1 text-sm text-slate-400">
            State-machine workflow guidance operationalizing 12 statutory compliance playbooks across 4 sequential stages.
          </p>
        </div>

        {activeRun && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">Status:</span>
            <span
              data-testid="playbook-status-badge"
              className={`rounded-full px-3 py-1 text-xs font-bold uppercase tracking-wider ${
                activeRun.status === 'COMPLETED'
                  ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                  : activeRun.status === 'BLOCKED'
                  ? 'bg-rose-950 text-rose-400 border border-rose-800'
                  : 'bg-cyan-950 text-cyan-400 border border-cyan-800'
              }`}
            >
              {activeRun.status}
            </span>
          </div>
        )}
      </div>

      {/* Playbook Configuration & Selector */}
      <form onSubmit={handleStartPlaybook} className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-3">
        <div>
          <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">
            Statutory Playbook
          </label>
          <select
            data-testid="playbook-select"
            value={selectedPlaybookId}
            onChange={(e) => setSelectedPlaybookId(e.target.value)}
            disabled={activeRun !== null && activeRun.status === 'ACTIVE'}
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-white focus:border-cyan-500 focus:outline-none"
          >
            {Object.values(PRESET_TEMPLATES).map((tmpl) => (
              <option key={tmpl.playbook_id} value={tmpl.playbook_id}>
                {tmpl.title} ({tmpl.domain})
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">
            Tenant Isolation ID
          </label>
          <input
            data-testid="tenant-id-input"
            type="text"
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            disabled={activeRun !== null && activeRun.status === 'ACTIVE'}
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-white focus:border-cyan-500 focus:outline-none"
          />
        </div>

        <div>
          <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">
            Assigned Compliance Lead
          </label>
          <div className="flex gap-2">
            <input
              data-testid="assigned-lead-input"
              type="text"
              value={assignedLead}
              onChange={(e) => setAssignedLead(e.target.value)}
              disabled={activeRun !== null && activeRun.status === 'ACTIVE'}
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-white focus:border-cyan-500 focus:outline-none"
            />
            {!activeRun ? (
              <button
                data-testid="start-playbook-button"
                type="submit"
                disabled={loading}
                className="rounded-lg bg-cyan-600 px-4 py-2 text-xs font-bold text-white hover:bg-cyan-500 transition-colors whitespace-nowrap disabled:opacity-50"
              >
                {loading ? 'Instantiating...' : 'Start Run'}
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setActiveRun(null)}
                className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs font-semibold text-slate-300 hover:bg-slate-700 transition-colors whitespace-nowrap"
              >
                Reset
              </button>
            )}
          </div>
        </div>
      </form>

      {/* Alerts */}
      {errorMessage && (
        <div data-testid="error-alert" className="mb-4 rounded-lg border border-rose-800/80 bg-rose-950/40 p-3 text-xs text-rose-300">
          <strong>Validation Block: </strong> {errorMessage}
        </div>
      )}
      {successMessage && (
        <div data-testid="success-alert" className="mb-4 rounded-lg border border-emerald-800/80 bg-emerald-950/40 p-3 text-xs text-emerald-300">
          {successMessage}
        </div>
      )}

      {/* 4-Stage Progressive Stepper */}
      <div className="mb-6 rounded-lg border border-slate-800 bg-slate-950/60 p-4">
        <div className="mb-3 flex justify-between items-center">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Progressive 4-Stage Lifecycle
          </span>
          <span className="text-xs text-cyan-400 font-mono">
            Stage {currentStageNum} of {template.total_stages}
          </span>
        </div>

        <div data-testid="playbook-stage-stepper" className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {template.stages.map((stage) => {
            const isCompleted = activeRun ? stage.number < currentStageNum || activeRun.status === 'COMPLETED' : false
            const isActive = activeRun ? stage.number === currentStageNum && activeRun.status === 'ACTIVE' : stage.number === 1

            return (
              <div
                key={stage.number}
                data-testid={`stage-item-${stage.number}`}
                className={`rounded-lg border p-3 transition-all ${
                  isActive
                    ? 'border-cyan-500 bg-cyan-950/30 ring-1 ring-cyan-500/50'
                    : isCompleted
                    ? 'border-emerald-800/80 bg-emerald-950/20'
                    : 'border-slate-800 bg-slate-900/60 opacity-60'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-mono font-bold text-slate-400">Stage {stage.number}</span>
                  {isCompleted && (
                    <span className="text-xs font-bold text-emerald-400">Done ✓</span>
                  )}
                  {isActive && (
                    <span className="text-xs font-bold text-cyan-400 animate-pulse">Active ●</span>
                  )}
                </div>
                <h4 className="mt-1 text-sm font-semibold text-white">{stage.name}</h4>
              </div>
            )
          })}
        </div>
      </div>

      {/* Active Stage Details & Milestone Checklist */}
      <div className="rounded-lg border border-slate-800 bg-slate-950/80 p-5">
        <div className="mb-4 flex flex-col justify-between gap-2 border-b border-slate-800 pb-3 md:flex-row md:items-center">
          <div>
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              <span>Stage {currentStage.number}: {currentStage.name}</span>
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">{currentStage.objective}</p>
          </div>

          <div className="flex items-center gap-3">
            <div className="text-right">
              <span className="text-xs text-slate-400">Exit Criteria Readiness:</span>
              <span
                data-testid="stage-completion-meter"
                className="ml-2 font-mono text-xs font-bold text-cyan-300"
              >
                {completedStageMilestones} / {totalStageMilestones} ({stageProgressPct}%)
              </span>
            </div>
            <div className="h-2 w-24 rounded-full bg-slate-800 overflow-hidden">
              <div
                className={`h-full transition-all duration-300 ${
                  stageProgressPct === 100 ? 'bg-emerald-500' : 'bg-cyan-500'
                }`}
                style={{ width: `${stageProgressPct}%` }}
              />
            </div>
          </div>
        </div>

        {/* Exit Criteria Banner */}
        <div className="mb-4 rounded-md border border-cyan-900/50 bg-cyan-950/30 p-2.5 text-xs text-cyan-200">
          <span className="font-semibold text-cyan-400">Exit Criteria: </span>
          {currentStage.exit_criteria.join(' ')}
        </div>

        {/* Milestones Checklist */}
        <div className="space-y-3">
          <span className="block text-xs font-semibold uppercase tracking-wider text-slate-400">
            Stage Milestones & Statutory Deliverables
          </span>

          {currentStage.milestones.map((milestone) => {
            const isCompleted = completedMilestoneIds.has(milestone.id)

            return (
              <div
                key={milestone.id}
                data-testid={`milestone-row-${milestone.id}`}
                className={`flex flex-col gap-2 rounded-lg border p-3 transition-colors md:flex-row md:items-center md:justify-between ${
                  isCompleted
                    ? 'border-emerald-900/80 bg-emerald-950/20 text-slate-300'
                    : 'border-slate-800 bg-slate-900 text-slate-200 hover:border-slate-700'
                }`}
              >
                <div className="flex items-start gap-3">
                  <input
                    data-testid={`milestone-checkbox-${milestone.id}`}
                    type="checkbox"
                    checked={isCompleted}
                    onChange={() => handleToggleMilestone(milestone.id)}
                    disabled={!activeRun || activeRun.status === 'COMPLETED'}
                    className="mt-1 h-4 w-4 rounded border-slate-700 bg-slate-800 text-cyan-600 focus:ring-cyan-500"
                  />
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-bold text-cyan-400">{milestone.id}</span>
                      <span className="text-sm font-medium text-white">{milestone.title}</span>
                    </div>
                    <span className="text-xs text-slate-400">Responsible Role: {milestone.role}</span>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    placeholder="Evidence Doc ID (e.g. ADR-0042)"
                    value={evidenceDocIds[milestone.id] || ''}
                    onChange={(e) =>
                      setEvidenceDocIds({ ...evidenceDocIds, [milestone.id]: e.target.value })
                    }
                    disabled={isCompleted}
                    className="w-40 rounded border border-slate-700 bg-slate-800 px-2 py-1 text-xs text-slate-200 placeholder-slate-500 focus:border-cyan-500 focus:outline-none"
                  />
                  <input
                    type="text"
                    placeholder="Audit verification note..."
                    value={milestoneNotes[milestone.id] || ''}
                    onChange={(e) =>
                      setMilestoneNotes({ ...milestoneNotes, [milestone.id]: e.target.value })
                    }
                    disabled={isCompleted}
                    className="w-48 rounded border border-slate-700 bg-slate-800 px-2 py-1 text-xs text-slate-200 placeholder-slate-500 focus:border-cyan-500 focus:outline-none"
                  />
                </div>
              </div>
            )
          })}
        </div>

        {/* Advance Action Button */}
        <div className="mt-6 flex justify-end border-t border-slate-800 pt-4">
          <button
            data-testid="advance-stage-button"
            type="button"
            onClick={handleAdvanceStage}
            disabled={!activeRun || activeRun.status === 'COMPLETED' || loading}
            className={`rounded-lg px-5 py-2.5 text-xs font-bold text-white transition-all shadow-lg ${
              stageProgressPct === 100
                ? 'bg-emerald-600 hover:bg-emerald-500 ring-2 ring-emerald-500/50'
                : 'bg-cyan-600 hover:bg-cyan-500'
            } disabled:opacity-40 disabled:cursor-not-allowed`}
          >
            {loading
              ? 'Promoting Stage...'
              : activeRun && currentStageNum >= template.total_stages
              ? 'Certify & Complete Playbook'
              : `Advance to Stage ${currentStageNum + 1} →`}
          </button>
        </div>
      </div>
    </div>
  )
}

export default PlaybookRuntimeView
