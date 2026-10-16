import React, { useState } from 'react'

export interface CriterionCheckData {
  criterion: string
  status: 'PASSED' | 'FAILED'
  evidence_ref: string
}

export interface ExitValidationResultData {
  can_advance: boolean
  exit_statement: string
  checks_evaluated: CriterionCheckData[]
  blocking_issues: string[]
  override_applied?: boolean
  validation_id?: string | null
}

export interface StageExitGateModalProps {
  isOpen: boolean
  runId: string
  currentStage: number
  stageName?: string
  tenantId?: string
  apiBaseUrl?: string
  apiKey?: string
  initialValidation?: ExitValidationResultData | null
  onClose: () => void
  onPromoted?: (result: ExitValidationResultData) => void
}

const DEFAULT_MOCK_VALIDATION: ExitValidationResultData = {
  can_advance: false,
  exit_statement: 'Domain interfaces documented with zero circular schema references.',
  checks_evaluated: [
    {
      criterion: 'Domain interfaces documented with zero circular schema references.',
      status: 'FAILED',
      evidence_ref: 'MISSING_DELIVERABLES',
    },
  ],
  blocking_issues: [
    "Milestone M1-2 ('Draft architectural decoupling ADR and API contracts') is incomplete.",
  ],
  override_applied: false,
}

export const StageExitGateModal: React.FC<StageExitGateModalProps> = ({
  isOpen,
  runId,
  currentStage,
  stageName = 'Decouple / Establish',
  tenantId = 'default',
  apiBaseUrl = '',
  apiKey = '',
  initialValidation = DEFAULT_MOCK_VALIDATION,
  onClose,
  onPromoted,
}) => {
  const [validation, setValidation] = useState<ExitValidationResultData | null>(initialValidation)
  const [overrideJustification, setOverrideJustification] = useState<string>('')
  const [showOverrideInput, setShowOverrideInput] = useState<boolean>(false)
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  if (!isOpen) return null

  const canAdvance = validation?.can_advance ?? false
  const checks = validation?.checks_evaluated ?? []
  const blockers = validation?.blocking_issues ?? []

  const handlePromote = async (withOverride = false) => {
    setIsSubmitting(true)
    setErrorMessage(null)
    setSuccessMessage(null)

    const justification = withOverride ? overrideJustification.trim() : null
    if (withOverride && (!justification || justification.length < 15)) {
      setErrorMessage(
        `Administrative override requires a justification of at least 15 characters (entered: ${
          justification?.length || 0
        }).`
      )
      setIsSubmitting(false)
      return
    }

    try {
      if (apiBaseUrl) {
        const headers: Record<string, string> = { 'Content-Type': 'application/json' }
        if (apiKey) headers['X-API-Key'] = apiKey

        const resp = await fetch(
          `${apiBaseUrl}/v1/playbooks/${runId}/promote?tenant_id=${tenantId}`,
          {
            method: 'POST',
            headers,
            body: JSON.stringify({
              current_stage: currentStage,
              override_justification: justification,
            }),
          }
        )

        if (!resp.ok) {
          const errData = await resp.json()
          throw new Error(errData.detail || 'Promotion failed')
        }
      }

      const updatedResult: ExitValidationResultData = {
        can_advance: true,
        exit_statement: validation?.exit_statement || '',
        checks_evaluated: checks,
        blocking_issues: [],
        override_applied: withOverride,
        validation_id: validation?.validation_id || 'mock-val-id',
      }
      setValidation(updatedResult)
      setSuccessMessage(
        withOverride
          ? 'Stage promoted with approved administrative override.'
          : 'Stage successfully promoted to next stage.'
      )
      if (onPromoted) onPromoted(updatedResult)
    } catch (err: unknown) {
      setErrorMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div
      data-testid="stage-exit-modal-backdrop"
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4"
    >
      <div
        data-testid="stage-exit-gate-container"
        className="w-full max-w-2xl rounded-2xl border border-slate-800 bg-slate-900 p-6 text-slate-100 shadow-2xl"
      >
        {/* Header */}
        <div className="flex items-start justify-between border-b border-slate-800 pb-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded bg-indigo-950 px-2 py-0.5 font-mono text-xs font-bold text-indigo-300 border border-indigo-800">
                Stage {currentStage} Gate
              </span>
              <h2 className="text-xl font-bold text-white">Automated Stage Exit Validator</h2>
            </div>
            <p className="mt-1 text-xs text-slate-400">
              Empirical verification of stage exit preconditions for{' '}
              <span className="text-slate-200 font-semibold">{stageName}</span>.
            </p>
          </div>
          <button
            data-testid="stage-exit-close-btn"
            type="button"
            onClick={onClose}
            className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
          >
            ✕
          </button>
        </div>

        {/* Exit Criteria Statement */}
        <div className="mt-4 rounded-lg border border-slate-800 bg-slate-950/60 p-3.5">
          <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Exit Criteria Standard:
          </div>
          <p
            data-testid="stage-exit-statement"
            className="mt-1 font-mono text-xs text-cyan-300"
          >
            {validation?.exit_statement || 'Empirical evidence required'}
          </p>
        </div>

        {/* Criteria Evaluation Checklist */}
        <div className="mt-4 space-y-2">
          <div className="text-xs font-semibold text-slate-300">Empirical Precondition Checks:</div>
          <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
            {checks.map((check, idx) => {
              const isPassed = check.status === 'PASSED'
              return (
                <div
                  key={idx}
                  data-testid={`criterion-check-item-${idx}`}
                  className={`flex items-start justify-between rounded-lg border p-3 ${
                    isPassed
                      ? 'border-emerald-900/60 bg-emerald-950/20 text-emerald-200'
                      : 'border-rose-900/60 bg-rose-950/20 text-rose-200'
                  }`}
                >
                  <div className="pr-2">
                    <div className="text-xs font-semibold">{check.criterion}</div>
                    <div className="mt-0.5 text-xs opacity-75 font-mono">
                      Ref: {check.evidence_ref || 'None'}
                    </div>
                  </div>
                  <span
                    data-testid={`criterion-badge-${idx}`}
                    className={`rounded px-2 py-0.5 text-xs font-bold uppercase tracking-wider border ${
                      isPassed
                        ? 'border-emerald-700 bg-emerald-900/80 text-emerald-300'
                        : 'border-rose-700 bg-rose-900/80 text-rose-300'
                    }`}
                  >
                    {check.status}
                  </span>
                </div>
              )
            })}
          </div>
        </div>

        {/* Blocking Issues */}
        {blockers.length > 0 && (
          <div
            data-testid="stage-exit-blocking-issues"
            className="mt-4 rounded-lg border border-rose-800/80 bg-rose-950/40 p-3.5 text-xs text-rose-300"
          >
            <div className="font-bold flex items-center gap-1.5">
              <span>⛔ Promotion Blocked</span>
              <span>({blockers.length} unsatisfied preconditions)</span>
            </div>
            <ul className="mt-1.5 list-disc list-inside space-y-1">
              {blockers.map((issue, idx) => (
                <li key={idx} data-testid={`blocking-issue-item-${idx}`}>
                  {issue}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Alerts */}
        {errorMessage && (
          <div
            data-testid="stage-exit-error-alert"
            className="mt-3 rounded-lg border border-rose-800 bg-rose-950/80 p-2.5 text-xs text-rose-300"
          >
            {errorMessage}
          </div>
        )}
        {successMessage && (
          <div
            data-testid="stage-exit-success-alert"
            className="mt-3 rounded-lg border border-emerald-800 bg-emerald-950/80 p-2.5 text-xs text-emerald-300"
          >
            {successMessage}
          </div>
        )}

        {/* Administrative Override Section */}
        {!canAdvance && (
          <div className="mt-4 border-t border-slate-800 pt-3">
            <button
              data-testid="toggle-override-btn"
              type="button"
              onClick={() => setShowOverrideInput(!showOverrideInput)}
              className="text-xs text-amber-400 hover:text-amber-300 underline font-medium"
            >
              {showOverrideInput ? 'Hide Administrative Override' : 'Apply Administrative Exception / Override'}
            </button>

            {showOverrideInput && (
              <div
                data-testid="override-section"
                className="mt-2.5 rounded-lg border border-amber-900/70 bg-amber-950/20 p-3"
              >
                <div className="text-xs text-amber-300 font-semibold">
                  Compliance Officer Exception Rationale:
                </div>
                <p className="text-xs text-slate-400 mt-0.5">
                  An immutable audit exception will be committed to the regulatory trail. Minimum 15 characters.
                </p>
                <textarea
                  data-testid="override-justification-input"
                  value={overrideJustification}
                  onChange={(e) => setOverrideJustification(e.target.value)}
                  placeholder="Enter detailed statutory or technical justification..."
                  className="mt-2 w-full rounded border border-slate-700 bg-slate-800 p-2 text-xs text-white placeholder-slate-500 focus:border-amber-500 focus:outline-none"
                  rows={2}
                />
                <button
                  data-testid="submit-override-btn"
                  type="button"
                  disabled={isSubmitting || overrideJustification.trim().length < 15}
                  onClick={() => handlePromote(true)}
                  className="mt-2 rounded bg-amber-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-amber-500 transition-colors disabled:opacity-50"
                >
                  {isSubmitting ? 'Signing Exception...' : 'Sign Audit Exception & Promote'}
                </button>
              </div>
            )}
          </div>
        )}

        {/* Modal Actions */}
        <div className="mt-6 flex items-center justify-end gap-3 border-t border-slate-800 pt-4">
          <button
            data-testid="stage-exit-cancel-btn"
            type="button"
            onClick={onClose}
            className="rounded px-4 py-2 text-xs font-semibold text-slate-300 hover:bg-slate-800"
          >
            Close
          </button>

          {canAdvance && (
            <button
              data-testid="promote-stage-btn"
              type="button"
              disabled={isSubmitting}
              onClick={() => handlePromote(false)}
              className="rounded bg-emerald-600 px-4 py-2 text-xs font-bold text-white hover:bg-emerald-500 transition-colors shadow-lg shadow-emerald-950/50"
            >
              {isSubmitting ? 'Promoting...' : `Promote to Stage ${currentStage + 1} ✓`}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export default StageExitGateModal
