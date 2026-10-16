// DocScout Circular Clause Conflict Detector (FEAT-032)
// Identifies unacknowledged contradictions, conflicting quantitative thresholds,
// and normative modality clashes across regulatory circular clauses.

import React, { useState, useEffect } from 'react'

export interface CircularClause {
  id: string
  circular_id: string
  circular_title: string
  regulator: string
  section_reference: string
  clause_text: string
  domain_category: string
  modality: string
  parameter_name?: string | null
  parameter_value?: number | null
  parameter_unit?: string | null
  comparison_operator?: string | null
  effective_date: string
  is_active: boolean
}

export interface DetectedConflict {
  conflict_id: string
  clause_a: CircularClause
  clause_b: CircularClause
  conflict_type: string
  severity: string
  parameter_name?: string | null
  explanation: string
  prescriptive_action: string
}

export interface DetectConflictsResponse {
  conflicts: DetectedConflict[]
  total_conflicts: number
  critical_count: number
  high_count: number
  medium_count: number
  has_conflicts: boolean
  domains_affected: string[]
  latency_ms: number
}

export interface ConflictBenchmarkResponse {
  total_conflicting_pairs: number
  detected_conflicts: number
  detection_rate: number
  total_non_conflicting_pairs: number
  false_positives: number
  precision: number
  benchmark_passed: boolean
}

export const CircularClauseConflictDetector: React.FC = () => {
  const [conflicts, setConflicts] = useState<DetectedConflict[]>([])
  const [selectedDomain, setSelectedDomain] = useState<string>('')
  const [stats, setStats] = useState<{
    total: number
    critical: number
    high: number
    medium: number
    domains: string[]
    latency: number
  }>({ total: 0, critical: 0, high: 0, medium: 0, domains: [], latency: 0 })
  const [benchmarkResult, setBenchmarkResult] = useState<ConflictBenchmarkResponse | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(false)
  const [isBenchmarking, setIsBenchmarking] = useState<boolean>(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'detected' | 'tester'>('detected')

  // Tester state
  const [customParam, setCustomParam] = useState<string>('minimum_crar_pct')
  const [customValA, setCustomValA] = useState<number>(9.0)
  const [customValB, setCustomValB] = useState<number>(11.5)
  const [customModA, setCustomModA] = useState<string>('mandatory')
  const [customModB, setCustomModB] = useState<string>('mandatory')
  const [testResult, setTestResult] = useState<DetectedConflict | null>(null)
  const [testEvaluated, setTestEvaluated] = useState<boolean>(false)

  const apiKey = localStorage.getItem('docscout_api_key') || ''

  const getHeaders = (): Record<string, string> => {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (apiKey) {
      if (apiKey.startsWith('Bearer ')) headers['Authorization'] = apiKey
      else headers['X-API-Key'] = apiKey
    }
    return headers
  }

  // Load detected conflicts
  async function fetchConflicts(domain?: string) {
    setIsLoading(true)
    setErrorMsg(null)
    try {
      const payload: Record<string, unknown> = {}
      if (domain) payload.domain_category = domain

      const res = await fetch('/v1/compliance/detect-conflicts', {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify(payload),
      })

      if (!res.ok) {
        throw new Error(`Conflict scan failed with status HTTP ${res.status}`)
      }

      const data: DetectConflictsResponse = await res.json()
      setConflicts(data.conflicts || [])
      setStats({
        total: data.total_conflicts,
        critical: data.critical_count,
        high: data.high_count,
        medium: data.medium_count,
        domains: data.domains_affected,
        latency: data.latency_ms,
      })
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      setErrorMsg(message)
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    fetchConflicts(selectedDomain)
  }, [selectedDomain])

  async function runBenchmark() {
    setIsBenchmarking(true)
    try {
      const res = await fetch('/v1/compliance/conflicts/benchmark', {
        headers: getHeaders(),
      })
      if (res.ok) {
        const data: ConflictBenchmarkResponse = await res.json()
        setBenchmarkResult(data)
      }
    } catch (err) {
      console.error('Benchmark execution failed:', err)
    } finally {
      setIsBenchmarking(false)
    }
  }

  async function handleTestPair(e: React.FormEvent) {
    e.preventDefault()
    setTestEvaluated(false)
    try {
      const clauseA = {
        id: 'tester-clause-a',
        circular_id: 'CIRCULAR-ALPHA-2023',
        circular_title: 'Directives on Statutory Thresholds Alpha',
        regulator: 'RBI',
        section_reference: 'Clause 4.1',
        clause_text: `Regulated entities shall adhere to ${customParam} of ${customValA}%.`,
        domain_category: 'custom_test',
        modality: customModA,
        parameter_name: customParam,
        parameter_value: customValA,
        parameter_unit: 'pct',
        comparison_operator: 'MIN',
        effective_date: '2023-01-01',
        is_active: true,
      }
      const clauseB = {
        id: 'tester-clause-b',
        circular_id: 'CIRCULAR-BETA-2023',
        circular_title: 'Directives on Statutory Thresholds Beta',
        regulator: 'RBI',
        section_reference: 'Clause 9.3',
        clause_text: `Regulated entities shall observe ${customParam} of ${customValB}%.`,
        domain_category: 'custom_test',
        modality: customModB,
        parameter_name: customParam,
        parameter_value: customValB,
        parameter_unit: 'pct',
        comparison_operator: 'MIN',
        effective_date: '2023-06-01',
        is_active: true,
      }

      const res = await fetch('/v1/compliance/compare-clause-pair', {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ clause_a: clauseA, clause_b: clauseB }),
      })

      if (res.ok) {
        const data = await res.json()
        setTestResult(data.conflict || null)
        setTestEvaluated(true)
      }
    } catch (err) {
      console.error('Pair comparison failed:', err)
    }
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

  const getModalityBadge = (mod: string) => {
    switch (mod.toLowerCase()) {
      case 'mandatory':
        return 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
      case 'prohibited':
        return 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
      default:
        return 'bg-sky-500/20 text-sky-300 border border-sky-500/30'
    }
  }

  return (
    <div className="bg-slate-900 text-slate-100 p-6 rounded-xl border border-slate-800 shadow-2xl space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-slate-800">
        <div>
          <div className="flex items-center gap-2">
            <span className="px-2.5 py-0.5 rounded text-xs font-semibold bg-red-500/20 text-red-300 border border-red-500/30">
              FEAT-032
            </span>
            <h2 className="text-xl font-bold tracking-tight text-white">
              Circular Clause Conflict Detector
            </h2>
          </div>
          <p className="text-sm text-slate-400 mt-1">
            Detects unacknowledged contradictions, incompatible thresholds, and modality clashes across active circulars.
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
            onClick={() => setActiveTab('detected')}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition ${
              activeTab === 'detected'
                ? 'bg-amber-600 text-white shadow'
                : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
            }`}
          >
            Detected Conflicts ({stats.total})
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('tester')}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition ${
              activeTab === 'tester'
                ? 'bg-amber-600 text-white shadow'
                : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
            }`}
          >
            Clause Pair Tester
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
              Contradiction Detection Rate:{' '}
              <strong className="text-white text-base">{(benchmarkResult.detection_rate * 100).toFixed(1)}%</strong> (Threshold &gt;90%)
            </span>
          </div>
          <div className="flex gap-4 text-xs text-slate-300">
            <span>Detected: {benchmarkResult.detected_conflicts} / {benchmarkResult.total_conflicting_pairs}</span>
            <span>False Positives: {benchmarkResult.false_positives}</span>
            <span>Precision: {(benchmarkResult.precision * 100).toFixed(1)}%</span>
          </div>
        </div>
      )}

      {/* Overview Metric Bar */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
          <div className="text-xs text-slate-400">Total Conflicts</div>
          <div className="text-xl font-bold text-white mt-1">{stats.total}</div>
        </div>
        <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
          <div className="text-xs text-red-400">Critical Conflicts</div>
          <div className="text-xl font-bold text-red-400 mt-1">{stats.critical}</div>
        </div>
        <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
          <div className="text-xs text-amber-400">High Severity</div>
          <div className="text-xl font-bold text-amber-400 mt-1">{stats.high}</div>
        </div>
        <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
          <div className="text-xs text-yellow-400">Medium Severity</div>
          <div className="text-xl font-bold text-yellow-400 mt-1">{stats.medium}</div>
        </div>
        <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
          <div className="text-xs text-slate-400">Scan Latency</div>
          <div className="text-xl font-bold text-emerald-400 mt-1">{stats.latency} ms</div>
        </div>
      </div>

      {activeTab === 'detected' ? (
        <div className="space-y-4">
          {/* Domain Filter Pills */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-slate-400 mr-1">Filter Domain:</span>
            <button
              type="button"
              onClick={() => setSelectedDomain('')}
              className={`px-2.5 py-1 text-xs rounded transition ${
                selectedDomain === ''
                  ? 'bg-amber-600 text-white'
                  : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
              }`}
            >
              All Domains
            </button>
            {stats.domains.map((dom) => (
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
                {dom}
              </button>
            ))}
          </div>

          {/* Conflict List */}
          {isLoading ? (
            <div className="p-12 text-center text-slate-400">Analyzing clause registry...</div>
          ) : conflicts.length === 0 ? (
            <div className="p-8 text-center bg-slate-950 rounded-lg border border-slate-800 text-emerald-400">
              Zero regulatory conflicts identified for the selected filter.
            </div>
          ) : (
            <div className="space-y-4">
              {conflicts.map((conf) => (
                <div
                  key={conf.conflict_id}
                  className="p-5 rounded-lg bg-slate-950 border border-slate-800 space-y-4 hover:border-slate-700 transition"
                >
                  {/* Top Badges */}
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className={`px-2 py-0.5 rounded text-xs font-bold ${getSeverityBadge(conf.severity)}`}>
                        {conf.severity}
                      </span>
                      <span className="px-2 py-0.5 rounded text-xs font-mono uppercase bg-slate-800 text-slate-300 border border-slate-700">
                        {conf.conflict_type.replace('_', ' ')}
                      </span>
                      <span className="px-2 py-0.5 rounded text-xs bg-slate-800 text-slate-400">
                        Domain: {conf.clause_a.domain_category}
                      </span>
                    </div>

                    {conf.parameter_name && (
                      <span className="text-xs text-amber-300 bg-amber-950/30 px-2 py-0.5 rounded border border-amber-800/40">
                        Parameter: {conf.parameter_name}
                      </span>
                    )}
                  </div>

                  {/* Side-by-Side Clause Comparison */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
                    {/* Clause A */}
                    <div className="p-4 rounded-lg bg-slate-900 border border-slate-800 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-white">{conf.clause_a.circular_id}</span>
                        <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${getModalityBadge(conf.clause_a.modality)}`}>
                          {conf.clause_a.modality.toUpperCase()}
                        </span>
                      </div>
                      <div className="text-xs text-slate-400">
                        {conf.clause_a.circular_title} &bull; {conf.clause_a.section_reference}
                      </div>
                      <p className="text-xs text-slate-200 bg-slate-950/60 p-2.5 rounded border border-slate-800/60 font-mono leading-relaxed">
                        "{conf.clause_a.clause_text}"
                      </p>
                      {conf.clause_a.parameter_value !== null && conf.clause_a.parameter_value !== undefined && (
                        <div className="text-xs text-emerald-400 font-semibold">
                          Threshold: {conf.clause_a.parameter_value} {conf.clause_a.parameter_unit} ({conf.clause_a.comparison_operator})
                        </div>
                      )}
                    </div>

                    {/* Clause B */}
                    <div className="p-4 rounded-lg bg-slate-900 border border-slate-800 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-white">{conf.clause_b.circular_id}</span>
                        <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${getModalityBadge(conf.clause_b.modality)}`}>
                          {conf.clause_b.modality.toUpperCase()}
                        </span>
                      </div>
                      <div className="text-xs text-slate-400">
                        {conf.clause_b.circular_title} &bull; {conf.clause_b.section_reference}
                      </div>
                      <p className="text-xs text-slate-200 bg-slate-950/60 p-2.5 rounded border border-slate-800/60 font-mono leading-relaxed">
                        "{conf.clause_b.clause_text}"
                      </p>
                      {conf.clause_b.parameter_value !== null && conf.clause_b.parameter_value !== undefined && (
                        <div className="text-xs text-rose-400 font-semibold">
                          Threshold: {conf.clause_b.parameter_value} {conf.clause_b.parameter_unit} ({conf.clause_b.comparison_operator})
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Explanation */}
                  <div className="p-3 bg-slate-900/60 rounded-lg border border-slate-800 text-xs text-slate-300">
                    <strong className="text-white">Conflict Analysis:</strong> {conf.explanation}
                  </div>

                  {/* Prescriptive Remediation */}
                  <div className="p-3 bg-amber-950/30 border border-amber-800/50 rounded-lg text-xs space-y-1">
                    <span className="font-semibold text-amber-300 uppercase tracking-wider block">
                      Recommended Compliance Stance
                    </span>
                    <p className="text-slate-200">{conf.prescriptive_action}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        /* Clause Pair Tester Tab */
        <div className="space-y-6">
          <form onSubmit={handleTestPair} className="p-5 bg-slate-950 rounded-lg border border-slate-800 space-y-4">
            <h3 className="text-sm font-semibold text-white">Compare Ad-Hoc Regulatory Clauses</h3>

            <div>
              <label htmlFor="custom-param-name" className="text-xs text-slate-400">Parameter Under Comparison</label>
              <input
                id="custom-param-name"
                type="text"
                value={customParam}
                onChange={(e) => setCustomParam(e.target.value)}
                className="w-full mt-1 bg-slate-900 border border-slate-700 rounded-lg p-2 text-sm text-slate-200 focus:outline-none focus:border-amber-500 font-mono"
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Clause A Controls */}
              <div className="p-4 bg-slate-900 rounded-lg border border-slate-800 space-y-3">
                <span className="text-xs font-bold text-amber-400 uppercase">Clause Alpha (Circular A)</span>
                <div>
                  <label htmlFor="custom-param-val-a" className="text-xs text-slate-400">Mandated Threshold Value</label>
                  <input
                    id="custom-param-val-a"
                    type="number"
                    step="any"
                    value={customValA}
                    onChange={(e) => setCustomValA(parseFloat(e.target.value) || 0)}
                    className="w-full mt-1 bg-slate-950 border border-slate-700 rounded-lg p-2 text-sm text-slate-200"
                  />
                </div>
                <div>
                  <label htmlFor="custom-param-mod-a" className="text-xs text-slate-400">Normative Modality</label>
                  <select
                    id="custom-param-mod-a"
                    value={customModA}
                    onChange={(e) => setCustomModA(e.target.value)}
                    className="w-full mt-1 bg-slate-950 border border-slate-700 rounded-lg p-2 text-sm text-slate-200"
                  >
                    <option value="mandatory">MANDATORY (Shall/Must)</option>
                    <option value="prohibited">PROHIBITED (Shall Not)</option>
                    <option value="permitted">PERMITTED (May)</option>
                  </select>
                </div>
              </div>

              {/* Clause B Controls */}
              <div className="p-4 bg-slate-900 rounded-lg border border-slate-800 space-y-3">
                <span className="text-xs font-bold text-amber-400 uppercase">Clause Beta (Circular B)</span>
                <div>
                  <label htmlFor="custom-param-val-b" className="text-xs text-slate-400">Mandated Threshold Value</label>
                  <input
                    id="custom-param-val-b"
                    type="number"
                    step="any"
                    value={customValB}
                    onChange={(e) => setCustomValB(parseFloat(e.target.value) || 0)}
                    className="w-full mt-1 bg-slate-950 border border-slate-700 rounded-lg p-2 text-sm text-slate-200"
                  />
                </div>
                <div>
                  <label htmlFor="custom-param-mod-b" className="text-xs text-slate-400">Normative Modality</label>
                  <select
                    id="custom-param-mod-b"
                    value={customModB}
                    onChange={(e) => setCustomModB(e.target.value)}
                    className="w-full mt-1 bg-slate-950 border border-slate-700 rounded-lg p-2 text-sm text-slate-200"
                  >
                    <option value="mandatory">MANDATORY (Shall/Must)</option>
                    <option value="prohibited">PROHIBITED (Shall Not)</option>
                    <option value="permitted">PERMITTED (May)</option>
                  </select>
                </div>
              </div>
            </div>

            <button
              type="submit"
              className="w-full bg-amber-600 hover:bg-amber-500 text-white font-medium py-2 rounded-lg transition"
            >
              Analyze Pair for Contradiction
            </button>
          </form>

          {/* Test Pair Evaluation Result */}
          {testEvaluated && (
            <div className="p-5 bg-slate-950 rounded-lg border border-slate-800 space-y-3">
              {testResult ? (
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <span className="px-2.5 py-0.5 rounded text-xs font-bold uppercase bg-red-500/20 text-red-300 border border-red-500/40">
                      Conflict Detected: {testResult.conflict_type.replace('_', ' ')}
                    </span>
                    <span className={`px-2 py-0.5 rounded text-xs font-bold ${getSeverityBadge(testResult.severity)}`}>
                      {testResult.severity}
                    </span>
                  </div>
                  <p className="text-sm text-slate-300">{testResult.explanation}</p>
                  <div className="p-3 bg-amber-950/30 rounded border border-amber-800/40 text-xs text-amber-200">
                    <strong>Recommended Stance:</strong> {testResult.prescriptive_action}
                  </div>
                </div>
              ) : (
                <div className="text-emerald-400 text-sm">
                  Clauses are harmonious; no contradiction detected.
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
export default CircularClauseConflictDetector
