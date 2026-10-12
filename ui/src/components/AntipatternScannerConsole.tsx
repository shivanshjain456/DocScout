// DocScout Regulatory and Technical Antipattern Scanner (FEAT-033)
// Scans internal compliance manuals, SOPs, and technical architecture documents
// against the 30 canonical taxonomy antipatterns to pinpoint systemic risks.

import React, { useState, useEffect } from 'react'

export interface AntipatternFinding {
  rule_id: string
  practice: string
  antipattern: string
  consequence: string
  instead: string[]
  severity: string
  domain_category: string
  matched_snippet: string
  line_number?: number | null
  confidence: number
}

export interface ScanAntipatternsResponse {
  document_name: string
  findings: AntipatternFinding[]
  total_findings: number
  critical_count: number
  high_count: number
  medium_count: number
  overall_score: number
  affected_domains: string[]
  is_healthy: boolean
  latency_ms: number
}

export interface AntipatternRule {
  id: string
  practice: string
  antipattern: string
  consequence: string
  instead: string[]
  domain_category: string
  severity: string
}

export interface AntipatternBenchmarkResponse {
  total_seeded_antipatterns: number
  detected_antipatterns: number
  false_positives: number
  false_negatives: number
  recall: number
  precision: number
  overall_score: number
  benchmark_passed: boolean
}

const SAMPLE_PRESETS: { label: string; text: string }[] = [
  {
    label: 'Legacy Testing & Quality Manual',
    text: `All microservices must enforce 90% line coverage as a quality target before merge.
To prevent intermittent CI delays, teams should add automatic retries to a failing test suite.
Engineers must mock everything so that tests verify the test's own assumptions rather than real behaviour.`,
  },
  {
    label: 'Risky Deployment & Chaos SOP',
    text: `The resilience team executes chaos experiments by breaking things in production without a steady-state hypothesis.
When testing canaries, routing 5% of traffic to a canary and watching a dashboard by eye is the standard protocol.
Deployments proceed by switching traffic without accounting for in-flight requests or session draining.`,
  },
  {
    label: 'Uncalibrated AI & LLM Policy',
    text: `Evaluations adopt judge scores as ground truth without validating the judge or running human calibration.
Security testing focuses exclusively on testing only direct user-supplied injections in the front-end chat interface.
For model risk, our policy treats model validation as a one-time pre-launch sign-off.`,
  },
  {
    label: 'Shallow Security & Audit Strategy',
    text: `Security assurance is validated by running an annual penetration test as the primary evidence that controls work.
Compliance officers ensure collecting evidence by screenshot shortly before the audit window closes.
Metrics ingestion attaches user IDs, request IDs and raw URL paths as metric labels in Prometheus.`,
  },
]

export const AntipatternScannerConsole: React.FC = () => {
  const [inputText, setInputText] = useState<string>(SAMPLE_PRESETS[0].text)
  const [docName, setDocName] = useState<string>('policy_manual_2024.md')
  const [scanResult, setScanResult] = useState<ScanAntipatternsResponse | null>(null)
  const [catalog, setCatalog] = useState<AntipatternRule[]>([])
  const [benchmarkResult, setBenchmarkResult] = useState<AntipatternBenchmarkResponse | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(false)
  const [isBenchmarking, setIsBenchmarking] = useState<boolean>(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'scanner' | 'directory'>('scanner')
  const [selectedDomain, setSelectedDomain] = useState<string>('')
  const [copiedInstead, setCopiedInstead] = useState<string | null>(null)

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
        const res = await fetch('/v1/compliance/antipatterns/catalog', {
          headers: getHeaders(),
        })
        if (res.ok) {
          const data = await res.json()
          setCatalog(data.rules || [])
        }
      } catch (err) {
        console.error('Failed to load antipattern catalog:', err)
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
      const res = await fetch('/v1/compliance/antipatterns/scan', {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          text: inputText,
          document_name: docName,
        }),
      })

      if (!res.ok) {
        throw new Error(`Scan request failed with HTTP ${res.status}`)
      }

      const data: ScanAntipatternsResponse = await res.json()
      setScanResult(data)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      setErrorMsg(message)
    } finally {
      setIsLoading(false)
    }
  }

  async function runBenchmark() {
    setIsBenchmarking(true)
    try {
      const res = await fetch('/v1/compliance/antipatterns/benchmark', {
        headers: getHeaders(),
      })
      if (res.ok) {
        const data: AntipatternBenchmarkResponse = await res.json()
        setBenchmarkResult(data)
      }
    } catch (err) {
      console.error('Benchmark execution failed:', err)
    } finally {
      setIsBenchmarking(false)
    }
  }

  function handleCopyAlternative(alt: string, id: string) {
    navigator.clipboard.writeText(alt)
    setCopiedInstead(id)
    setTimeout(() => setCopiedInstead(null), 2000)
  }

  const getSeverityBadge = (sev: string) => {
    switch (sev.toUpperCase()) {
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

  const getScoreColor = (score: number) => {
    if (score >= 80) return 'text-emerald-400'
    if (score >= 50) return 'text-amber-400'
    return 'text-red-400'
  }

  const filteredCatalog = selectedDomain
    ? catalog.filter((r) => r.domain_category.toLowerCase() === selectedDomain.toLowerCase())
    : catalog

  return (
    <div className="bg-slate-900 text-slate-100 p-6 rounded-xl border border-slate-800 shadow-2xl space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-slate-800">
        <div>
          <div className="flex items-center gap-2">
            <span className="px-2.5 py-0.5 rounded text-xs font-semibold bg-rose-500/20 text-rose-300 border border-rose-500/30">
              FEAT-033
            </span>
            <h2 className="text-xl font-bold tracking-tight text-white">
              Regulatory and Technical Antipattern Scanner
            </h2>
          </div>
          <p className="text-sm text-slate-400 mt-1">
            Scans internal compliance manuals, policies, and engineering practices against 30 taxonomy antipatterns.
          </p>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={runBenchmark}
            disabled={isBenchmarking}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-amber-300 border border-amber-500/30 transition flex items-center gap-1.5"
          >
            <span>{isBenchmarking ? 'Evaluating...' : 'Run Benchmark (>90%)'}</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('scanner')}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition ${
              activeTab === 'scanner'
                ? 'bg-amber-600 text-white shadow'
                : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
            }`}
          >
            Manual Scanner
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('directory')}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition ${
              activeTab === 'directory'
                ? 'bg-amber-600 text-white shadow'
                : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
            }`}
          >
            30 Antipatterns Directory ({catalog.length})
          </button>
        </div>
      </div>

      {errorMsg && (
        <div className="p-4 bg-red-900/30 border border-red-700 rounded-lg text-red-200 text-sm">
          {errorMsg}
        </div>
      )}

      {/* Benchmark Banner */}
      {benchmarkResult && (
        <div className="p-4 rounded-lg bg-emerald-950/40 border border-emerald-700/60 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="px-2.5 py-1 rounded text-xs font-bold uppercase bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
              Benchmark Passed
            </span>
            <span className="text-sm text-emerald-200">
              Detection Recall:{' '}
              <strong className="text-white text-base">{(benchmarkResult.recall * 100).toFixed(1)}%</strong> &bull; Precision:{' '}
              <strong className="text-white text-base">{(benchmarkResult.precision * 100).toFixed(1)}%</strong>
            </span>
          </div>
          <div className="flex gap-4 text-xs text-slate-300">
            <span>Detected: {benchmarkResult.detected_antipatterns} / {benchmarkResult.total_seeded_antipatterns}</span>
            <span>False Positives: {benchmarkResult.false_positives}</span>
            <span>Manual Score: {benchmarkResult.overall_score}/100</span>
          </div>
        </div>
      )}

      {activeTab === 'scanner' ? (
        <div className="space-y-6">
          {/* Quick Presets */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Sample Policy Documents
            </label>
            <div className="flex flex-wrap gap-2">
              {SAMPLE_PRESETS.map((p, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={() => setInputText(p.text)}
                  className="px-2.5 py-1 text-xs rounded bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition"
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* Form */}
          <form onSubmit={handleScan} className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="md:col-span-3">
                <label htmlFor="manual-text-input" className="text-xs text-slate-400">
                  Compliance Manual or Architecture Spec
                </label>
                <textarea
                  id="manual-text-input"
                  rows={5}
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  placeholder="Paste organizational guidelines, architecture specifications, or test policy..."
                  className="w-full mt-1 bg-slate-950 border border-slate-700 rounded-lg p-3 text-sm text-slate-200 font-mono focus:outline-none focus:border-amber-500"
                />
              </div>

              <div className="flex flex-col justify-between space-y-3">
                <div>
                  <label htmlFor="doc-name-input" className="text-xs text-slate-400">Document Identifier</label>
                  <input
                    id="doc-name-input"
                    type="text"
                    value={docName}
                    onChange={(e) => setDocName(e.target.value)}
                    className="w-full mt-1 bg-slate-950 border border-slate-700 rounded-lg p-2 text-sm text-slate-200 focus:outline-none focus:border-amber-500"
                  />
                </div>

                <button
                  type="submit"
                  disabled={isLoading || !inputText.trim()}
                  className="w-full bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white font-medium py-2.5 rounded-lg transition shadow-md"
                >
                  {isLoading ? 'Scanning Document...' : 'Scan for Antipatterns'}
                </button>
              </div>
            </div>
          </form>

          {/* Scan Results */}
          {scanResult && (
            <div className="space-y-4 pt-4 border-t border-slate-800">
              {/* Score Bar */}
              <div className="p-4 bg-slate-950 rounded-lg border border-slate-800 flex flex-wrap items-center justify-between gap-4">
                <div className="flex items-center gap-4">
                  <div className="text-center">
                    <div className="text-xs text-slate-400">Health Score</div>
                    <div className={`text-2xl font-black ${getScoreColor(scanResult.overall_score)}`}>
                      {scanResult.overall_score}/100
                    </div>
                  </div>

                  <span
                    className={`px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wide ${
                      scanResult.is_healthy
                        ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'
                        : 'bg-red-500/20 text-red-400 border border-red-500/40'
                    }`}
                  >
                    {scanResult.is_healthy ? 'Acceptable Posture' : 'Critical Antipatterns Present'}
                  </span>
                </div>

                <div className="flex gap-4 text-xs text-slate-300">
                  <span className="text-red-400 font-semibold">{scanResult.critical_count} Critical</span>
                  <span className="text-amber-400 font-semibold">{scanResult.high_count} High</span>
                  <span className="text-yellow-400 font-semibold">{scanResult.medium_count} Medium</span>
                  <span>Latency: {scanResult.latency_ms} ms</span>
                </div>
              </div>

              {scanResult.total_findings === 0 ? (
                <div className="p-8 text-center bg-slate-950 rounded-lg border border-slate-800 text-emerald-400">
                  Zero organizational antipatterns detected in document.
                </div>
              ) : (
                <div className="space-y-4">
                  {scanResult.findings.map((finding) => (
                    <div
                      key={finding.rule_id}
                      className="p-5 bg-slate-950 rounded-lg border border-slate-800 space-y-3 hover:border-slate-700 transition"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <span className={`px-2 py-0.5 rounded text-xs font-bold ${getSeverityBadge(finding.severity)}`}>
                            {finding.severity}
                          </span>
                          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                            {finding.practice}
                          </span>
                          <span className="px-2 py-0.5 rounded text-[11px] bg-slate-800 text-slate-400">
                            Domain: {finding.domain_category}
                          </span>
                        </div>

                        {finding.line_number && (
                          <span className="text-xs text-slate-500">Line {finding.line_number}</span>
                        )}
                      </div>

                      <h4 className="text-sm font-bold text-white">{finding.antipattern}</h4>

                      {/* Matched Snippet */}
                      <div className="p-2.5 rounded bg-slate-900 border border-slate-800 text-xs font-mono text-amber-200">
                        "{finding.matched_snippet}"
                      </div>

                      {/* Consequence */}
                      <div className="p-3 bg-red-950/20 border border-red-900/30 rounded text-xs text-red-200">
                        <strong className="text-red-300">Failure Consequence:</strong> {finding.consequence}
                      </div>

                      {/* Instead Replacements */}
                      <div className="space-y-1 pt-1">
                        <div className="text-xs font-semibold text-emerald-400 uppercase tracking-wider">
                          Prescriptive Instead-Of Replacements
                        </div>
                        <div className="flex flex-wrap gap-2 pt-1">
                          {finding.instead.map((alt, aIdx) => (
                            <button
                              key={aIdx}
                              type="button"
                              onClick={() => handleCopyAlternative(alt, `${finding.rule_id}-${aIdx}`)}
                              className="px-2.5 py-1 text-xs rounded bg-slate-800 hover:bg-slate-700 text-emerald-300 border border-slate-700 flex items-center gap-1.5 transition"
                            >
                              <span>{alt}</span>
                              <span className="text-slate-500 text-[10px]">
                                {copiedInstead === `${finding.rule_id}-${aIdx}` ? 'Copied' : 'Copy'}
                              </span>
                            </button>
                          ))}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        /* Directory Tab */
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-slate-400 mr-1">Filter Domain:</span>
            {['', 'testing', 'reliability', 'ai_llm', 'security', 'observability', 'deployment', 'governance'].map(
              (dom) => (
                <button
                  key={dom}
                  type="button"
                  onClick={() => setSelectedDomain(dom)}
                  className={`px-2.5 py-1 text-xs rounded transition ${
                    selectedDomain === dom
                      ? 'bg-amber-600 text-white'
                      : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                  }`}
                >
                  {dom ? dom.replace('_', ' ') : 'All Domains'}
                </button>
              )
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {filteredCatalog.map((item) => (
              <div
                key={item.id}
                className="p-4 bg-slate-950 rounded-lg border border-slate-800 space-y-3 flex flex-col justify-between"
              >
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                      {item.practice}
                    </span>
                    <span className={`px-2 py-0.5 rounded text-[11px] font-bold ${getSeverityBadge(item.severity)}`}>
                      {item.severity}
                    </span>
                  </div>

                  <h4 className="text-sm font-bold text-white">{item.antipattern}</h4>
                  <p className="text-xs text-slate-400">{item.consequence}</p>
                </div>

                <div className="space-y-1 pt-2 border-t border-slate-900 text-xs">
                  <span className="text-emerald-400 font-semibold">Adopt instead:</span>
                  <div className="text-slate-300">{item.instead.join(', ')}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
export default AntipatternScannerConsole
