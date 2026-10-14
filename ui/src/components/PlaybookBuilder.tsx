import React, { useState, useMemo } from 'react'

export interface CustomMilestone {
  id: string
  title: string
  role: string
  mandatory: boolean
  estimated_hours: number
}

export interface CustomStage {
  stage_number: number
  stage_name: string
  description: string
  milestones: CustomMilestone[]
  exit_criteria: string[]
}

export interface CustomPlaybook {
  id: string
  name: string
  goal: string
  domain: string
  stages: CustomStage[]
  metadata?: Record<string, any>
}

export interface PlaybookBuilderProps {
  tenantId?: string
  apiBaseUrl?: string
  apiKey?: string
  className?: string
  initialPlaybook?: CustomPlaybook
  onPlaybookCreated?: (templateId: string) => void
}

const DEFAULT_INITIAL_PLAYBOOK: CustomPlaybook = {
  id: 'playbook.custom-enterprise-audit',
  name: 'Enterprise Cryptographic & Vendor Resilience Playbook',
  goal: 'Orchestrate end-to-end cryptographic inventory transition and third-party vendor operational resilience review.',
  domain: 'compliance-resilience',
  stages: [
    {
      stage_number: 1,
      stage_name: 'Scope and Discovery',
      description: 'Identify all relevant systems, third-party ICT providers, and post-quantum cryptographic dependencies.',
      milestones: [
        {
          id: 'ms.discovery.inventory',
          title: 'Compile exhaustive cryptographic and supplier inventory',
          role: 'sre',
          mandatory: true,
          estimated_hours: 16,
        },
        {
          id: 'ms.discovery.legal_review',
          title: 'Review third-party contractual resilience commitments',
          role: 'legal',
          mandatory: true,
          estimated_hours: 24,
        },
      ],
      exit_criteria: [
        'Complete asset inventory with 100% component coverage',
        'Signed mutual resilience SLA acknowledgments from tier-1 vendors',
      ],
    },
    {
      stage_number: 2,
      stage_name: 'Risk Assessment & Remediation',
      description: 'Perform vulnerability gap analysis, execute penetration tests, and remediate high-severity items.',
      milestones: [
        {
          id: 'ms.remediation.vuln_scan',
          title: 'Conduct algorithmic resilience audit and static analysis',
          role: 'security',
          mandatory: true,
          estimated_hours: 32,
        },
        {
          id: 'ms.remediation.signoff',
          title: 'Secure formal executive risk sign-off',
          role: 'risk-lead',
          mandatory: true,
          estimated_hours: 8,
        },
      ],
      exit_criteria: [
        'Zero critical or high CVEs in critical ICT processing paths',
        'Board-level sign-off on residual risk registry',
      ],
    },
  ],
  metadata: {
    author: 'Compliance Architecture Team',
    version: '1.0.0',
  },
}

const ROLE_OPTIONS = [
  'compliance-officer',
  'sre',
  'developer',
  'legal',
  'security',
  'risk-lead',
]

export const PlaybookBuilder: React.FC<PlaybookBuilderProps> = ({
  tenantId = 'default',
  apiBaseUrl = '',
  apiKey = '',
  className = '',
  initialPlaybook,
  onPlaybookCreated,
}) => {
  const [playbook, setPlaybook] = useState<CustomPlaybook>(
    initialPlaybook || DEFAULT_INITIAL_PLAYBOOK
  )
  const [showJsonMode, setShowJsonMode] = useState<boolean>(false)
  const [jsonText, setJsonText] = useState<string>('')
  const [jsonParseError, setJsonParseError] = useState<string | null>(null)
  const [publishing, setPublishing] = useState<boolean>(false)
  const [publishSuccess, setPublishSuccess] = useState<string | null>(null)
  const [publishError, setPublishError] = useState<string | null>(null)

  // Real-time structural validation
  const validationErrors = useMemo(() => {
    const errors: string[] = []

    if (!playbook.id.trim()) {
      errors.push('Playbook ID must not be empty.')
    }
    if (!playbook.name.trim()) {
      errors.push('Playbook title must not be empty.')
    }
    if (!playbook.goal.trim()) {
      errors.push('Playbook goal must not be empty.')
    }

    if (playbook.stages.length < 2) {
      errors.push(`Playbook must have at least 2 stages (currently ${playbook.stages.length}).`)
    } else if (playbook.stages.length > 6) {
      errors.push(`Playbook must not exceed 6 stages (currently ${playbook.stages.length}).`)
    }

    const seenMilestoneIds = new Set<string>()

    playbook.stages.forEach((stage, sIdx) => {
      const expectedNumber = sIdx + 1
      if (stage.stage_number !== expectedNumber) {
        errors.push(
          `Stage at index ${expectedNumber} has invalid stage_number ${stage.stage_number}; expected ${expectedNumber}.`
        )
      }
      if (!stage.stage_name.trim()) {
        errors.push(`Stage ${expectedNumber} has an empty name.`)
      }
      if (!stage.exit_criteria || stage.exit_criteria.length === 0) {
        errors.push(`Stage ${expectedNumber} must specify at least one exit criterion.`)
      } else {
        stage.exit_criteria.forEach((crit, cIdx) => {
          if (!crit.trim()) {
            errors.push(`Stage ${expectedNumber} exit criterion #${cIdx + 1} is empty.`)
          }
        })
      }

      if (!stage.milestones || stage.milestones.length === 0) {
        errors.push(`Stage ${expectedNumber} must specify at least one milestone.`)
      } else {
        stage.milestones.forEach((m) => {
          if (!m.id.trim()) {
            errors.push(`Stage ${expectedNumber} has a milestone with an empty ID.`)
          } else if (seenMilestoneIds.has(m.id)) {
            errors.push(
              `Duplicate milestone ID '${m.id}' detected in Stage ${expectedNumber}; IDs must be unique.`
            )
          } else {
            seenMilestoneIds.add(m.id)
          }

          if (!m.title.trim()) {
            errors.push(`Milestone '${m.id}' in Stage ${expectedNumber} has an empty title.`)
          }
          if (m.estimated_hours < 1 || m.estimated_hours > 240) {
            errors.push(`Milestone '${m.id}' estimated hours must be between 1 and 240.`)
          }
        })
      }
    })

    return errors
  }, [playbook])

  const isValid = validationErrors.length === 0

  // Stage Manipulation
  const handleAddStage = () => {
    if (playbook.stages.length >= 6) return
    const newStageNumber = playbook.stages.length + 1
    const newStage: CustomStage = {
      stage_number: newStageNumber,
      stage_name: `Stage ${newStageNumber}: New Operational Phase`,
      description: 'Describe stage objectives, governance prerequisites, and operational scope.',
      milestones: [
        {
          id: `ms.stage${newStageNumber}.action_1`,
          title: `Initial milestone for stage ${newStageNumber}`,
          role: 'compliance-officer',
          mandatory: true,
          estimated_hours: 8,
        },
      ],
      exit_criteria: [`Stage ${newStageNumber} verification sign-off`],
    }

    setPlaybook({
      ...playbook,
      stages: [...playbook.stages, newStage],
    })
  }

  const handleRemoveStage = (index: number) => {
    if (playbook.stages.length <= 2) return
    const updatedStages = playbook.stages
      .filter((_, idx) => idx !== index)
      .map((s, idx) => ({ ...s, stage_number: idx + 1 }))

    setPlaybook({
      ...playbook,
      stages: updatedStages,
    })
  }

  const handleUpdateStageName = (index: number, name: string) => {
    const updatedStages = [...playbook.stages]
    updatedStages[index] = { ...updatedStages[index], stage_name: name }
    setPlaybook({ ...playbook, stages: updatedStages })
  }

  const handleUpdateStageDesc = (index: number, desc: string) => {
    const updatedStages = [...playbook.stages]
    updatedStages[index] = { ...updatedStages[index], description: desc }
    setPlaybook({ ...playbook, stages: updatedStages })
  }

  // Milestone Manipulation
  const handleAddMilestone = (stageIndex: number) => {
    const stage = playbook.stages[stageIndex]
    const mNum = stage.milestones.length + 1
    const newMilestone: CustomMilestone = {
      id: `ms.stage${stage.stage_number}.task_${mNum}_${Date.now().toString().slice(-4)}`,
      title: 'Actionable compliance milestone task',
      role: 'sre',
      mandatory: true,
      estimated_hours: 8,
    }

    const updatedStages = [...playbook.stages]
    updatedStages[stageIndex] = {
      ...stage,
      milestones: [...stage.milestones, newMilestone],
    }
    setPlaybook({ ...playbook, stages: updatedStages })
  }

  const handleRemoveMilestone = (stageIndex: number, milestoneIndex: number) => {
    const stage = playbook.stages[stageIndex]
    const updatedMilestones = stage.milestones.filter((_, idx) => idx !== milestoneIndex)
    const updatedStages = [...playbook.stages]
    updatedStages[stageIndex] = {
      ...stage,
      milestones: updatedMilestones,
    }
    setPlaybook({ ...playbook, stages: updatedStages })
  }

  const handleUpdateMilestone = (
    stageIndex: number,
    milestoneIndex: number,
    field: keyof CustomMilestone,
    val: any
  ) => {
    const stage = playbook.stages[stageIndex]
    const updatedMilestones = [...stage.milestones]
    updatedMilestones[milestoneIndex] = {
      ...updatedMilestones[milestoneIndex],
      [field]: val,
    }
    const updatedStages = [...playbook.stages]
    updatedStages[stageIndex] = {
      ...stage,
      milestones: updatedMilestones,
    }
    setPlaybook({ ...playbook, stages: updatedStages })
  }

  // Exit Criteria Manipulation
  const handleAddExitCriterion = (stageIndex: number) => {
    const stage = playbook.stages[stageIndex]
    const updatedStages = [...playbook.stages]
    updatedStages[stageIndex] = {
      ...stage,
      exit_criteria: [...stage.exit_criteria, 'Mandatory verification exit criterion'],
    }
    setPlaybook({ ...playbook, stages: updatedStages })
  }

  const handleRemoveExitCriterion = (stageIndex: number, critIndex: number) => {
    const stage = playbook.stages[stageIndex]
    const updatedCrit = stage.exit_criteria.filter((_, idx) => idx !== critIndex)
    const updatedStages = [...playbook.stages]
    updatedStages[stageIndex] = {
      ...stage,
      exit_criteria: updatedCrit,
    }
    setPlaybook({ ...playbook, stages: updatedStages })
  }

  const handleUpdateExitCriterion = (
    stageIndex: number,
    critIndex: number,
    text: string
  ) => {
    const stage = playbook.stages[stageIndex]
    const updatedCrit = [...stage.exit_criteria]
    updatedCrit[critIndex] = text
    const updatedStages = [...playbook.stages]
    updatedStages[stageIndex] = {
      ...stage,
      exit_criteria: updatedCrit,
    }
    setPlaybook({ ...playbook, stages: updatedStages })
  }

  // JSON Mode Toggle
  const toggleJsonMode = () => {
    if (!showJsonMode) {
      setJsonText(JSON.stringify(playbook, null, 2))
      setJsonParseError(null)
      setShowJsonMode(true)
    } else {
      try {
        const parsed = JSON.parse(jsonText)
        setPlaybook(parsed)
        setJsonParseError(null)
        setShowJsonMode(false)
      } catch (err: any) {
        setJsonParseError(`Invalid JSON format: ${err.message}`)
      }
    }
  }

  // Publishing
  const handlePublish = async () => {
    if (!isValid) return
    setPublishing(true)
    setPublishError(null)
    setPublishSuccess(null)

    try {
      const url = `${apiBaseUrl}/v1/playbooks/custom?tenant_id=${encodeURIComponent(tenantId)}`
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
      }
      if (apiKey) {
        headers['Authorization'] = `Bearer ${apiKey}`
      }

      const res = await fetch(url, {
        method: 'POST',
        headers,
        body: JSON.stringify(playbook),
      })

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        const msg =
          errData?.detail?.message ||
          (Array.isArray(errData?.detail) ? errData.detail.join('; ') : null) ||
          errData?.detail ||
          `Server returned HTTP ${res.status}`
        throw new Error(msg)
      }

      const data = await res.json()
      setPublishSuccess(`Custom playbook successfully published! Template ID: ${data.template_id}`)
      if (onPlaybookCreated) {
        onPlaybookCreated(data.template_id)
      }
    } catch (err: any) {
      setPublishError(err.message || 'Failed to publish custom playbook.')
    } finally {
      setPublishing(false)
    }
  }

  return (
    <div
      data-testid="playbook-builder"
      className={`bg-slate-900 border border-slate-800 rounded-xl p-6 text-slate-100 shadow-xl ${className}`}
    >
      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-slate-800">
        <div>
          <h2 className="text-xl font-bold text-slate-100 tracking-tight flex items-center gap-2">
            <span className="p-1.5 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"
                />
              </svg>
            </span>
            Custom Compliance Playbook Builder
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Author, validate, and publish custom multi-stage internal compliance playbooks (FEAT-060).
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            data-testid="btn-toggle-json"
            onClick={toggleJsonMode}
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition"
          >
            {showJsonMode ? 'Visual Mode' : 'JSON Mode'}
          </button>

          <button
            type="button"
            data-testid="btn-publish-playbook"
            onClick={handlePublish}
            disabled={!isValid || publishing}
            className={`px-4 py-1.5 text-xs font-semibold rounded-lg shadow-sm transition flex items-center gap-2 ${
              isValid && !publishing
                ? 'bg-emerald-600 hover:bg-emerald-500 text-white cursor-pointer'
                : 'bg-slate-800 text-slate-500 cursor-not-allowed border border-slate-700'
            }`}
          >
            {publishing ? (
              <>
                <svg
                  className="animate-spin h-3.5 w-3.5 text-white"
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8v8H4z"
                  />
                </svg>
                Publishing...
              </>
            ) : (
              <>
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                Publish Playbook
              </>
            )}
          </button>
        </div>
      </div>

      {/* Notifications */}
      {publishSuccess && (
        <div
          data-testid="publish-success-banner"
          className="mt-4 p-3.5 rounded-lg bg-emerald-950/60 border border-emerald-500/40 text-emerald-300 text-xs flex items-center justify-between"
        >
          <span>{publishSuccess}</span>
          <button
            onClick={() => setPublishSuccess(null)}
            className="text-emerald-400 hover:text-emerald-200"
          >
            x
          </button>
        </div>
      )}

      {publishError && (
        <div
          data-testid="publish-error-banner"
          className="mt-4 p-3.5 rounded-lg bg-rose-950/60 border border-rose-500/40 text-rose-300 text-xs flex items-center justify-between"
        >
          <span>{publishError}</span>
          <button
            onClick={() => setPublishError(null)}
            className="text-rose-400 hover:text-rose-200"
          >
            x
          </button>
        </div>
      )}

      {/* Validation Errors Callout */}
      {!isValid && (
        <div
          data-testid="validation-errors"
          className="mt-4 p-3.5 rounded-lg bg-amber-950/40 border border-amber-500/30 text-amber-200 text-xs"
        >
          <div className="font-semibold mb-1 flex items-center gap-1.5 text-amber-400">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
              />
            </svg>
            Validation Requirements ({validationErrors.length})
          </div>
          <ul className="list-disc list-inside space-y-0.5 text-slate-300">
            {validationErrors.map((err, idx) => (
              <li key={idx}>{err}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Main Content: JSON vs Visual */}
      {showJsonMode ? (
        <div className="mt-6 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400">Direct Custom Playbook JSON Editor</span>
            {jsonParseError && <span className="text-xs text-rose-400">{jsonParseError}</span>}
          </div>
          <textarea
            data-testid="json-editor"
            value={jsonText}
            onChange={(e) => {
              setJsonText(e.target.value)
              setJsonParseError(null)
            }}
            rows={18}
            className="w-full font-mono text-xs p-3.5 bg-slate-950 border border-slate-800 rounded-lg text-emerald-400 focus:outline-none focus:border-emerald-500"
          />
        </div>
      ) : (
        <div className="mt-6 space-y-6">
          {/* Metadata Section */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 bg-slate-950/60 p-4 rounded-lg border border-slate-800/80">
            <div>
              <label className="block text-[11px] font-semibold uppercase text-slate-400 mb-1">
                Playbook ID
              </label>
              <input
                data-testid="input-playbook-id"
                type="text"
                value={playbook.id}
                onChange={(e) => setPlaybook({ ...playbook, id: e.target.value })}
                className="w-full px-3 py-1.5 text-xs bg-slate-900 border border-slate-700 rounded text-slate-200 focus:outline-none focus:border-emerald-500"
                placeholder="playbook.custom-sample"
              />
            </div>

            <div>
              <label className="block text-[11px] font-semibold uppercase text-slate-400 mb-1">
                Playbook Name
              </label>
              <input
                data-testid="input-playbook-name"
                type="text"
                value={playbook.name}
                onChange={(e) => setPlaybook({ ...playbook, name: e.target.value })}
                className="w-full px-3 py-1.5 text-xs bg-slate-900 border border-slate-700 rounded text-slate-200 focus:outline-none focus:border-emerald-500"
                placeholder="Custom Playbook Title"
              />
            </div>

            <div>
              <label className="block text-[11px] font-semibold uppercase text-slate-400 mb-1">
                Domain Taxonomy
              </label>
              <input
                data-testid="input-playbook-domain"
                type="text"
                value={playbook.domain}
                onChange={(e) => setPlaybook({ ...playbook, domain: e.target.value })}
                className="w-full px-3 py-1.5 text-xs bg-slate-900 border border-slate-700 rounded text-slate-200 focus:outline-none focus:border-emerald-500"
                placeholder="compliance, risk, security..."
              />
            </div>

            <div className="md:col-span-3">
              <label className="block text-[11px] font-semibold uppercase text-slate-400 mb-1">
                Playbook Governance Goal
              </label>
              <textarea
                data-testid="input-playbook-goal"
                rows={2}
                value={playbook.goal}
                onChange={(e) => setPlaybook({ ...playbook, goal: e.target.value })}
                className="w-full px-3 py-1.5 text-xs bg-slate-900 border border-slate-700 rounded text-slate-200 focus:outline-none focus:border-emerald-500"
                placeholder="State the regulatory purpose, target risk posture, or institutional mandate..."
              />
            </div>
          </div>

          {/* Stages Header */}
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-200 flex items-center gap-2">
              <span>Workflow Stages ({playbook.stages.length}/6)</span>
              <span className="text-[11px] text-slate-400 font-normal">
                Min 2 stages, max 6 stages required.
              </span>
            </h3>

            <button
              type="button"
              data-testid="btn-add-stage"
              onClick={handleAddStage}
              disabled={playbook.stages.length >= 6}
              className={`px-3 py-1 text-xs font-medium rounded-lg border transition ${
                playbook.stages.length < 6
                  ? 'bg-slate-800 hover:bg-slate-700 text-slate-200 border-slate-700'
                  : 'bg-slate-900 text-slate-600 border-slate-800 cursor-not-allowed'
              }`}
            >
              + Add Stage
            </button>
          </div>

          {/* Stages List */}
          <div className="space-y-4">
            {playbook.stages.map((stage, sIdx) => (
              <div
                key={sIdx}
                data-testid={`stage-card-${sIdx}`}
                className="bg-slate-950/80 border border-slate-800 rounded-lg p-4 space-y-4 shadow-sm"
              >
                {/* Stage Header */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-slate-800/80">
                  <div className="flex items-center gap-3">
                    <span className="w-6 h-6 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center text-xs font-bold border border-emerald-500/30">
                      {stage.stage_number}
                    </span>
                    <input
                      data-testid={`input-stage-name-${sIdx}`}
                      type="text"
                      value={stage.stage_name}
                      onChange={(e) => handleUpdateStageName(sIdx, e.target.value)}
                      className="px-2.5 py-1 text-xs bg-slate-900 border border-slate-700 rounded text-slate-200 focus:outline-none focus:border-emerald-500 font-medium w-64"
                      placeholder="Stage Name"
                    />
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      data-testid={`btn-remove-stage-${sIdx}`}
                      onClick={() => handleRemoveStage(sIdx)}
                      disabled={playbook.stages.length <= 2}
                      className={`px-2.5 py-1 text-[11px] rounded transition ${
                        playbook.stages.length > 2
                          ? 'bg-rose-950/40 text-rose-300 hover:bg-rose-900/60 border border-rose-500/30'
                          : 'bg-slate-900 text-slate-600 border border-slate-800 cursor-not-allowed'
                      }`}
                    >
                      Delete Stage
                    </button>
                  </div>
                </div>

                {/* Stage Description */}
                <div>
                  <label className="block text-[10px] font-semibold uppercase text-slate-400 mb-1">
                    Stage Description
                  </label>
                  <input
                    type="text"
                    value={stage.description}
                    onChange={(e) => handleUpdateStageDesc(sIdx, e.target.value)}
                    className="w-full px-2.5 py-1 text-xs bg-slate-900 border border-slate-700/80 rounded text-slate-300 focus:outline-none focus:border-emerald-500"
                    placeholder="Describe operational responsibilities and phase boundary..."
                  />
                </div>

                {/* Stage Milestones */}
                <div className="space-y-2 pt-1">
                  <div className="flex items-center justify-between">
                    <label className="text-[11px] font-semibold uppercase tracking-wider text-slate-300">
                      Milestones ({stage.milestones.length})
                    </label>
                    <button
                      type="button"
                      data-testid={`btn-add-milestone-${sIdx}`}
                      onClick={() => handleAddMilestone(sIdx)}
                      className="text-[11px] text-emerald-400 hover:text-emerald-300 font-medium"
                    >
                      + Add Milestone
                    </button>
                  </div>

                  <div className="space-y-2">
                    {stage.milestones.map((m, mIdx) => (
                      <div
                        key={mIdx}
                        className="grid grid-cols-1 md:grid-cols-12 gap-2 items-center bg-slate-900/90 p-2.5 rounded border border-slate-800 text-xs"
                      >
                        <div className="md:col-span-3">
                          <input
                            type="text"
                            value={m.id}
                            onChange={(e) =>
                              handleUpdateMilestone(sIdx, mIdx, 'id', e.target.value)
                            }
                            className="w-full px-2 py-1 bg-slate-950 border border-slate-700 rounded text-slate-300 font-mono text-[11px]"
                            placeholder="Milestone ID"
                          />
                        </div>

                        <div className="md:col-span-4">
                          <input
                            type="text"
                            value={m.title}
                            onChange={(e) =>
                              handleUpdateMilestone(sIdx, mIdx, 'title', e.target.value)
                            }
                            className="w-full px-2 py-1 bg-slate-950 border border-slate-700 rounded text-slate-200 text-xs"
                            placeholder="Task description"
                          />
                        </div>

                        <div className="md:col-span-2">
                          <select
                            value={m.role}
                            onChange={(e) =>
                              handleUpdateMilestone(sIdx, mIdx, 'role', e.target.value)
                            }
                            className="w-full px-2 py-1 bg-slate-950 border border-slate-700 rounded text-slate-300 text-xs"
                          >
                            {ROLE_OPTIONS.map((r) => (
                              <option key={r} value={r}>
                                {r}
                              </option>
                            ))}
                          </select>
                        </div>

                        <div className="md:col-span-1 flex items-center gap-1">
                          <input
                            type="number"
                            min={1}
                            max={240}
                            value={m.estimated_hours}
                            onChange={(e) =>
                              handleUpdateMilestone(
                                sIdx,
                                mIdx,
                                'estimated_hours',
                                parseInt(e.target.value, 10) || 1
                              )
                            }
                            className="w-14 px-1.5 py-1 bg-slate-950 border border-slate-700 rounded text-slate-300 text-xs text-center"
                          />
                          <span className="text-[10px] text-slate-500">h</span>
                        </div>

                        <div className="md:col-span-1 flex items-center justify-center">
                          <label className="flex items-center gap-1 cursor-pointer text-[10px] text-slate-400">
                            <input
                              type="checkbox"
                              checked={m.mandatory}
                              onChange={(e) =>
                                handleUpdateMilestone(sIdx, mIdx, 'mandatory', e.target.checked)
                              }
                              className="rounded bg-slate-950 border-slate-700 text-emerald-500 focus:ring-0"
                            />
                            Req
                          </label>
                        </div>

                        <div className="md:col-span-1 flex justify-end">
                          <button
                            type="button"
                            onClick={() => handleRemoveMilestone(sIdx, mIdx)}
                            className="text-slate-500 hover:text-rose-400 p-1"
                            title="Remove milestone"
                          >
                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                            </svg>
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Exit Criteria */}
                <div className="space-y-2 pt-1 border-t border-slate-800/60">
                  <div className="flex items-center justify-between">
                    <label className="text-[11px] font-semibold uppercase tracking-wider text-slate-300">
                      Exit Criteria Gates ({stage.exit_criteria.length})
                    </label>
                    <button
                      type="button"
                      data-testid={`btn-add-exit-criterion-${sIdx}`}
                      onClick={() => handleAddExitCriterion(sIdx)}
                      className="text-[11px] text-emerald-400 hover:text-emerald-300 font-medium"
                    >
                      + Add Criterion
                    </button>
                  </div>

                  <div className="space-y-1.5">
                    {stage.exit_criteria.map((crit, cIdx) => (
                      <div key={cIdx} className="flex items-center gap-2">
                        <span className="text-emerald-500 text-xs">/</span>
                        <input
                          type="text"
                          value={crit}
                          onChange={(e) =>
                            handleUpdateExitCriterion(sIdx, cIdx, e.target.value)
                          }
                          className="flex-1 px-2.5 py-1 text-xs bg-slate-900 border border-slate-700/80 rounded text-slate-200 focus:outline-none focus:border-emerald-500"
                          placeholder="Verification condition required before advancing stage"
                        />
                        <button
                          type="button"
                          onClick={() => handleRemoveExitCriterion(sIdx, cIdx)}
                          className="text-slate-500 hover:text-rose-400 px-1"
                          title="Remove exit criterion"
                        >
                          x
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default PlaybookBuilder
