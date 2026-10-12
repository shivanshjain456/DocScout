// DocScout Statutory Deprecation and Supersession Engine (FEAT-031)
// Scans internal policies, compliance manuals, and circular citations for obsolete
// directives, repealed clauses, and technical antipatterns.

import React, { useState, useEffect } from 'react'

export interface DeprecationDetection {
  deprecation_id: string
  matched_text: string
  subject: string
  subject_type: string
  regulator: string
  status: string
  severity: string
  superseded_by?: string | null
  active_authority?: string | null
  supersession_chain: string[]
  reason: string
  replacement: string[]
  guidance: string
  effective_date: string
  sunset_date?: string | null
  is_sunset_passed: boolean
  grandfathering_clause?: string | null
}

export interface CheckSupersessionResponse {
  detections: DeprecationDetection[]
  total_flagged: number
  critical_count: number
  high_count: number
  medium_count: number
  low_count: number
  is_compliant: boolean
  recommended_actions: string[]
  latency_ms: number
}

export interface StatutoryDeprecation {
  id: string
  subject: string
  subject_type: string
  regulator: string
  status: string
  reason: string
  superseded_by?: string | null
  effective_date: string
  sunset_date?: string | null
  grandfathering_clause?: string | null
  replacement: string[]
  guidance: string
  severity: string
  is_sunset_passed: boolean
}

const SAMPLE_PRESETS: { label: string; text: string; regulator?: string }[] = [
  {
    label: 'Legacy RBI KYC Procedures',
    text: 'Customer onboarding follows RBI KYC Guidelines 2002 (DBOD.AML.BC.18/14.01.001/2002-03) with annual branch visits.',
    regulator: 'RBI',
  },
  {
    label: 'Outdated IT Outsourcing Policy',
    text: 'Outsourcing of Core Banking infrastructure governed by DBOD.No.BP.40/21.04.158/2006-07 guidelines.',
    regulator: 'RBI',
  },
  {
    label: 'Raw Card-on-File Storage',
    text: 'Payment service aggregator retains Card-on-File plain text storage for accelerated customer 1-click checkout.',
    regulator: 'RBI',
  },
  {
    label: 'Technical Antipatterns in Quality Manual',
    text: 'Engineering standard mandates 90% line coverage as a quality target, relies on blind test retries in CI, and utilizes DREAD scoring with Netflix Hystrix.',
    regulator: 'INDUSTRY_STANDARD',
  },
  {
    label: 'Legacy SEBI Listing & Cyber Compliance',
    text: 'Company complies with Clause 49 corporate governance and CIR/MIRSD/1/2015 Cybersecurity Framework.',
    regulator: 'SEBI',
  },
  {
    label: 'PMLA 25% Beneficial Ownership',
    text: 'Corporate client identification applied under 25% beneficial ownership threshold for controlling persons.',
    regulator: 'PMLA',
  },
]

export const StatutoryDeprecationScanner: React.FC = () => {
  const [inputText, setInputText] = useState<string>(SAMPLE_PRESETS[0].text)
  const [asOfDate, setAsOfDate] = useState<string>('')
  const [regulatorFilter, setRegulatorFilter] = useState<string>('')
  const [scanResult, setScanResult] = useState<CheckSupersessionResponse | null>(null)
  const [catalog, setCatalog] = useState<StatutoryDeprecation[]>([])
  const [isLoading, setIsLoading] = useState<boolean>(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'scanner' | 'catalog'>('scanner')
  const [copiedId, setCopiedId] = useState<string | null>(null)

  const apiKey = localStorage.getItem('docscout_api_key') || ''

  const getHeaders = (): Record<string, string> => {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (apiKey) {
      if (apiKey.startsWith('Bearer ')) headers['Authorization'] = apiKey
      else headers['X-API-Key'] = apiKey
    }
    return headers
  }

  // Load catalog on mount
  useEffect(() => {
    async function fetchCatalog() {
      try {
        const res = await fetch('/v1/compliance/deprecations', {
          headers: getHeaders(),
        })
        if (res.ok) {
          const data = await res.json()
          setCatalog(data.deprecations || [])
        }
      } catch (err) {
        console.error('Failed to load deprecation catalog:', err)
      }
    }
    fetchCatalog()
  }, [])

  async function handleScan(e?: React.FormEvent) {
    if (e) e.preventDefault()
    if (!inputText.trim()) return

    setIsLoading(true)
    setErrorMsg(null)

    try {
      const payload: Record<string, unknown> = { text: inputText }
      if (asOfDate) payload.as_of_date = asOfDate
      if (regulatorFilter) payload.regulator = regulatorFilter

      const res = await fetch('/v1/compliance/check-supersession', {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify(payload),
      })

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        throw new Error(errData.detail || `Scan request failed with HTTP ${res.status}`)
      }

      const data: CheckSupersessionResponse = await res.json()
      setScanResult(data)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Unknown scan error'
      setErrorMsg(message)
    } finally {
      setIsLoading(false)
    }
  }

  function handleCopyReplacement(rep: string, id: string) {
    navigator.clipboard.writeText(rep)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 2000)
  }

  const getSeverityBadge = (severity: string) => {
    switch (severity.toUpperCase()) {
      case 'CRITICAL':
        return 'bg-red-500/20 text-red-300 border border-red-500/40'
      case 'HIGH':
        return 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
      case 'MEDIUM':
        return 'bg-yellow-500/20 text-yellow-300 border border-yellow-500/40'
      default:
        return 'bg-blue-500/20 text-blue-300 border border-blue-500/40'
    }
  }

  const getStatusBadge = (status: string) => {
    switch (status.toLowerCase()) {
      case 'superseded':
        return 'bg-orange-500/20 text-orange-300 border border-orange-500/30'
      case 'repealed':
        return 'bg-red-500/20 text-red-300 border border-red-500/30'
      case 'anti_pattern':
        return 'bg-purple-500/20 text-purple-300 border border-purple-500/30'
      case 'sunset_expired':
        return 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
      default:
        return 'bg-slate-500/20 text-slate-300 border border-slate-500/30'
    }
  }

  return (
    <div className="bg-slate-900 text-slate-100 p-6 rounded-xl border border-slate-800 shadow-2xl space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-slate-800">
        <div>
          <div className="flex items-center gap-2">
            <span className="px-2.5 py-0.5 rounded text-xs font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/30">
              FEAT-031
            </span>
            <h2 className="text-xl font-bold tracking-tight text-white">
              Statutory Deprecation and Supersession Engine
            </h2>
          </div>
          <p className="text-sm text-slate-400 mt-1">
            Detects superseded circulars, repealed guidelines, and engineering antipatterns with recursive authority tracing.
          </p>
        </div>

        {/* Tab Controls */}
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setActiveTab('scanner')}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition ${
              activeTab === 'scanner'
                ? 'bg-amber-600 text-white shadow'
                : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
            }`}
          >
            Policy Scanner
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('catalog')}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition ${
              activeTab === 'catalog'
                ? 'bg-amber-600 text-white shadow'
                : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
            }`}
          >
            Deprecations Catalog ({catalog.length})
          </button>
        </div>
      </div>

      {errorMsg && (
        <div className="p-4 bg-red-900/30 border border-red-700 rounded-lg text-red-200 text-sm">
          {errorMsg}
        </div>
      )}

      {activeTab === 'scanner' ? (
        <div className="space-y-6">
          {/* Preset Buttons */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Quick Test Presets
            </label>
            <div className="flex flex-wrap gap-2">
              {SAMPLE_PRESETS.map((p, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={() => {
                    setInputText(p.text)
                    setRegulatorFilter(p.regulator || '')
                  }}
                  className="px-2.5 py-1 text-xs rounded bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition"
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* Scanner Input Form */}
          <form onSubmit={handleScan} className="space-y-4">
            <div className="space-y-2">
              <label htmlFor="policy-text-input" className="text-sm font-medium text-slate-300">
                Regulatory Policy, Submission, or Architecture Text
              </label>
              <textarea
                id="policy-text-input"
                rows={4}
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                placeholder="Paste compliance policy, circular references, or architecture standards..."
                className="w-full bg-slate-950 border border-slate-700 rounded-lg p-3 text-sm font-mono text-slate-200 focus:outline-none focus:border-amber-500 focus:ring-1 focus:ring-amber-500"
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label htmlFor="regulator-filter-input" className="text-xs font-medium text-slate-400">
                  Regulator Filter
                </label>
                <select
                  id="regulator-filter-input"
                  value={regulatorFilter}
                  onChange={(e) => setRegulatorFilter(e.target.value)}
                  className="w-full mt-1 bg-slate-800 border border-slate-700 rounded-lg p-2 text-sm text-slate-200 focus:outline-none focus:border-amber-500"
                >
                  <option value="">All Regulators</option>
                  <option value="RBI">RBI (Reserve Bank of India)</option>
                  <option value="SEBI">SEBI (Securities and Exchange Board)</option>
                  <option value="PMLA">PMLA (Prevention of Money Laundering)</option>
                  <option value="BASEL">Basel Committee</option>
                  <option value="INDUSTRY_STANDARD">Industry Technical Standard</option>
                </select>
              </div>

              <div>
                <label htmlFor="as-of-date-input" className="text-xs font-medium text-slate-400">
                  Point-in-Time Date (Optional)
                </label>
                <input
                  id="as-of-date-input"
                  type="date"
                  value={asOfDate}
                  onChange={(e) => setAsOfDate(e.target.value)}
                  className="w-full mt-1 bg-slate-800 border border-slate-700 rounded-lg p-2 text-sm text-slate-200 focus:outline-none focus:border-amber-500"
                />
              </div>

              <div className="flex items-end">
                <button
                  type="submit"
                  disabled={isLoading || !inputText.trim()}
                  className="w-full bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white font-medium py-2 px-4 rounded-lg transition shadow-md flex items-center justify-center gap-2"
                >
                  {isLoading ? 'Scanning Text...' : 'Scan for Deprecations'}
                </button>
              </div>
            </div>
          </form>

          {/* Scan Results */}
          {scanResult && (
            <div className="space-y-4 pt-4 border-t border-slate-800">
              <div className="flex flex-wrap items-center justify-between gap-4 p-4 rounded-lg bg-slate-950 border border-slate-800">
                <div className="flex items-center gap-3">
                  <span
                    className={`px-3 py-1 rounded-full text-xs font-bold tracking-wide uppercase ${
                      scanResult.is_compliant
                        ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'
                        : 'bg-red-500/20 text-red-400 border border-red-500/40'
                    }`}
                  >
                    {scanResult.is_compliant ? 'Compliant' : 'Deprecations Detected'}
                  </span>
                  <span className="text-sm text-slate-300">
                    <strong>{scanResult.total_flagged}</strong> items flagged
                  </span>
                </div>

                <div className="flex gap-3 text-xs text-slate-400">
                  <span className="text-red-400 font-semibold">{scanResult.critical_count} Critical</span>
                  <span className="text-amber-400 font-semibold">{scanResult.high_count} High</span>
                  <span className="text-yellow-400 font-semibold">{scanResult.medium_count} Medium</span>
                  <span>Latency: {scanResult.latency_ms} ms</span>
                </div>
              </div>

              {scanResult.total_flagged === 0 ? (
                <div className="p-8 text-center bg-slate-950/60 rounded-lg border border-slate-800">
                  <p className="text-emerald-400 font-medium">
                    Zero superseded circulars or deprecated practices found in provided text.
                  </p>
                </div>
              ) : (
                <div className="space-y-4">
                  {scanResult.detections.map((det) => (
                    <div
                      key={det.deprecation_id}
                      className="p-5 rounded-lg bg-slate-950 border border-slate-800 space-y-4 hover:border-slate-700 transition"
                    >
                      {/* Top Badges */}
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <span className={`px-2 py-0.5 rounded text-xs font-bold ${getSeverityBadge(det.severity)}`}>
                            {det.severity}
                          </span>
                          <span className={`px-2 py-0.5 rounded text-xs font-medium ${getStatusBadge(det.status)}`}>
                            {det.status.toUpperCase()}
                          </span>
                          <span className="px-2 py-0.5 rounded text-xs bg-slate-800 text-slate-400">
                            {det.regulator}
                          </span>
                        </div>

                        {det.sunset_date && (
                          <div className="text-xs">
                            {det.is_sunset_passed ? (
                              <span className="text-rose-400 font-medium bg-rose-950/50 px-2 py-0.5 rounded border border-rose-800">
                                Sunset Passed ({det.sunset_date})
                              </span>
                            ) : (
                              <span className="text-emerald-400 font-medium bg-emerald-950/50 px-2 py-0.5 rounded border border-emerald-800">
                                Active Grace Period (Sunsets {det.sunset_date})
                              </span>
                            )}
                          </div>
                        )}
                      </div>

                      {/* Title & Matched Text */}
                      <div>
                        <h4 className="text-base font-semibold text-white">{det.subject}</h4>
                        <p className="text-xs text-slate-400 mt-0.5">
                          Matched fragment: <code className="text-amber-300 bg-amber-950/30 px-1 py-0.5 rounded font-mono">"{det.matched_text}"</code>
                        </p>
                      </div>

                      {/* Reason */}
                      <p className="text-sm text-slate-300 leading-relaxed">{det.reason}</p>

                      {/* Supersession Chain */}
                      {det.supersession_chain && det.supersession_chain.length > 1 && (
                        <div className="p-3 bg-slate-900 rounded-lg border border-slate-800">
                          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
                            Supersession Authority Chain
                          </div>
                          <div className="flex flex-wrap items-center gap-2 text-xs">
                            {det.supersession_chain.map((link, idx) => (
                              <React.Fragment key={idx}>
                                <span
                                  className={`px-2 py-1 rounded ${
                                    idx === det.supersession_chain.length - 1
                                      ? 'bg-emerald-900/40 text-emerald-300 border border-emerald-700 font-semibold'
                                      : 'bg-slate-800 text-slate-400 line-through'
                                  }`}
                                >
                                  {link}
                                </span>
                                {idx < det.supersession_chain.length - 1 && (
                                  <span className="text-amber-500 font-bold">&rarr;</span>
                                )}
                              </React.Fragment>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Grandfathering Notice */}
                      {det.grandfathering_clause && (
                        <div className="p-3 bg-blue-950/30 border border-blue-800/40 rounded-lg text-xs text-blue-300">
                          <strong>Grandfathering Provision:</strong> {det.grandfathering_clause}
                        </div>
                      )}

                      {/* Replacements & Guidance */}
                      <div className="space-y-2 pt-2 border-t border-slate-900">
                        <div className="text-xs font-semibold text-amber-400 uppercase tracking-wider">
                          Prescriptive Remediation
                        </div>
                        <p className="text-xs text-slate-300">{det.guidance}</p>

                        {det.replacement && det.replacement.length > 0 && (
                          <div className="flex flex-wrap items-center gap-2 pt-1">
                            <span className="text-xs text-slate-400">Adopt instead:</span>
                            {det.replacement.map((rep, rIdx) => (
                              <button
                                key={rIdx}
                                type="button"
                                onClick={() => handleCopyReplacement(rep, `${det.deprecation_id}-${rIdx}`)}
                                title="Click to copy replacement name"
                                className="px-2.5 py-1 text-xs rounded bg-slate-800 hover:bg-slate-700 text-emerald-300 border border-slate-700 flex items-center gap-1.5 transition"
                              >
                                <span>{rep}</span>
                                <span className="text-slate-500 text-[10px]">
                                  {copiedId === `${det.deprecation_id}-${rIdx}` ? 'Copied' : 'Copy'}
                                </span>
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        /* Deprecations Catalog Tab */
        <div className="space-y-4">
          <div className="text-sm text-slate-400">
            Authoritative registry of all tracked circular repeals, statutory supersessions, and engineering antipatterns.
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {catalog.map((item) => (
              <div
                key={item.id}
                className="p-4 bg-slate-950 rounded-lg border border-slate-800 space-y-3 flex flex-col justify-between"
              >
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className={`px-2 py-0.5 rounded text-[11px] font-bold ${getSeverityBadge(item.severity)}`}>
                      {item.severity}
                    </span>
                    <span className={`px-2 py-0.5 rounded text-[11px] font-medium ${getStatusBadge(item.status)}`}>
                      {item.status.toUpperCase()}
                    </span>
                  </div>

                  <h4 className="text-sm font-bold text-white">{item.subject}</h4>
                  <p className="text-xs text-slate-400">{item.reason}</p>
                </div>

                <div className="space-y-2 pt-2 border-t border-slate-900 text-xs">
                  <div className="text-slate-400">
                    <strong>Regulator:</strong> {item.regulator} &bull; <strong>Effective:</strong> {item.effective_date}
                  </div>
                  {item.replacement && item.replacement.length > 0 && (
                    <div className="text-emerald-400">
                      <strong>Replacement:</strong> {item.replacement.join(', ')}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
export default StatutoryDeprecationScanner
