import React, { useState, useMemo } from 'react'
import {
  usePlaybooks,
  type UsePlaybooksOptions,
} from '../hooks/usePlaybooks'

export interface PlaybookConsoleProps extends UsePlaybooksOptions {
  className?: string
  onStagePromoted?: (newStage: number) => void
}

export const PlaybookConsole: React.FC<PlaybookConsoleProps> = ({
  runId,
  tenantId = 'default',
  apiBaseUrl = '',
  apiKey = '',
  refreshIntervalSeconds = 30,
  initialRun,
  className = '',
  onStagePromoted,
}) => {
  const {
    activeRun,
    templates,
    currentStage,
    allStages,
    error,
    overallProgressPct,
    stageProgressPct,
    isExitCriteriaSatisfied,
    completeMilestone,
    promoteStage,
    selectPlaybook,
    exportAuditSummary,
  } = usePlaybooks({
    runId,
    tenantId,
    apiBaseUrl,
    apiKey,
    refreshIntervalSeconds,
    initialRun,
  })

  const [selectedRole, setSelectedRole] = useState<string>('ALL')
  const [copiedExport, setCopiedExport] = useState<boolean>(false)
  const [promoting, setPromoting] = useState<boolean>(false)
  const [promoteError, setPromoteError] = useState<string | null>(null)
  const [selectedStageTab, setSelectedStageTab] = useState<number | null>(null)

  // Determine stage to inspect (either selected tab or current stage)
  const inspectedStage = useMemo(() => {
    if (selectedStageTab !== null) {
      return allStages.find((s) => s.number === selectedStageTab) || currentStage
    }
    return currentStage
  }, [allStages, selectedStageTab, currentStage])

  // Filter milestones by role
  const filteredMilestones = useMemo(() => {
    if (!inspectedStage) return []
    if (selectedRole === 'ALL') return inspectedStage.milestones
    return inspectedStage.milestones.filter(
      (m) => m.role.toLowerCase() === selectedRole.toLowerCase()
    )
  }, [inspectedStage, selectedRole])

  // Unique roles across current inspected stage
  const availableRoles = useMemo(() => {
    if (!inspectedStage) return ['ALL']
    const roles = Array.from(new Set(inspectedStage.milestones.map((m) => m.role)))
    return ['ALL', ...roles]
  }, [inspectedStage])

  const handlePromote = async () => {
    setPromoting(true)
    setPromoteError(null)
    const res = await promoteStage()
    setPromoting(false)
    if (res.success && activeRun) {
      if (onStagePromoted) {
        onStagePromoted(activeRun.current_stage + 1)
      }
    } else if (res.error) {
      setPromoteError(res.error)
    }
  }

  const handleExport = () => {
    const summary = exportAuditSummary()
    navigator.clipboard?.writeText?.(summary)
    setCopiedExport(true)
    setTimeout(() => setCopiedExport(false), 2500)
  }

  const handlePlaybookChange = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedStageTab(null)
    await selectPlaybook(e.target.value)
  }

  // Circular SVG ring helper
  const renderProgressRing = (pct: number, size: number = 72, strokeWidth: number = 6) => {
    const radius = (size - strokeWidth) / 2
    const circumference = 2 * Math.PI * radius
    const offset = circumference - (pct / 100) * circumference

    return (
      <div className="relative inline-flex items-center justify-center">
        <svg width={size} height={size} className="transform -rotate-90">
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            stroke="currentColor"
            strokeWidth={strokeWidth}
            className="text-slate-800"
            fill="transparent"
          />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            stroke="currentColor"
            strokeWidth={strokeWidth}
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            strokeLinecap="round"
            className={`transition-all duration-700 ${
              pct === 100
                ? 'text-emerald-500'
                : pct >= 50
                ? 'text-indigo-500'
                : 'text-amber-500'
            }`}
            fill="transparent"
          />
        </svg>
        <div className="absolute text-center">
          <span className="text-sm font-bold text-white font-mono">{pct}%</span>
        </div>
      </div>
    )
  }

  if (!activeRun) {
    return (
      <div
        data-testid="playbook-console"
        className="bg-slate-950 text-slate-100 rounded-xl border border-slate-800 p-8 text-center"
      >
        <p className="text-slate-400">Loading enterprise playbook console...</p>
      </div>
    )
  }

  return (
    <div
      data-testid="playbook-console"
      className={`bg-slate-950 text-slate-100 rounded-xl border border-slate-800 p-6 shadow-2xl ${className}`}
    >
      {/* Header Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-slate-800">
        <div>
          <div className="flex items-center gap-3">
            <span className="inline-flex items-center justify-center p-2 rounded-lg bg-indigo-950 border border-indigo-800 text-indigo-400">
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
              </svg>
            </span>
            <div>
              <h2 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                Playbook Progress Dashboard
                <span
                  className={`text-xs px-2.5 py-0.5 rounded-full font-mono font-bold border ${
                    activeRun.status === 'COMPLETED'
                      ? 'bg-emerald-950/80 text-emerald-400 border-emerald-800'
                      : activeRun.status === 'ACTIVE'
                      ? 'bg-cyan-950/80 text-cyan-400 border-cyan-800'
                      : 'bg-rose-950/80 text-rose-400 border-rose-800'
                  }`}
                >
                  {activeRun.status}
                </span>
              </h2>
              <p className="text-sm text-slate-400">
                Multi-stage regulatory milestone execution, role-based allocations, and exit gate validation
              </p>
            </div>
          </div>
        </div>

        {/* Playbook Selector & Actions */}
        <div className="flex flex-wrap items-center gap-3">
          <select
            id="playbook-select-dropdown"
            data-testid="playbook-select"
            value={activeRun.playbook_id}
            onChange={handlePlaybookChange}
            className="bg-slate-900 border border-slate-700 text-sm rounded-lg px-3 py-2 text-white focus:outline-none focus:border-indigo-500 font-medium"
          >
            {templates.map((t) => (
              <option key={t.playbook_id} value={t.playbook_id}>
                {t.title}
              </option>
            ))}
          </select>

          <button
            type="button"
            data-testid="export-summary-btn"
            onClick={handleExport}
            className="px-3.5 py-2 text-sm font-medium rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-700 text-slate-200 transition-colors flex items-center gap-1.5"
            title="Copy audit-ready markdown summary to clipboard"
          >
            <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
            {copiedExport ? 'Copied Report!' : 'Export Report'}
          </button>
        </div>
      </div>

      {/* Error alert if fetch or promote failed */}
      {(error || promoteError) && (
        <div className="my-4 p-3 bg-rose-950/60 border border-rose-900 rounded-lg text-rose-300 text-sm flex items-center justify-between">
          <span>{promoteError || error}</span>
          <button
            type="button"
            onClick={() => setPromoteError(null)}
            className="text-rose-400 hover:text-rose-200 text-xs font-bold"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Progress Gauges & Stage Overview */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 my-6">
        {/* Overall Progress Gauge */}
        <div
          data-testid="overall-progress-ring"
          className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 flex items-center gap-5"
        >
          {renderProgressRing(overallProgressPct, 76, 7)}
          <div>
            <div className="text-xs font-medium text-slate-400 uppercase tracking-wider">
              Overall Playbook Progress
            </div>
            <div className="text-xl font-bold text-white mt-1">
              Stage {activeRun.current_stage} of {activeRun.total_stages}
            </div>
            <div className="text-xs text-slate-400 mt-0.5">
              {activeRun.stage_data.completed_milestones.length} milestones complete
            </div>
          </div>
        </div>

        {/* Current Stage Progress Gauge */}
        <div
          data-testid="stage-progress-ring"
          className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 flex items-center gap-5"
        >
          {renderProgressRing(stageProgressPct, 76, 7)}
          <div>
            <div className="text-xs font-medium text-slate-400 uppercase tracking-wider">
              Active Stage Progress
            </div>
            <div className="text-xl font-bold text-white mt-1">
              {currentStage ? currentStage.name : `Stage ${activeRun.current_stage}`}
            </div>
            <div className="text-xs text-slate-400 mt-0.5">
              {currentStage
                ? `${currentStage.milestones.filter((m) => m.completed).length} of ${
                    currentStage.milestones.length
                  } complete`
                : ''}
            </div>
          </div>
        </div>

        {/* Lead & Tenant Metadata */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 flex flex-col justify-between">
          <div>
            <div className="text-xs font-medium text-slate-400 uppercase tracking-wider">
              Governance Lead & Tenant
            </div>
            <div className="text-base font-semibold text-indigo-300 mt-1">
              {activeRun.assigned_lead}
            </div>
            <div className="text-xs font-mono text-slate-400 mt-1">
              Tenant: <span className="text-slate-300">{activeRun.tenant_id}</span>
            </div>
          </div>
          <div className="text-xs text-slate-500 font-mono">
            Run ID: {activeRun.run_id}
          </div>
        </div>
      </div>

      {/* 4-Stage Progressive Workflow Stepper */}
      <div data-testid="stage-stepper" className="my-6">
        <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
          Workflow Stage Lifecycle
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {allStages.map((stage) => {
            const isCurrent = stage.number === activeRun.current_stage
            const isPast = stage.number < activeRun.current_stage
            const isInspected = inspectedStage?.number === stage.number

            return (
              <button
                key={stage.number}
                type="button"
                data-testid={`stage-step-${stage.number}`}
                onClick={() => setSelectedStageTab(stage.number)}
                className={`p-3.5 rounded-lg border text-left transition-all ${
                  isInspected
                    ? 'ring-2 ring-indigo-500 border-indigo-500 bg-indigo-950/40'
                    : 'bg-slate-900 border-slate-800 hover:border-slate-700'
                }`}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs font-mono text-slate-400">
                    Stage {stage.number}
                  </span>
                  {isPast ? (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-950 border border-emerald-800 text-emerald-400 font-bold">
                      COMPLETED
                    </span>
                  ) : isCurrent ? (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-950 border border-indigo-800 text-indigo-300 font-bold">
                      ACTIVE
                    </span>
                  ) : (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 font-mono">
                      LOCKED
                    </span>
                  )}
                </div>
                <div className="font-semibold text-sm text-white truncate">
                  {stage.name}
                </div>
                <div className="text-xs text-slate-400 mt-1 flex items-center justify-between">
                  <span>
                    {stage.milestones.filter((m) => m.completed).length} /{' '}
                    {stage.milestones.length}
                  </span>
                  <span className="font-mono text-[11px]">
                    {Math.round(
                      (stage.milestones.filter((m) => m.completed).length /
                        (stage.milestones.length || 1)) *
                        100
                    )}
                    %
                  </span>
                </div>
              </button>
            )
          })}
        </div>
      </div>

      {/* Stage Detail & Milestone Checklist */}
      {inspectedStage && (
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5 mt-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-800">
            <div>
              <div className="text-xs font-mono text-indigo-400">
                Inspecting Stage {inspectedStage.number}: {inspectedStage.name}
              </div>
              <p className="text-sm text-slate-300 mt-0.5">{inspectedStage.objective}</p>
            </div>

            {/* Role Filter Toggles */}
            <div data-testid="role-filter" className="flex items-center gap-1.5 flex-wrap">
              <span className="text-xs text-slate-400 mr-1">Role:</span>
              {availableRoles.map((role) => (
                <button
                  key={role}
                  type="button"
                  onClick={() => setSelectedRole(role)}
                  className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                    selectedRole === role
                      ? 'bg-indigo-600 text-white'
                      : 'bg-slate-800 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {role.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          {/* Exit Criteria Banner */}
          <div
            data-testid="exit-criteria-banner"
            className={`my-4 p-3.5 rounded-lg border flex flex-col sm:flex-row sm:items-center justify-between gap-3 ${
              isExitCriteriaSatisfied
                ? 'bg-emerald-950/30 border-emerald-900/60 text-emerald-300'
                : 'bg-amber-950/30 border-amber-900/60 text-amber-300'
            }`}
          >
            <div>
              <div className="text-xs font-bold uppercase tracking-wider mb-1 flex items-center gap-1.5">
                {isExitCriteriaSatisfied ? (
                  <>
                    <svg className="w-4 h-4 text-emerald-400" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                    </svg>
                    Stage Exit Criteria Satisfied
                  </>
                ) : (
                  <>
                    <svg className="w-4 h-4 text-amber-400" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                    </svg>
                    Active Stage Exit Criteria Gate
                  </>
                )}
              </div>
              <ul className="text-xs space-y-0.5 list-disc list-inside">
                {inspectedStage.exit_criteria.map((crit, idx) => (
                  <li key={idx}>{crit}</li>
                ))}
              </ul>
            </div>

            {/* Advance Button (only enabled if inspecting active stage) */}
            {inspectedStage.number === activeRun.current_stage &&
              activeRun.current_stage < activeRun.total_stages && (
                <button
                  type="button"
                  data-testid="promote-stage-btn"
                  onClick={handlePromote}
                  disabled={!isExitCriteriaSatisfied || promoting}
                  className="px-4 py-2 text-sm font-semibold rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white transition-colors shrink-0 shadow-lg shadow-indigo-950/40"
                >
                  {promoting
                    ? 'Validating Gate...'
                    : `Promote to Stage ${activeRun.current_stage + 1}`}
                </button>
              )}
          </div>

          {/* Interactive Milestone Checklist */}
          <div data-testid="milestones-checklist" className="space-y-2.5 mt-4">
            <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
              Stage Milestones ({filteredMilestones.length})
            </div>

            {filteredMilestones.length === 0 ? (
              <div className="text-xs text-slate-500 italic p-3 text-center">
                No milestones match the selected role filter.
              </div>
            ) : (
              filteredMilestones.map((m) => (
                <div
                  key={m.id}
                  data-testid={`milestone-row-${m.id}`}
                  className={`p-3.5 rounded-lg border transition-colors flex items-center justify-between gap-3 ${
                    m.completed
                      ? 'bg-slate-900/90 border-slate-700/80'
                      : 'bg-slate-950/60 border-slate-800 hover:border-slate-700'
                  }`}
                >
                  <label
                    htmlFor={`milestone-chk-${m.id}`}
                    className="flex items-center gap-3 cursor-pointer flex-1"
                  >
                    <input
                      id={`milestone-chk-${m.id}`}
                      type="checkbox"
                      data-testid={`milestone-checkbox-${m.id}`}
                      checked={!!m.completed}
                      onChange={() => completeMilestone(m.id)}
                      className="w-4 h-4 rounded text-indigo-600 bg-slate-900 border-slate-700 focus:ring-indigo-500 focus:ring-offset-slate-950 cursor-pointer"
                    />
                    <div>
                      <div
                        className={`text-sm font-medium ${
                          m.completed
                            ? 'line-through text-slate-400'
                            : 'text-white'
                        }`}
                      >
                        {m.title}
                      </div>
                      <div className="text-xs font-mono text-slate-500 flex items-center gap-2 mt-0.5">
                        <span>ID: {m.id}</span>
                        <span className="text-slate-600">•</span>
                        <span className="px-1.5 py-0.2 rounded bg-slate-800 text-slate-300 uppercase font-semibold text-[10px]">
                          {m.role}
                        </span>
                      </div>
                    </div>
                  </label>

                  <div className="flex items-center gap-2">
                    {m.completed ? (
                      <span className="text-xs text-emerald-400 font-semibold px-2 py-0.5 rounded bg-emerald-950/60 border border-emerald-800">
                        Completed
                      </span>
                    ) : (
                      <span className="text-xs text-amber-400 font-semibold px-2 py-0.5 rounded bg-amber-950/40 border border-amber-900/60">
                        Pending
                      </span>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* Footer Details */}
      <div className="mt-6 pt-4 border-t border-slate-800 flex flex-col sm:flex-row justify-between items-center text-xs text-slate-500">
        <div>
          Last updated:{' '}
          <span className="font-mono text-slate-400">
            {new Date(activeRun.updated_at).toLocaleString()}
          </span>
        </div>
        <div>DocScout Enterprise-100 Playbook Progress Console (FEAT-059)</div>
      </div>
    </div>
  )
}
export default PlaybookConsole
