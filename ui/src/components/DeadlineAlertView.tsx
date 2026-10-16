// DocScout Sunset Clause & Mandatory Cutover Alerting (FEAT-035)
// Tracks statutory transition deadlines, sunset dates, and countdown alerting for compliance officers.

import React, { useState } from 'react'

export interface RegulatoryDeadline {
  doc_id: string
  mandate_description: string
  effective_date: string
  days_remaining: number
  urgency_level: 'CRITICAL' | 'WARNING' | 'INFO'
  extracted_snippet?: string | null
  confidence: number
}

export interface ExtractDeadlinesResponse {
  doc_id: string
  total_deadlines: number
  deadlines: RegulatoryDeadline[]
  latency_ms: number
}

export interface DispatchDeadlineAlertsResponse {
  total_checked: number
  alerts_dispatched: number
  critical_count: number
  warning_count: number
  info_count: number
  duration_ms: number
}

const SAMPLE_CIRCULARS = [
  {
    label: 'RBI Card-on-File Tokenization (CoFT)',
    docId: 'doc-rbi-coft-2024',
    text: `Reserve Bank of India - Department of Payment and Settlement Systems.
Card-on-File Tokenization (CoFT) implementation timeline.
With a view to ensuring consumer data security, all regulated entities (REs) and
authorized payment aggregators shall transition to Card-on-File Tokenization (CoFT).
The timeline for implementation of CoFT guidelines is extended up to September 30, 2026.
No entity in the card transaction flow other than card issuers and card networks shall
store actual card details on or after October 01, 2026. All stakeholders are advised to comply.`,
  },
  {
    label: 'SEBI T+1 Settlement Cycle Migration',
    docId: 'doc-sebi-t1-settlement',
    text: `Securities and Exchange Board of India (SEBI) Circular on T+1 Settlement Cycle.
In super-session of previous circulars on settlement mechanics, all listed securities
shall transition by December 31, 2026 to the phased T+1 settlement mechanism.
Stock exchanges, clearing corporations, and depositories shall ensure that all trades
executed on and from January 01, 2027 shall settle on T+1 basis. Necessary infrastructure
upgrades shall be operationalized immediately.`,
  },
  {
    label: 'RBI Payment Aggregator Net Worth Milestones',
    docId: 'doc-rbi-pa-networth',
    text: `Guidelines for Regulation of Payment Aggregators and Payment Gateways.
Existing Payment Aggregators (PAs) shall achieve a minimum net-worth of Rs. 15 crore
by March 31, 2027 and a net-worth of Rs. 25 crore by March 31, 2028.
Applications for authorization shall be submitted on or before September 30, 2026.
Failure to achieve net-worth milestones will result in closure of operations.`,
  },
]

export const DeadlineAlertView: React.FC = () => {
  const [docId, setDocId] = useState<string>('doc-rbi-coft-2024')
  const [inputText, setInputText] = useState<string>(SAMPLE_CIRCULARS[0].text)
  const [referenceDate, setReferenceDate] = useState<string>('2026-09-01')
  const [criticalDays, setCriticalDays] = useState<number>(15)
  const [warningDays, setWarningDays] = useState<number>(45)
  const [loading, setLoading] = useState<boolean>(false)
  const [dispatchLoading, setDispatchLoading] = useState<boolean>(false)
  const [deadlines, setDeadlines] = useState<RegulatoryDeadline[]>([])
  const [latencyMs, setLatencyMs] = useState<number | null>(null)
  const [dispatchResult, setDispatchResult] = useState<DispatchDeadlineAlertsResponse | null>(null)
  const [recipientEmail, setRecipientEmail] = useState<string>('compliance@enterprise.bank')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const handleExtract = async () => {
    setLoading(true)
    setErrorMsg(null)
    setDispatchResult(null)

    try {
      const resp = await fetch('/v1/ingest/deadlines/extract', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          doc_id: docId,
          text: inputText,
          reference_date: referenceDate || null,
          critical_threshold_days: criticalDays,
          warning_threshold_days: warningDays,
        }),
      })

      if (!resp.ok) {
        const err = await resp.json()
        throw new Error(err.detail || 'Failed to extract statutory deadlines')
      }

      const data: ExtractDeadlinesResponse = await resp.json()
      setDeadlines(data.deadlines)
      setLatencyMs(data.latency_ms)
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  const handleDispatch = async () => {
    if (deadlines.length === 0) return
    setDispatchLoading(true)
    setErrorMsg(null)

    try {
      const resp = await fetch('/v1/compliance/deadlines/dispatch-alerts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          deadlines,
          recipients: [recipientEmail],
          dry_run: true,
        }),
      })

      if (!resp.ok) {
        const err = await resp.json()
        throw new Error(err.detail || 'Failed to dispatch deadline alerts')
      }

      const result: DispatchDeadlineAlertsResponse = await resp.json()
      setDispatchResult(result)
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : String(err))
    } finally {
      setDispatchLoading(false)
    }
  }

  const getUrgencyBadge = (level: 'CRITICAL' | 'WARNING' | 'INFO') => {
    switch (level) {
      case 'CRITICAL':
        return (
          <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-500/20 text-rose-300 border border-rose-500/30">
            CRITICAL (&le;15d)
          </span>
        )
      case 'WARNING':
        return (
          <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/30">
            WARNING (&le;45d)
          </span>
        )
      case 'INFO':
        return (
          <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-500/20 text-blue-300 border border-blue-500/30">
            INFO (&gt;45d)
          </span>
        )
    }
  }

  return (
    <div className="w-full max-w-7xl mx-auto p-6 space-y-8 text-slate-100 font-sans">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between pb-6 border-b border-slate-800 gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight text-white">
              Sunset Clause &amp; Mandatory Cutover Alerting
            </h1>
            <span className="px-2 py-0.5 rounded text-xs font-mono uppercase bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
              FEAT-035 Active
            </span>
          </div>
          <p className="text-sm text-slate-400 mt-1">
            Automated statutory cutover date extraction, transition window tracking, and Brevo countdown alerts.
          </p>
        </div>
        <div className="flex items-center gap-4 text-xs font-mono">
          <div className="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 flex flex-col">
            <span className="text-slate-500">Extraction SLO</span>
            <span className="text-emerald-400 font-semibold">&le; 2.0 ms</span>
          </div>
          <div className="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 flex flex-col">
            <span className="text-slate-500">Historical FP Rate</span>
            <span className="text-emerald-400 font-semibold">0.0% Guarded</span>
          </div>
        </div>
      </div>

      {/* Preset Selector */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs uppercase font-semibold text-slate-400 mr-2 tracking-wider">Presets:</span>
        {SAMPLE_CIRCULARS.map((p) => (
          <button
            key={p.docId}
            onClick={() => {
              setDocId(p.docId)
              setInputText(p.text)
            }}
            className="px-3 py-1 text-xs rounded-md bg-slate-800/80 hover:bg-slate-700 text-slate-200 border border-slate-700 transition"
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Controls & Text Area */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-4">
          <div className="flex gap-4">
            <div className="flex-1">
              <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">
                Circular Document ID
              </label>
              <input
                type="text"
                value={docId}
                onChange={(e) => setDocId(e.target.value)}
                className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-indigo-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">
                Reference Date (as of)
              </label>
              <input
                type="date"
                value={referenceDate}
                onChange={(e) => setReferenceDate(e.target.value)}
                className="px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-indigo-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">
              Circular Text (Directive or Gazette Excerpt)
            </label>
            <textarea
              rows={7}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              className="w-full px-4 py-3 bg-slate-900/90 border border-slate-700 rounded-lg text-sm font-mono text-slate-200 focus:outline-none focus:border-indigo-500 leading-relaxed"
              placeholder="Paste regulatory directive text here..."
            />
          </div>

          <div className="flex items-center gap-4">
            <button
              onClick={handleExtract}
              disabled={loading || !inputText}
              className="px-5 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-medium text-sm transition shadow-lg shadow-indigo-600/20"
            >
              {loading ? 'Extracting Deadlines...' : 'Extract Statutory Deadlines'}
            </button>
            {latencyMs !== null && (
              <span className="text-xs text-slate-400 font-mono">
                Extracted in <span className="text-emerald-400 font-semibold">{latencyMs} ms</span>
              </span>
            )}
          </div>
        </div>

        {/* Configuration & Dispatch Panel */}
        <div className="p-5 rounded-xl bg-slate-900/80 border border-slate-800 space-y-4">
          <h3 className="text-sm font-semibold text-white uppercase tracking-wider">Alert Thresholds</h3>
          <div className="space-y-3">
            <div>
              <label className="block text-xs text-slate-400 mb-1">Critical Threshold (days)</label>
              <input
                type="number"
                value={criticalDays}
                onChange={(e) => setCriticalDays(Number(e.target.value))}
                className="w-full px-3 py-1.5 bg-slate-800 border border-slate-700 rounded text-sm text-white"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">Warning Threshold (days)</label>
              <input
                type="number"
                value={warningDays}
                onChange={(e) => setWarningDays(Number(e.target.value))}
                className="w-full px-3 py-1.5 bg-slate-800 border border-slate-700 rounded text-sm text-white"
              />
            </div>
          </div>

          <hr className="border-slate-800" />

          <h3 className="text-sm font-semibold text-white uppercase tracking-wider">Brevo Countdown Dispatch</h3>
          <div className="space-y-3">
            <div>
              <label className="block text-xs text-slate-400 mb-1">Recipient Compliance Officer</label>
              <input
                type="email"
                value={recipientEmail}
                onChange={(e) => setRecipientEmail(e.target.value)}
                className="w-full px-3 py-1.5 bg-slate-800 border border-slate-700 rounded text-sm text-white"
              />
            </div>
            <button
              onClick={handleDispatch}
              disabled={dispatchLoading || deadlines.length === 0}
              className="w-full py-2 px-3 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-white text-xs font-semibold uppercase tracking-wider transition"
            >
              {dispatchLoading ? 'Dispatching...' : 'Dispatch Countdown Alert (Dry Run)'}
            </button>
          </div>

          {dispatchResult && (
            <div className="p-3 rounded-lg bg-slate-800/80 border border-emerald-500/30 text-xs space-y-1">
              <div className="text-emerald-400 font-semibold">Alert Pass Completed</div>
              <div className="text-slate-300">Checked: {dispatchResult.total_checked} deadlines</div>
              <div className="text-slate-300">Dispatched: {dispatchResult.alerts_dispatched} notifications</div>
              <div className="text-slate-400">Duration: {dispatchResult.duration_ms} ms</div>
            </div>
          )}
        </div>
      </div>

      {/* Error Banner */}
      {errorMsg && (
        <div className="p-4 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm">
          {errorMsg}
        </div>
      )}

      {/* Results View */}
      {deadlines.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white">
              Detected Statutory Deadlines ({deadlines.length})
            </h2>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {deadlines.map((dl, idx) => (
              <div
                key={idx}
                className="p-5 rounded-xl bg-slate-900 border border-slate-800 hover:border-slate-700 transition flex flex-col justify-between space-y-4"
              >
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    {getUrgencyBadge(dl.urgency_level)}
                    <span className="text-xl font-bold font-mono text-white">
                      {dl.days_remaining} <span className="text-xs font-normal text-slate-400">days left</span>
                    </span>
                  </div>
                  <div className="text-sm font-semibold text-slate-200">
                    Effective: <span className="text-indigo-400 font-mono">{dl.effective_date}</span>
                  </div>
                  <p className="text-xs text-slate-400 leading-relaxed italic border-l-2 border-indigo-500/40 pl-3">
                    &ldquo;{dl.mandate_description}&rdquo;
                  </p>
                </div>
                {dl.extracted_snippet && (
                  <div className="pt-2 border-t border-slate-800/80 text-[11px] font-mono text-slate-500">
                    Match: {dl.extracted_snippet}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default DeadlineAlertView
