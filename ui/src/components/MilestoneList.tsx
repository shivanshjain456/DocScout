import React, { useState } from 'react'

export interface MilestoneItemData {
  id: string
  title: string
  role: string
  mandatory?: boolean
  completed?: boolean
  evidence_doc_id?: string | null
  notes?: string
}

export interface StageProgressData {
  stage_number: number
  stage_name: string
  total_milestones: number
  completed_milestones: number
  completion_ratio: number
  exit_ready: boolean
}

export interface MilestoneListProps {
  runId?: string
  stageNumber?: number
  stageName?: string
  tenantId?: string
  apiBaseUrl?: string
  apiKey?: string
  className?: string
  initialMilestones?: MilestoneItemData[]
  onProgressChanged?: (progress: StageProgressData) => void
}

const DEFAULT_STAGE_1_MILESTONES: MilestoneItemData[] = [
  {
    id: 'M1-1',
    title: 'Map database dependencies and domain boundary edges',
    role: 'sre',
    mandatory: true,
    completed: false,
  },
  {
    id: 'M1-2',
    title: 'Draft architectural decoupling ADR and API contracts',
    role: 'developer',
    mandatory: true,
    completed: false,
  },
]

export const MilestoneList: React.FC<MilestoneListProps> = ({
  runId = 'mock-run-001',
  stageNumber = 1,
  stageName = 'Decouple / Establish',
  tenantId = 'default',
  apiBaseUrl = '',
  apiKey = '',
  className = '',
  initialMilestones = DEFAULT_STAGE_1_MILESTONES,
  onProgressChanged,
}) => {
  const [milestones, setMilestones] = useState<MilestoneItemData[]>(initialMilestones)
  const [evidenceInputs, setEvidenceInputs] = useState<Record<string, string>>({})
  const [notesInputs, setNotesInputs] = useState<Record<string, string>>({})
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [submittingId, setSubmittingId] = useState<string | null>(null)

  const totalCount = milestones.length
  const completedCount = milestones.filter((m) => m.completed).length
  const completionRatio = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 100
  const isExitReady = totalCount > 0 && completedCount >= totalCount

  const handleCompleteMilestone = async (milestoneId: string) => {
    const notes = (notesInputs[milestoneId] || '').trim()
    const evidenceDocId = (evidenceInputs[milestoneId] || '').trim() || null

    if (notes.length < 10) {
      setErrorMessage(`Verification notes must be at least 10 characters long (entered: ${notes.length}).`)
      return
    }

    setSubmittingId(milestoneId)
    setErrorMessage(null)
    setSuccessMessage(null)

    try {
      if (apiBaseUrl) {
        const headers: Record<string, string> = { 'Content-Type': 'application/json' }
        if (apiKey) headers['X-API-Key'] = apiKey

        const resp = await fetch(
          `${apiBaseUrl}/v1/playbooks/${runId}/milestones/${milestoneId}?tenant_id=${tenantId}`,
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
          const errData = await resp.json()
          throw new Error(errData.detail || 'Failed to complete milestone')
        }

        const progressData: StageProgressData = await resp.json()
        if (onProgressChanged) onProgressChanged(progressData)
      }

      // Update local state
      const updated = milestones.map((m) =>
        m.id === milestoneId
          ? { ...m, completed: true, evidence_doc_id: evidenceDocId, notes }
          : m
      )
      setMilestones(updated)
      setSuccessMessage(`Milestone ${milestoneId} completed and audit evidence recorded.`)

      if (!apiBaseUrl && onProgressChanged) {
        const updatedCompleted = updated.filter((m) => m.completed).length
        onProgressChanged({
          stage_number: stageNumber,
          stage_name: stageName,
          total_milestones: totalCount,
          completed_milestones: updatedCompleted,
          completion_ratio: totalCount > 0 ? updatedCompleted / totalCount : 1.0,
          exit_ready: updatedCompleted >= totalCount,
        })
      }
    } catch (err: unknown) {
      setErrorMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmittingId(null)
    }
  }

  return (
    <div
      data-testid="milestone-list-container"
      className={`rounded-xl border border-slate-800 bg-slate-900 p-5 text-slate-100 shadow-xl ${className}`}
    >
      {/* Stage Header */}
      <div className="mb-4 flex flex-col justify-between gap-3 border-b border-slate-800 pb-4 md:flex-row md:items-center">
        <div>
          <div className="flex items-center gap-2">
            <span className="rounded bg-indigo-950 px-2 py-0.5 font-mono text-xs font-bold text-indigo-300 border border-indigo-800">
              Stage {stageNumber}
            </span>
            <h3 className="text-lg font-bold text-white">{stageName}</h3>
          </div>
          <p className="mt-1 text-xs text-slate-400">
            Granular deliverable checklist and statutory grounding evidence records.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="text-right">
            <div className="text-xs text-slate-400">Deliverables Complete:</div>
            <div data-testid="stage-progress-ratio" className="font-mono text-xs font-bold text-cyan-300">
              {completedCount} / {totalCount} ({completionRatio}%)
            </div>
          </div>

          <span
            data-testid="stage-exit-badge"
            className={`rounded-full px-3 py-1 text-xs font-bold uppercase tracking-wider border ${
              isExitReady
                ? 'bg-emerald-950/80 text-emerald-400 border-emerald-800'
                : 'bg-amber-950/80 text-amber-400 border-amber-800'
            }`}
          >
            {isExitReady ? 'Exit Ready ✓' : 'Prerequisites Incomplete ●'}
          </span>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="mb-5 h-2 w-full overflow-hidden rounded-full bg-slate-800">
        <div
          className={`h-full transition-all duration-300 ${
            isExitReady ? 'bg-emerald-500' : 'bg-cyan-500'
          }`}
          style={{ width: `${completionRatio}%` }}
        />
      </div>

      {/* Alerts */}
      {errorMessage && (
        <div
          data-testid="milestone-error-alert"
          className="mb-4 rounded-lg border border-rose-800/80 bg-rose-950/40 p-3 text-xs text-rose-300"
        >
          <strong>Validation Block: </strong> {errorMessage}
        </div>
      )}
      {successMessage && (
        <div
          data-testid="milestone-success-alert"
          className="mb-4 rounded-lg border border-emerald-800/80 bg-emerald-950/40 p-3 text-xs text-emerald-300"
        >
          {successMessage}
        </div>
      )}

      {/* Milestones List */}
      <div className="space-y-3">
        {milestones.map((milestone) => {
          const isDone = milestone.completed
          const currentNotes = notesInputs[milestone.id] ?? (milestone.notes || '')
          const currentEvidence = evidenceInputs[milestone.id] ?? (milestone.evidence_doc_id || '')

          return (
            <div
              key={milestone.id}
              data-testid={`milestone-item-${milestone.id}`}
              className={`rounded-lg border p-4 transition-colors ${
                isDone
                  ? 'border-emerald-900/60 bg-emerald-950/20'
                  : 'border-slate-800 bg-slate-950/60 hover:border-slate-700'
              }`}
            >
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div className="flex items-start gap-3">
                  <input
                    data-testid={`milestone-check-${milestone.id}`}
                    type="checkbox"
                    checked={isDone}
                    disabled={isDone}
                    onChange={() => handleCompleteMilestone(milestone.id)}
                    className="mt-1 h-4 w-4 rounded border-slate-700 bg-slate-800 text-cyan-600 focus:ring-cyan-500"
                  />
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-bold text-cyan-400">{milestone.id}</span>
                      <span className="text-sm font-semibold text-white">{milestone.title}</span>
                      <span className="rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-400">
                        {milestone.role}
                      </span>
                    </div>

                    {isDone && milestone.notes && (
                      <p className="mt-1 text-xs text-slate-400 italic">
                        Verified: {milestone.notes}
                        {milestone.evidence_doc_id && (
                          <span className="ml-2 font-mono text-cyan-400">[{milestone.evidence_doc_id}]</span>
                        )}
                      </p>
                    )}
                  </div>
                </div>

                {!isDone && (
                  <div className="flex flex-col gap-2 md:flex-row md:items-center">
                    <input
                      data-testid={`milestone-evidence-input-${milestone.id}`}
                      type="text"
                      placeholder="Evidence Doc ID (e.g. ADR-0043)"
                      value={currentEvidence}
                      onChange={(e) =>
                        setEvidenceInputs({ ...evidenceInputs, [milestone.id]: e.target.value })
                      }
                      className="w-48 rounded border border-slate-700 bg-slate-800 px-2.5 py-1.5 text-xs text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none"
                    />

                    <input
                      data-testid={`milestone-notes-input-${milestone.id}`}
                      type="text"
                      placeholder="Audit note (min 10 chars)..."
                      value={currentNotes}
                      onChange={(e) =>
                        setNotesInputs({ ...notesInputs, [milestone.id]: e.target.value })
                      }
                      className="w-56 rounded border border-slate-700 bg-slate-800 px-2.5 py-1.5 text-xs text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none"
                    />

                    <button
                      data-testid={`milestone-submit-btn-${milestone.id}`}
                      type="button"
                      disabled={submittingId === milestone.id}
                      onClick={() => handleCompleteMilestone(milestone.id)}
                      className="rounded bg-cyan-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-cyan-500 transition-colors whitespace-nowrap disabled:opacity-50"
                    >
                      {submittingId === milestone.id ? 'Recording...' : 'Sign Off'}
                    </button>
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default MilestoneList
