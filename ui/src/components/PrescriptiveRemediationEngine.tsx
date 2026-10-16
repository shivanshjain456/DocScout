// DocScout Prescriptive Remediation Engine (FEAT-034)
// Maps compliance antipatterns and deprecated practices to sanctioned, compliant
// alternative practices ('Instead-Of') and actionable execution checklists.

import React, { useState, useEffect } from 'react'

export interface PracticeRecommendation {
  name: string
  term_id: string
  definition: string
  value_justification: string
  tier: number
  domain: string
  gate_criteria?: string | null
  implementation_steps: string[]
  standard_reference?: string | null
}

export interface RemediationPlan {
  flaw_id: string
  flaw_type: string
  identified_flaw: string
  consequence_or_reason: string
  severity: string
  recommended_practices: PracticeRecommendation[]
  guidance?: string | null
  lookup_latency_ms: number
}

export interface BatchRemediationResponse {
  total_findings: number
  remediated_findings: number
  plans: RemediationPlan[]
  unique_recommended_practices: string[]
  latency_ms: number
}

export interface RemediationCatalogResponse {
  total_plans: number
  total_practices_mapped: number
  plans: RemediationPlan[]
}

const SAMPLE_PRESETS: { label: string; flawId: string; description: string }[] = [
  {
    label: 'Line Coverage Target (Antipattern)',
    flawId: 'ap-line-coverage',
    description: 'Release gates requiring 90% statement coverage rather than verification adequacy.',
  },
  {
    label: 'Mock Everything (Antipattern)',
    flawId: 'ap-mock-everything',
    description: 'Mocking all external dependencies so tests verify assumptions rather than behavior.',
  },
  {
    label: 'Direct-Only Prompt Injection (Antipattern)',
    flawId: 'ap-prompt-injection-direct-only',
    description: 'Testing only front-end direct injections while omitting indirect retrieval attacks.',
  },
  {
    label: 'DREAD Risk Scoring (Deprecation)',
    flawId: 'dep-dread',
    description: 'Subjective numerical vulnerability rubric with high inter-reviewer variance.',
  },
  {
    label: 'Hystrix Circuit Breakers (Deprecation)',
    flawId: 'dep-hystrix',
    description: 'Deprecated Netflix library lacking proactive backpressure and bulkhead verification.',
  },
  {
    label: 'Annual Point-in-Time Pentests (Deprecation)',
    flawId: 'dep-annual-point-in-time-penetr',
    description: 'Point-in-time annual tests failing continuous SOC 2 and DORA assurance.',
  },
]

export const PrescriptiveRemediationEngine: React.FC = () => {
  const [selectedFlawId, setSelectedFlawId] = useState<string>(SAMPLE_PRESETS[0].flawId)
  const [customFlawId, setCustomFlawId] = useState<string>('')
  const [includeSteps, setIncludeSteps] = useState<boolean>(true)
  const [currentPlan, setCurrentPlan] = useState<RemediationPlan | null>(null)
  const [catalog, setCatalog] = useState<RemediationPlan[]>([])
  const [batchResult, setBatchResult] = useState<BatchRemediationResponse | null>(null)
  const [batchInput, setBatchInput] = useState<string>(
    'ap-line-coverage\nap-mock-everything\nap-error-budget-ignored\ndep-dread'
  )
  const [isLoading, setIsLoading] = useState<boolean>(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'planner' | 'catalog' | 'batch'>('planner')
  const [catalogFilterType, setCatalogFilterType] = useState<string>('')
  const [catalogFilterTier, setCatalogFilterTier] = useState<string>('')
  const [searchQuery, setSearchQuery] = useState<string>('')
  const [copiedKey, setCopiedKey] = useState<string | null>(null)

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
    fetchCatalog()
    fetchPlan(selectedFlawId)
  }, [])

  const fetchCatalog = async () => {
    try {
      const res = await fetch('/v1/compliance/remediation/catalog', { credentials: 'include', headers: getHeaders() })
      if (res.ok) {
        const data: RemediationCatalogResponse = await res.json()
        setCatalog(data.plans)
      }
    } catch {
      // Catalog fallback handled gracefully
    }
  }

  const fetchPlan = async (flawIdToFetch: string) => {
    setIsLoading(true)
    setErrorMsg(null)
    try {
      const res = await fetch('/v1/compliance/remediation/plan', {
        method: 'POST',
        credentials: 'include',
        headers: getHeaders(),
        body: JSON.stringify({
          flaw_id: flawIdToFetch,
          include_implementation_steps: includeSteps,
        }),
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Failed to generate plan' }))
        throw new Error(err.detail || 'Plan lookup failed')
      }

      const plan: RemediationPlan = await res.json()
      setCurrentPlan(plan)
    } catch (err: any) {
      setErrorMsg(err.message || 'Error communicating with remediation service')
    } finally {
      setIsLoading(false)
    }
  }

  const handleExecuteBatch = async () => {
    setIsLoading(true)
    setErrorMsg(null)
    try {
      const ids = batchInput
        .split('\n')
        .map((s) => s.trim())
        .filter((s) => s.length > 0)

      if (ids.length === 0) {
        throw new Error('Please provide at least one flaw ID.')
      }

      const res = await fetch('/v1/compliance/remediation/batch', {
        method: 'POST',
        credentials: 'include',
        headers: getHeaders(),
        body: JSON.stringify({
          flaw_ids: ids,
          include_implementation_steps: includeSteps,
        }),
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Batch remediation failed' }))
        throw new Error(err.detail || 'Batch remediation failed')
      }

      const data: BatchRemediationResponse = await res.json()
      setBatchResult(data)
    } catch (err: any) {
      setErrorMsg(err.message || 'Batch execution failed')
    } finally {
      setIsLoading(false)
    }
  }

  const copyStepsToClipboard = (rec: PracticeRecommendation) => {
    const text = `Prescriptive Checklist for: ${rec.name}\n` +
      `Tier: Tier ${rec.tier}\n` +
      `Gate: ${rec.gate_criteria || 'None'}\n\n` +
      rec.implementation_steps.map((st, i) => `${i + 1}. [ ] ${st}`).join('\n')

    navigator.clipboard.writeText(text)
    setCopiedKey(rec.term_id)
    setTimeout(() => setCopiedKey(null), 2500)
  }

  const filteredCatalog = catalog.filter((p) => {
    if (catalogFilterType && p.flaw_type !== catalogFilterType) return false
    if (catalogFilterTier) {
      const targetTier = parseInt(catalogFilterTier, 10)
      if (!p.recommended_practices.some((r) => r.tier === targetTier)) return false
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase()
      const matchFlaw = p.identified_flaw.toLowerCase().includes(q) || p.flaw_id.toLowerCase().includes(q)
      const matchRec = p.recommended_practices.some(
        (r) => r.name.toLowerCase().includes(q) || r.definition.toLowerCase().includes(q)
      )
      if (!matchFlaw && !matchRec) return false
    }
    return true
  })

  return (
    <div className="docscout-remediation-engine p-6 bg-slate-950 text-slate-100 rounded-xl border border-slate-800 font-sans">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 pb-6 border-b border-slate-800">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-xl font-bold tracking-tight text-white">
              Prescriptive Remediation Engine
            </h2>
            <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
              FEAT-034
            </span>
            <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-blue-500/20 text-blue-300 border border-blue-500/30">
              Instead-Of Mapping
            </span>
          </div>
          <p className="text-sm text-slate-400 mt-1">
            Prescriptive alternative practices anchored directly in formal taxonomy standards and gating rules.
          </p>
        </div>

        {/* Tab Buttons */}
        <div className="flex bg-slate-900 p-1 rounded-lg border border-slate-800 text-sm">
          <button
            onClick={() => setActiveTab('planner')}
            className={`px-3 py-1.5 rounded-md font-medium transition-all ${
              activeTab === 'planner'
                ? 'bg-emerald-600 text-white shadow-sm'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            Prescriptive Planner
          </button>
          <button
            onClick={() => setActiveTab('catalog')}
            className={`px-3 py-1.5 rounded-md font-medium transition-all ${
              activeTab === 'catalog'
                ? 'bg-emerald-600 text-white shadow-sm'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            Catalog ({catalog.length})
          </button>
          <button
            onClick={() => setActiveTab('batch')}
            className={`px-3 py-1.5 rounded-md font-medium transition-all ${
              activeTab === 'batch'
                ? 'bg-emerald-600 text-white shadow-sm'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            Batch Audit Resolver
          </button>
        </div>
      </div>

      {errorMsg && (
        <div className="mt-4 p-3 bg-red-950/60 border border-red-800 text-red-200 text-sm rounded-lg flex items-center justify-between">
          <span>{errorMsg}</span>
          <button onClick={() => setErrorMsg(null)} className="text-red-400 hover:text-white">
            Dismiss
          </button>
        </div>
      )}

      {/* Tab 1: Prescriptive Planner */}
      {activeTab === 'planner' && (
        <div className="mt-6 space-y-6">
          {/* Controls */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 p-4 bg-slate-900/60 border border-slate-800/80 rounded-lg">
            <div>
              <label className="block text-xs font-semibold text-slate-400 mb-1">
                Preset Compliance Flaws
              </label>
              <select
                value={selectedFlawId}
                onChange={(e) => {
                  setSelectedFlawId(e.target.value)
                  fetchPlan(e.target.value)
                }}
                className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-emerald-500"
              >
                {SAMPLE_PRESETS.map((p) => (
                  <option key={p.flawId} value={p.flawId}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-400 mb-1">
                Or Custom Flaw ID / Subject
              </label>
              <div className="flex gap-2">
                <input
                  type="text"
                  placeholder="e.g. ap-blind-test-retries or Hystrix"
                  value={customFlawId}
                  onChange={(e) => setCustomFlawId(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-emerald-500"
                />
                <button
                  onClick={() => {
                    if (customFlawId.trim()) {
                      setSelectedFlawId(customFlawId.trim())
                      fetchPlan(customFlawId.trim())
                    }
                  }}
                  disabled={isLoading || !customFlawId.trim()}
                  className="px-3 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded text-sm font-medium transition"
                >
                  Lookup
                </button>
              </div>
            </div>

            <div className="flex flex-col justify-end">
              <label className="flex items-center gap-2 cursor-pointer text-sm text-slate-300 select-none pb-2">
                <input
                  type="checkbox"
                  checked={includeSteps}
                  onChange={(e) => {
                    setIncludeSteps(e.target.checked)
                    if (currentPlan) fetchPlan(currentPlan.flaw_id)
                  }}
                  className="rounded border-slate-700 text-emerald-600 focus:ring-emerald-500 bg-slate-900 h-4 w-4"
                />
                Generate Actionable Implementation Steps
              </label>
            </div>
          </div>

          {/* Plan Display */}
          {isLoading ? (
            <div className="p-12 text-center text-slate-400">
              <div className="animate-spin inline-block w-8 h-8 border-4 border-emerald-500 border-t-transparent rounded-full mb-3" />
              <p>Formulating prescriptive remediation plan...</p>
            </div>
          ) : currentPlan ? (
            <div className="space-y-6">
              {/* Flaw Header Card */}
              <div className="p-5 bg-slate-900/90 border border-slate-800 rounded-xl">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <span className="text-xs uppercase font-bold tracking-wider px-2 py-0.5 rounded bg-slate-800 text-slate-300">
                      Flaw ID: {currentPlan.flaw_id}
                    </span>
                    <span
                      className={`ml-2 text-xs uppercase font-bold tracking-wider px-2 py-0.5 rounded ${
                        currentPlan.severity === 'CRITICAL'
                          ? 'bg-red-500/20 text-red-300 border border-red-500/30'
                          : 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                      }`}
                    >
                      {currentPlan.severity} Severity
                    </span>
                    <span className="ml-2 text-xs font-medium text-slate-400">
                      Type: {currentPlan.flaw_type}
                    </span>
                  </div>
                  <span className="text-xs font-mono text-slate-400">
                    Lookup Latency: {currentPlan.lookup_latency_ms.toFixed(3)} ms
                  </span>
                </div>

                <h3 className="text-lg font-bold text-white mt-3">{currentPlan.identified_flaw}</h3>
                <p className="text-sm text-slate-300 mt-2 bg-red-950/30 border border-red-900/40 p-3 rounded">
                  <span className="font-semibold text-red-300">Consequence & Failure Mode: </span>
                  {currentPlan.consequence_or_reason}
                </p>

                {currentPlan.guidance && (
                  <p className="text-xs text-slate-400 mt-2 italic">
                    <span className="font-semibold text-slate-300">Policy Guidance: </span>
                    {currentPlan.guidance}
                  </p>
                )}
              </div>

              {/* Sanctioned Alternatives Grid */}
              <div>
                <h4 className="text-sm font-bold uppercase tracking-wider text-emerald-400 mb-3 flex items-center gap-2">
                  <span>Sanctioned Compliant Alternatives ("Instead-Of")</span>
                  <span className="px-2 py-0.2 rounded-full text-xs bg-emerald-950 text-emerald-300 border border-emerald-800">
                    {currentPlan.recommended_practices.length} Practices Available
                  </span>
                </h4>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {currentPlan.recommended_practices.map((rec) => (
                    <div
                      key={rec.term_id}
                      className="p-4 bg-slate-900 border border-slate-800 hover:border-emerald-500/60 transition-all rounded-xl flex flex-col justify-between"
                    >
                      <div>
                        <div className="flex items-center justify-between gap-2 mb-2">
                          <span className="text-xs font-semibold px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">
                            Tier {rec.tier}
                          </span>
                          <span className="text-xs font-mono text-slate-400">{rec.domain}</span>
                        </div>

                        <h5 className="font-bold text-white text-base leading-snug">{rec.name}</h5>
                        <p className="text-xs text-slate-300 mt-2 leading-relaxed">
                          {rec.definition}
                        </p>

                        <div className="mt-3 p-2.5 bg-slate-950/70 border border-slate-800/80 rounded text-xs">
                          <span className="font-semibold text-emerald-400">Value Justification: </span>
                          <span className="text-slate-300">{rec.value_justification}</span>
                        </div>

                        {rec.gate_criteria && (
                          <div className="mt-2 p-2 bg-blue-950/40 border border-blue-900/40 rounded text-xs text-blue-200">
                            <span className="font-semibold text-blue-300">Release Gate: </span>
                            {rec.gate_criteria}
                          </div>
                        )}

                        {rec.implementation_steps && rec.implementation_steps.length > 0 && (
                          <div className="mt-3">
                            <span className="text-xs font-semibold text-slate-400">
                              Actionable Steps:
                            </span>
                            <ul className="mt-1 space-y-1 text-xs text-slate-300 list-disc list-inside">
                              {rec.implementation_steps.map((step, idx) => (
                                <li key={idx} className="leading-tight">
                                  {step}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>

                      <div className="mt-4 pt-3 border-t border-slate-800 flex justify-end">
                        <button
                          onClick={() => copyStepsToClipboard(rec)}
                          className="px-2.5 py-1 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 rounded transition flex items-center gap-1.5"
                        >
                          {copiedKey === rec.term_id ? (
                            <span className="text-emerald-400">Checklist Copied!</span>
                          ) : (
                            <span>Copy Checklist</span>
                          )}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : null}
        </div>
      )}

      {/* Tab 2: Remediation Catalog */}
      {activeTab === 'catalog' && (
        <div className="mt-6 space-y-4">
          <div className="flex flex-wrap items-center gap-3 p-3 bg-slate-900/80 rounded-lg border border-slate-800">
            <input
              type="text"
              placeholder="Search flaw title, practice name, or keyword..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="flex-1 bg-slate-950 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-emerald-500"
            />
            <select
              value={catalogFilterType}
              onChange={(e) => setCatalogFilterType(e.target.value)}
              className="bg-slate-950 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-200"
            >
              <option value="">All Flaw Types</option>
              <option value="antipattern">Antipatterns (30)</option>
              <option value="deprecation">Deprecations (8)</option>
            </select>
            <select
              value={catalogFilterTier}
              onChange={(e) => setCatalogFilterTier(e.target.value)}
              className="bg-slate-950 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-200"
            >
              <option value="">All Tiers</option>
              <option value="1">Tier 1 (Core)</option>
              <option value="2">Tier 2</option>
              <option value="3">Tier 3</option>
            </select>
            <span className="text-xs text-slate-400">
              Showing {filteredCatalog.length} of {catalog.length} Plans
            </span>
          </div>

          <div className="space-y-3">
            {filteredCatalog.map((p) => (
              <div
                key={p.flaw_id}
                className="p-4 bg-slate-900 border border-slate-800 rounded-lg hover:border-slate-700 transition"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs px-2 py-0.5 bg-slate-800 rounded text-slate-300">
                      {p.flaw_id}
                    </span>
                    <span className="text-xs font-semibold uppercase text-emerald-400">
                      {p.flaw_type}
                    </span>
                    <span
                      className={`text-xs px-2 py-0.5 rounded ${
                        p.severity === 'CRITICAL'
                          ? 'bg-red-500/20 text-red-300'
                          : 'bg-amber-500/20 text-amber-300'
                      }`}
                    >
                      {p.severity}
                    </span>
                  </div>
                  <button
                    onClick={() => {
                      setSelectedFlawId(p.flaw_id)
                      setCurrentPlan(p)
                      setActiveTab('planner')
                    }}
                    className="text-xs font-medium text-emerald-400 hover:text-emerald-300 underline"
                  >
                    View Full Plan &rarr;
                  </button>
                </div>

                <h4 className="font-bold text-white text-sm mt-2">{p.identified_flaw}</h4>
                <p className="text-xs text-slate-400 mt-1">{p.consequence_or_reason}</p>

                <div className="mt-3 flex flex-wrap gap-2">
                  {p.recommended_practices.map((rec) => (
                    <span
                      key={rec.term_id}
                      className="px-2 py-1 bg-slate-950 border border-slate-800 rounded text-xs text-slate-300 flex items-center gap-1.5"
                    >
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                      {rec.name}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tab 3: Batch Audit Resolver */}
      {activeTab === 'batch' && (
        <div className="mt-6 space-y-6">
          <div className="p-4 bg-slate-900 border border-slate-800 rounded-lg space-y-3">
            <label className="block text-xs font-bold text-slate-300 uppercase tracking-wide">
              Batch Flaw Identifiers (one per line)
            </label>
            <textarea
              rows={4}
              value={batchInput}
              onChange={(e) => setBatchInput(e.target.value)}
              className="w-full font-mono text-xs bg-slate-950 border border-slate-700 rounded p-3 text-slate-200 focus:outline-none focus:border-emerald-500"
              placeholder="e.g. ap-line-coverage\nap-chaos-no-hypothesis\ndep-dread"
            />
            <button
              onClick={handleExecuteBatch}
              disabled={isLoading || !batchInput.trim()}
              className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded text-sm font-semibold transition"
            >
              {isLoading ? 'Resolving Batch Plans...' : 'Resolve All Flaws'}
            </button>
          </div>

          {batchResult && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <div className="p-3 bg-slate-900 border border-slate-800 rounded-lg text-center">
                  <div className="text-xl font-bold text-white">{batchResult.total_findings}</div>
                  <div className="text-xs text-slate-400">Total Findings Submitted</div>
                </div>
                <div className="p-3 bg-slate-900 border border-slate-800 rounded-lg text-center">
                  <div className="text-xl font-bold text-emerald-400">
                    {batchResult.remediated_findings}
                  </div>
                  <div className="text-xs text-slate-400">Remediations Formulated</div>
                </div>
                <div className="p-3 bg-slate-900 border border-slate-800 rounded-lg text-center">
                  <div className="text-xl font-bold text-blue-400">
                    {batchResult.unique_recommended_practices.length}
                  </div>
                  <div className="text-xs text-slate-400">Unique Sanctioned Practices</div>
                </div>
              </div>

              <div className="p-4 bg-slate-900 border border-slate-800 rounded-lg">
                <h4 className="text-xs font-bold text-slate-300 uppercase tracking-wide mb-2">
                  Consolidated Target Practices:
                </h4>
                <div className="flex flex-wrap gap-2">
                  {batchResult.unique_recommended_practices.map((prac, i) => (
                    <span
                      key={i}
                      className="px-2.5 py-1 bg-emerald-950/60 border border-emerald-800/80 rounded-full text-xs font-medium text-emerald-300"
                    >
                      {prac}
                    </span>
                  ))}
                </div>
              </div>

              <div className="space-y-3">
                {batchResult.plans.map((p) => (
                  <div
                    key={p.flaw_id}
                    className="p-3 bg-slate-900/60 border border-slate-800 rounded-lg"
                  >
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-mono text-slate-400">{p.flaw_id}</span>
                      <span className="font-semibold text-emerald-400">
                        {p.recommended_practices.length} alternatives mapped
                      </span>
                    </div>
                    <div className="text-sm font-bold text-white mt-1">{p.identified_flaw}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default PrescriptiveRemediationEngine
