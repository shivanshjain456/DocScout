import React, { useState, useEffect } from 'react'

export interface IncidentCrisisStateData {
  incident_id: string
  severity: 'SEV1' | 'SEV2'
  summary: string
  systems_impacted: string[]
  discovery_timestamp: string
  statutory_reporting_deadline: string
  minutes_remaining: number
  required_actions: string[]
  actions_completed: string[]
  disclosure_draft: string
  status: 'DECLARED' | 'CONTAINED' | 'REPORTED' | 'RESOLVED'
  warning_issued: boolean
  run_id?: string | null
  created_at?: string
  updated_at?: string
}

export interface CrisisConsoleProps {
  incidentId?: string
  tenantId?: string
  apiBaseUrl?: string
  apiKey?: string
  className?: string
  initialState?: IncidentCrisisStateData
  onStateChange?: (state: IncidentCrisisStateData) => void
}

const DEFAULT_MOCK_INCIDENT: IncidentCrisisStateData = {
  incident_id: 'e30a5749-5a12-4eb3-8b7c-f8d97e59b201',
  severity: 'SEV1',
  summary: 'Unauthorized API credential usage detected across core payment gateway settlement endpoints.',
  systems_impacted: ['core-payment-gateway', 'settlement-db-replica', 'customer-token-service'],
  discovery_timestamp: new Date(Date.now() - 45 * 60 * 1000).toISOString(),
  statutory_reporting_deadline: new Date(Date.now() + (5 * 60 + 15) * 60 * 1000).toISOString(),
  minutes_remaining: 315,
  required_actions: [
    'ACT-01: Establish out-of-band encrypted incident war room and appoint Incident Commander',
    'ACT-02: Preserve volatile memory dump and system event audit logs before shutdown',
    'ACT-03: Isolate compromised network segments via automated ingress bulkhead controls',
    'ACT-04: Revoke all active session tokens, compromised service credentials, and API keys',
    'ACT-05: Alert Chief Information Security Officer (CISO) and Statutory Compliance Liaison',
    'ACT-06: Compile and sign off preliminary RBI Cyber Security Annex II disclosure report',
  ],
  actions_completed: [
    'ACT-01: Establish out-of-band encrypted incident war room and appoint Incident Commander',
  ],
  disclosure_draft: `# STATUTORY INCIDENT DISCLOSURE (RBI CYBER SECURITY FRAMEWORK - ANNEX II)

## 1. Statutory Incident Identification
- **Incident Reference ID:** e30a5749-5a12-4eb3-8b7c-f8d97e59b201
- **Statutory Reporting Tier:** SEV1
- **Reporting Institution:** DocScout Core Banking & Regulatory Gateway
- **Incident Discovery Timestamp:** ${new Date(Date.now() - 45 * 60 * 1000).toISOString()}
- **Critical Systems & Services Impacted:** core-payment-gateway, settlement-db-replica, customer-token-service

## 2. Preliminary Technical Summary & Attack Indicators
Unauthorized API credential usage detected across core payment gateway settlement endpoints.

## 3. Preserved Evidence & Containment Actions
- Volatile memory captures and raw forensic snapshots secured prior to container/host teardown.
- Network bulkheads and egress filtering applied to contain lateral propagation.
- Compromised session credentials, tokens, and mutual TLS certificates revoked.

## 4. Statutory Notification Status
- Statutory regulatory notification draft compiled for final compliance officer sign-off.
- Target formal submission within statutory 6-hour window.
`,
  status: 'DECLARED',
  warning_issued: false,
}

export const CrisisConsole: React.FC<CrisisConsoleProps> = ({
  incidentId,
  tenantId = 'default',
  apiBaseUrl = '',
  apiKey = '',
  className = '',
  initialState,
  onStateChange,
}) => {
  const [incident, setIncident] = useState<IncidentCrisisStateData>(initialState || DEFAULT_MOCK_INCIDENT)
  const [isLoading, setIsLoading] = useState<boolean>(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [copiedDraft, setCopiedDraft] = useState<boolean>(false)
  const [completingActionId, setCompletingActionId] = useState<string | null>(null)

  // Declare Incident Modal / Form State
  const [showDeclareModal, setShowDeclareModal] = useState<boolean>(false)
  const [newSeverity, setNewSeverity] = useState<'SEV1' | 'SEV2'>('SEV1')
  const [newSummary, setNewSummary] = useState<string>('')
  const [newSystems, setNewSystems] = useState<string>('core-switch, payment-api')

  // Calculate live countdown
  const calculateRemaining = () => {
    if (!incident.statutory_reporting_deadline) return { hours: 0, minutes: 0, seconds: 0, totalMinutes: 0 }
    const deadline = new Date(incident.statutory_reporting_deadline).getTime()
    const now = Date.now()
    const diff = Math.max(0, deadline - now)
    const totalMinutes = Math.floor(diff / (1000 * 60))
    const hours = Math.floor(diff / (1000 * 60 * 60))
    const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60))
    const seconds = Math.floor((diff % (1000 * 60)) / 1000)
    return { hours, minutes, seconds, totalMinutes }
  }

  const [countdown, setCountdown] = useState(calculateRemaining())

  useEffect(() => {
    const timer = setInterval(() => {
      setCountdown(calculateRemaining())
    }, 1000)
    return () => clearInterval(timer)
  }, [incident.statutory_reporting_deadline])

  // Fetch live incident status from backend if incidentId provided
  useEffect(() => {
    if (!incidentId || !apiBaseUrl) return

    let isMounted = true
    const fetchStatus = async () => {
      setIsLoading(true)
      try {
        const headers: Record<string, string> = {
          Accept: 'application/json',
          'Content-Type': 'application/json',
        }
        if (apiKey) headers['x-api-key'] = apiKey

        const res = await fetch(`${apiBaseUrl}/v1/incidents/${incidentId}/status?tenant_id=${tenantId}`, {
          headers,
        })
        if (!res.ok) {
          throw new Error(`Failed to load crisis incident status: ${res.statusText}`)
        }
        const data: IncidentCrisisStateData = await res.json()
        if (isMounted) {
          setIncident(data)
          if (onStateChange) onStateChange(data)
          setErrorMessage(null)
        }
      } catch (err: any) {
        if (isMounted) setErrorMessage(err.message || 'Error fetching crisis state')
      } finally {
        if (isMounted) setIsLoading(false)
      }
    }

    fetchStatus()
    return () => {
      isMounted = false
    }
  }, [incidentId, apiBaseUrl, apiKey, tenantId])

  // Mark action complete
  const handleCompleteAction = async (actionText: string) => {
    const actionId = actionText.split(':')[0].trim()
    setCompletingActionId(actionId)

    if (apiBaseUrl && (incident.incident_id || incidentId)) {
      try {
        const id = incident.incident_id || incidentId
        const headers: Record<string, string> = {
          Accept: 'application/json',
          'Content-Type': 'application/json',
        }
        if (apiKey) headers['x-api-key'] = apiKey

        const res = await fetch(
          `${apiBaseUrl}/v1/incidents/${id}/actions/${actionId}/complete?tenant_id=${tenantId}`,
          {
            method: 'POST',
            headers,
            body: JSON.stringify({ notes: 'Verified via CrisisConsole UI' }),
          }
        )
        if (res.ok) {
          const updated: IncidentCrisisStateData = await res.json()
          setIncident(updated)
          if (onStateChange) onStateChange(updated)
          setCompletingActionId(null)
          return
        }
      } catch (err: any) {
        setErrorMessage(err.message || 'Failed to complete action item')
      }
    }

    // Local fallback state update
    const completedSet = new Set(incident.actions_completed)
    completedSet.add(actionText)
    const allDone = incident.required_actions.every((a) => completedSet.has(a))
    const updated: IncidentCrisisStateData = {
      ...incident,
      actions_completed: Array.from(completedSet),
      status: allDone ? 'CONTAINED' : incident.status,
    }
    setIncident(updated)
    if (onStateChange) onStateChange(updated)
    setCompletingActionId(null)
  }

  // Declare new incident handler
  const handleDeclareIncident = async (e: React.FormEvent) => {
    e.preventDefault()
    if (newSummary.trim().length < 20) {
      setErrorMessage('Summary must be at least 20 characters.')
      return
    }

    const systemsList = newSystems
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)

    if (systemsList.length === 0) {
      setErrorMessage('At least one impacted system must be specified.')
      return
    }

    setIsLoading(true)
    setErrorMessage(null)

    if (apiBaseUrl) {
      try {
        const headers: Record<string, string> = {
          Accept: 'application/json',
          'Content-Type': 'application/json',
        }
        if (apiKey) headers['x-api-key'] = apiKey

        const payload = {
          severity: newSeverity,
          summary: newSummary.trim(),
          systems_impacted: systemsList,
          discovery_timestamp: new Date().toISOString(),
        }

        const res = await fetch(`${apiBaseUrl}/v1/incidents/declare?tenant_id=${tenantId}`, {
          method: 'POST',
          headers,
          body: JSON.stringify(payload),
        })

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}))
          throw new Error(errData.detail || `Declaration failed with status ${res.status}`)
        }

        const data: IncidentCrisisStateData = await res.json()
        setIncident(data)
        if (onStateChange) onStateChange(data)
        setShowDeclareModal(false)
        setNewSummary('')
        setIsLoading(false)
        return
      } catch (err: any) {
        setErrorMessage(err.message || 'Error declaring incident')
        setIsLoading(false)
        return
      }
    }

    // Client mock declaration
    const mockDeadline = new Date(Date.now() + 6 * 60 * 60 * 1000).toISOString()
    const actions =
      newSeverity === 'SEV1'
        ? DEFAULT_MOCK_INCIDENT.required_actions
        : DEFAULT_MOCK_INCIDENT.required_actions.slice(0, 5)

    const declared: IncidentCrisisStateData = {
      incident_id: 'new-' + Math.random().toString(36).substring(2, 9),
      severity: newSeverity,
      summary: newSummary.trim(),
      systems_impacted: systemsList,
      discovery_timestamp: new Date().toISOString(),
      statutory_reporting_deadline: mockDeadline,
      minutes_remaining: 360,
      required_actions: actions,
      actions_completed: [],
      disclosure_draft: DEFAULT_MOCK_INCIDENT.disclosure_draft,
      status: 'DECLARED',
      warning_issued: false,
    }

    setIncident(declared)
    if (onStateChange) onStateChange(declared)
    setShowDeclareModal(false)
    setNewSummary('')
    setIsLoading(false)
  }

  const copyToClipboard = () => {
    if (navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(incident.disclosure_draft)
      setCopiedDraft(true)
      setTimeout(() => setCopiedDraft(false), 2500)
    }
  }

  // Dynamic urgency color coding
  const isExpired = countdown.totalMinutes <= 0
  const isUrgent = countdown.totalMinutes <= 240 // 4-hour mark
  const isCritical = countdown.totalMinutes <= 60 // 1-hour mark

  let countdownTheme = 'border-cyan-500/30 bg-cyan-950/20 text-cyan-300'
  if (isUrgent) countdownTheme = 'border-amber-500/40 bg-amber-950/30 text-amber-300 animate-pulse'
  if (isCritical || isExpired) countdownTheme = 'border-rose-500/60 bg-rose-950/40 text-rose-300 animate-pulse'

  return (
    <div
      data-testid="crisis-console"
      className={`rounded-xl border border-rose-900/60 bg-slate-950 p-6 text-slate-100 shadow-2xl ${className}`}
    >
      {/* Top Crisis Emergency Banner */}
      <div
        data-testid="crisis-mode-banner"
        className="mb-6 flex flex-col justify-between gap-4 rounded-lg border border-rose-700/60 bg-rose-950/40 p-4 md:flex-row md:items-center"
      >
        <div className="flex items-center gap-3">
          <span className="flex h-3 w-3 relative">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-3 w-3 bg-rose-500"></span>
          </span>
          <div>
            <h2 className="text-sm font-bold uppercase tracking-wider text-rose-300">
              Statutory Cyber Incident Crisis Response (RBI CSF)
            </h2>
            <p className="text-xs text-rose-400/80">
              Mandatory 6-Hour Incident Notification & Evidence Preservation Protocol
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <span
            data-testid="crisis-severity-badge"
            className={`rounded px-2.5 py-1 text-xs font-bold uppercase ${
              incident.severity === 'SEV1'
                ? 'bg-rose-900 text-rose-100 border border-rose-600'
                : 'bg-amber-900 text-amber-100 border border-amber-600'
            }`}
          >
            {incident.severity}
          </span>
          <span
            data-testid="crisis-status-badge"
            className="rounded bg-slate-800 px-2.5 py-1 text-xs font-semibold uppercase text-slate-300 border border-slate-700"
          >
            {incident.status}
          </span>
          <button
            data-testid="declare-incident-btn"
            onClick={() => setShowDeclareModal(true)}
            className="rounded bg-rose-600 px-3 py-1 text-xs font-semibold text-white hover:bg-rose-500 transition-colors"
          >
            Declare Crisis
          </button>
        </div>
      </div>

      {/* Countdown Clock & Core Incident Header */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3 mb-6">
        {/* Countdown Box */}
        <div
          data-testid="regulatory-countdown-clock"
          className={`flex flex-col items-center justify-center rounded-lg border p-6 text-center shadow-inner ${countdownTheme}`}
        >
          <div className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">
            Statutory RBI 6-Hour Deadline Window
          </div>
          <div className="font-mono text-3xl font-extrabold tracking-tight md:text-4xl">
            {String(countdown.hours).padStart(2, '0')}:{String(countdown.minutes).padStart(2, '0')}:
            {String(countdown.seconds).padStart(2, '0')}
          </div>
          <div className="mt-2 text-xs font-medium">
            {isExpired ? (
              <span className="text-rose-400 font-bold">DEADLINE EXPIRED - REGULATORY BREACH</span>
            ) : isUrgent ? (
              <span className="text-amber-300 font-semibold">URGENT: Alert Risk Officer & Prepare Filing</span>
            ) : (
              <span className="text-cyan-400">Time Remaining to Certify Filing</span>
            )}
          </div>
          <div className="mt-3 text-[11px] text-slate-400">
            Deadline: {new Date(incident.statutory_reporting_deadline).toLocaleTimeString()} UTC
          </div>
        </div>

        {/* Incident Metadata Box */}
        <div className="lg:col-span-2 rounded-lg border border-slate-800 bg-slate-900/60 p-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
              <span>Incident ID: <strong className="font-mono text-slate-300">{incident.incident_id}</strong></span>
              <span>Discovered: <strong className="text-slate-300">{new Date(incident.discovery_timestamp).toLocaleTimeString()}</strong></span>
            </div>
            <h3 className="text-sm font-bold text-white mb-2">{incident.summary}</h3>

            {/* Impacted Systems */}
            <div className="mt-3">
              <span className="text-xs font-medium text-slate-400">Impacted Infrastructure:</span>
              <div className="mt-1 flex flex-wrap gap-2" data-testid="impacted-systems-list">
                {incident.systems_impacted.map((sys) => (
                  <span
                    key={sys}
                    data-testid={`system-tag-${sys}`}
                    className="rounded bg-slate-800 px-2 py-0.5 font-mono text-xs text-rose-300 border border-slate-700"
                  >
                    {sys}
                  </span>
                ))}
              </div>
            </div>
          </div>

          {/* Action Progress Meter */}
          <div className="mt-4 pt-3 border-t border-slate-800/80">
            <div className="flex justify-between text-xs text-slate-400 mb-1">
              <span>Forensic & Regulatory Milestones Completed</span>
              <span className="font-mono font-bold text-slate-200">
                {incident.actions_completed.length} / {incident.required_actions.length}
              </span>
            </div>
            <div className="h-2 w-full rounded-full bg-slate-800 overflow-hidden">
              <div
                className="h-full bg-rose-500 transition-all duration-300"
                style={{
                  width: `${(incident.actions_completed.length / Math.max(1, incident.required_actions.length)) * 100}%`,
                }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Error alert if any */}
      {errorMessage && (
        <div
          data-testid="crisis-error-alert"
          className="mb-6 rounded-lg border border-rose-800 bg-rose-950/60 p-3 text-xs text-rose-300"
        >
          {errorMessage}
        </div>
      )}

      {/* Main Tabs / Grids: Actions Checklist & RBI Disclosure Draft */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Forensic & Statutory Action Checklist */}
        <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-5">
          <div className="mb-4 flex items-center justify-between border-b border-slate-800 pb-3">
            <h4 className="text-sm font-bold text-white uppercase tracking-wider">
              Forensic Evidence & Containment Checklist
            </h4>
            <span className="text-xs text-slate-400">
              {incident.actions_completed.length} of {incident.required_actions.length} Done
            </span>
          </div>

          <div className="space-y-3" data-testid="crisis-actions-checklist">
            {incident.required_actions.map((act) => {
              const isDone = incident.actions_completed.includes(act)
              const actionId = act.split(':')[0].trim()
              const isBusy = completingActionId === actionId

              return (
                <div
                  key={act}
                  data-testid={`crisis-action-item-${actionId}`}
                  className={`flex items-start justify-between gap-3 rounded-lg border p-3 transition-colors ${
                    isDone
                      ? 'border-emerald-800/50 bg-emerald-950/20 text-slate-300'
                      : 'border-slate-800 bg-slate-950/80 text-white hover:border-slate-700'
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <input
                      type="checkbox"
                      data-testid={`action-checkbox-${actionId}`}
                      checked={isDone}
                      disabled={isDone || isBusy}
                      onChange={() => handleCompleteAction(act)}
                      className="mt-1 h-4 w-4 rounded border-slate-700 bg-slate-800 text-rose-600 focus:ring-rose-500 cursor-pointer disabled:cursor-not-allowed"
                    />
                    <div>
                      <div className={`text-xs font-semibold ${isDone ? 'line-through text-slate-400' : 'text-slate-100'}`}>
                        {act}
                      </div>
                      <div className="mt-1 flex items-center gap-2 text-[11px] text-slate-500">
                        <span className="font-mono text-cyan-400">{actionId}</span>
                        {isDone ? (
                          <span className="text-emerald-400 font-medium">Verified & Recorded</span>
                        ) : (
                          <span className="text-amber-400/90 font-medium">Pending Statutory Action</span>
                        )}
                      </div>
                    </div>
                  </div>

                  {!isDone && (
                    <button
                      data-testid={`complete-action-btn-${actionId}`}
                      onClick={() => handleCompleteAction(act)}
                      disabled={isBusy}
                      className="shrink-0 rounded bg-slate-800 px-2.5 py-1 text-[11px] font-semibold text-slate-200 hover:bg-slate-700 transition-colors disabled:opacity-50"
                    >
                      {isBusy ? 'Saving...' : 'Verify'}
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* Standardized RBI Annex II Incident Disclosure Draft */}
        <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-5 flex flex-col justify-between">
          <div>
            <div className="mb-4 flex items-center justify-between border-b border-slate-800 pb-3">
              <div>
                <h4 className="text-sm font-bold text-white uppercase tracking-wider">
                  RBI Annex II Incident Disclosure Form
                </h4>
                <p className="text-xs text-slate-400">
                  Pre-compiled statutory dossier draft for CISO/Compliance Officer sign-off
                </p>
              </div>
              <button
                data-testid="copy-disclosure-btn"
                onClick={copyToClipboard}
                className="shrink-0 rounded bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-cyan-500 transition-colors"
              >
                {copiedDraft ? 'Copied!' : 'Copy Draft'}
              </button>
            </div>

            <div
              data-testid="disclosure-draft-preview"
              className="max-h-80 overflow-y-auto rounded-lg border border-slate-800 bg-slate-950 p-4 font-mono text-xs text-slate-300 leading-relaxed whitespace-pre-wrap select-all"
            >
              {incident.disclosure_draft}
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-slate-800/80 text-[11px] text-slate-400 flex items-center justify-between">
            <span>Certification Authority: RBI Cyber Crisis Management Cell</span>
            <span className="font-semibold text-amber-400">Mandatory Review Before Final Submission</span>
          </div>
        </div>
      </div>

      {/* Declare Incident Modal */}
      {showDeclareModal && (
        <div
          data-testid="declare-modal-backdrop"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
        >
          <div
            data-testid="declare-modal-content"
            className="w-full max-w-lg rounded-xl border border-rose-800 bg-slate-900 p-6 shadow-2xl"
          >
            <div className="mb-4 flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-base font-bold text-white uppercase tracking-wider">
                Declare Regulatory Cyber Crisis Incident
              </h3>
              <button
                onClick={() => setShowDeclareModal(false)}
                className="text-slate-400 hover:text-white text-sm"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleDeclareIncident} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Severity Classification</label>
                <div className="flex gap-4">
                  <label className="flex items-center gap-2 text-xs text-slate-200 cursor-pointer">
                    <input
                      type="radio"
                      name="severity"
                      value="SEV1"
                      checked={newSeverity === 'SEV1'}
                      onChange={() => setNewSeverity('SEV1')}
                      className="text-rose-600"
                    />
                    <strong className="text-rose-400">SEV1</strong> (Core outage / potential data compromise)
                  </label>
                  <label className="flex items-center gap-2 text-xs text-slate-200 cursor-pointer">
                    <input
                      type="radio"
                      name="severity"
                      value="SEV2"
                      checked={newSeverity === 'SEV2'}
                      onChange={() => setNewSeverity('SEV2')}
                      className="text-amber-600"
                    />
                    <strong className="text-amber-400">SEV2</strong> (Lateral anomaly / secondary service)
                  </label>
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Incident Summary (min 20 characters)
                </label>
                <textarea
                  data-testid="declare-summary-input"
                  rows={3}
                  value={newSummary}
                  onChange={(e) => setNewSummary(e.target.value)}
                  placeholder="Describe detected anomaly, symptoms, and initial forensic observations..."
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 p-2.5 text-xs text-white placeholder-slate-500 focus:border-rose-500 focus:outline-none"
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Impacted Systems (comma-separated)
                </label>
                <input
                  type="text"
                  data-testid="declare-systems-input"
                  value={newSystems}
                  onChange={(e) => setNewSystems(e.target.value)}
                  placeholder="e.g. core-switch, payment-api, auth-token-db"
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 p-2.5 text-xs text-white placeholder-slate-500 focus:border-rose-500 focus:outline-none"
                  required
                />
              </div>

              <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowDeclareModal(false)}
                  className="rounded px-4 py-2 text-xs text-slate-300 hover:bg-slate-800"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  data-testid="submit-declare-incident-btn"
                  disabled={isLoading}
                  className="rounded bg-rose-600 px-4 py-2 text-xs font-semibold text-white hover:bg-rose-500 disabled:opacity-50"
                >
                  {isLoading ? 'Initializing...' : 'Declare & Start 6h Countdown'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
export default CrisisConsole
