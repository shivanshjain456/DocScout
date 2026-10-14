import React, { useState } from 'react'

export type ModelType =
  | 'algorithmic_trading'
  | 'credit_scoring'
  | 'llm_agent'
  | 'fraud_detection'
  | 'general_ai'

export type ConformityStatus = 'CONFORMANT' | 'CONDITIONAL' | 'NON_CONFORMANT'

export interface FailedControl {
  control_id: string
  title: string
  regulation_ref: string
  remedy: string
}

export interface AlgoAssessmentResponseData {
  system_name: string
  model_type: string
  conformity_score: number
  status: ConformityStatus
  passed_controls: string[]
  failed_controls: FailedControl[]
  negative_flags: string[]
  audit_certificate_id: string
  evaluated_at: string
  summary: string
}

export interface AlgoImpactViewProps {
  apiBaseUrl?: string
  apiKey?: string
  className?: string
  onAssessmentComplete?: (result: AlgoAssessmentResponseData) => void
}

const PRESET_SPECS: Record<ModelType, { name: string; spec: string }> = {
  algorithmic_trading: {
    name: 'AlphaPulse HFT Market Maker v4.2',
    spec: `System Architecture & Algorithmic Risk Specification:
AlphaPulse is a low-latency market-making algorithm for NSE/BSE cash and equity derivative segments.
1. Operational Resilience: Equipped with an automated hardware kill switch and manual operator emergency halt button. Upon market disconnect or latency threshold exceedance (>15ms), the kill switch instantaneously cancels all outstanding limit orders and freezes new order generation.
2. Model Validation: Pre-deployment backtesting was performed across 5 years of historical tick-data. Rigorous walk-forward validation and out-of-sample stress testing simulated Flash Crash events with -12% index drops.
3. Feature Explainability: Implements TreeSHAP explainability pipelines providing local feature importance vectors for bid-ask spread adjustments.
4. Bias & Fairness: Demographic fairness metrics audited to confirm non-discriminatory quote placement.
5. Deterministic Audit Trail: WORM storage maintains an immutable audit trail recording every order state, timestamped with microsecond-level accuracy, retained for a 7-year retention period per SEBI norms.
6. Post-Deployment Telemetry: Real-time population stability index (PSI) and concept drift monitors evaluate distribution shifts every 60 seconds.
7. Market Integrity: Pre-trade risk controls enforce strict order-to-trade ratio (OTR) limiters and fat-finger price bands restricting order sizes to 1,000 lots.
8. External Assurance: Annual system audit executed by CERT-In empanelled independent system auditor.`,
  },
  credit_scoring: {
    name: 'Retail Credit Underwriting AI v2.1',
    spec: `Retail Credit Risk Model Documentation:
Automated credit risk assessment and underwriting engine for personal retail lending.
1. Feature Attribution: Incorporates TreeSHAP and LIME surrogate models generating local feature importance rationales for every adverse underwriting decision.
2. Fairness & Bias Auditing: Annual algorithmic bias evaluation measures disparate impact ratio, demographic parity, and equalized odds across protected applicant categories.
3. Model Validation: Out-of-sample stress testing on distressed default loan cohorts alongside 5-fold cross-validation.
4. Continuous Drift: Population Stability Index (PSI) monitored weekly; alerts trigger retraining when PSI exceeds 0.25.
5. Audit Logging: Full deterministic audit logging of applicant feature snapshots and decision scores with 7-year storage.
6. Governance: Underwriting policies independently certified for compliance with RBI fair lending principles.`,
  },
  llm_agent: {
    name: 'Advisory Financial Copilot Agent',
    spec: `Autonomous Wealth Advisory LLM Agent Specification:
1. Operational Guardrails: Integrated circuit breaker and emergency cutoff switch halting generation if hallucination score exceeds 0.3.
2. Decision Attribution: Feature importance and citation provenance provide explainability for financial recommendations.
3. Bias Mitigation: Regular demographic fairness audits evaluate parity of financial advisory outcomes.
4. Audit Logging: Microsecond timestamps log all prompts, completions, and retrieved statutory contexts into immutable audit trail storage for 7 years.
5. Telemetry: Continuous monitoring tracks concept drift and distribution shifts in user query embeddings.`,
  },
  fraud_detection: {
    name: 'Sentinel Real-Time Payment Fraud Engine',
    spec: `High-Throughput Fraud Detection Architecture:
1. Risk Throttle: Hardware circuit breaker halts automated block actions if false-positive anomaly rate spikes over 5%.
2. Model Validation: Backtesting over 100M historical UPI payment events with out-of-sample stress testing under festival surge traffic.
3. Explainability: Local SHAP values accompany every blocked payment event.
4. Telemetry: Real-time concept drift monitoring alerts operators on new merchant category anomalies.
5. Audit Records: Immutable logging of fraud scores with 7-year retention.`,
  },
  general_ai: {
    name: 'Enterprise Decision Support Model',
    spec: `Generic Enterprise Decision Model Card:
1. Circuit Breaker: Emergency stop and manual override switch configured.
2. Model Governance: Cross-validation and backtesting across historical datasets.
3. Interpretability: Decision attribution and feature importance explanations generated for each inference.
4. Provenance: 7-year retention of model parameter weights and inference logs.
5. Monitoring: Continuous telemetry for data drift and population stability index tracking.`,
  },
}

export const AlgoImpactView: React.FC<AlgoImpactViewProps> = ({
  apiBaseUrl = '',
  apiKey = '',
  className = '',
  onAssessmentComplete,
}) => {
  const [modelType, setModelType] = useState<ModelType>('algorithmic_trading')
  const [systemName, setSystemName] = useState<string>(PRESET_SPECS.algorithmic_trading.name)
  const [systemSpecText, setSystemSpecText] = useState<string>(PRESET_SPECS.algorithmic_trading.spec)
  const [strictKillSwitch, setStrictKillSwitch] = useState<boolean>(true)
  const [loading, setLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AlgoAssessmentResponseData | null>(null)
  const [copiedId, setCopiedId] = useState<string | null>(null)

  const handlePresetSelect = (type: ModelType) => {
    setModelType(type)
    setSystemName(PRESET_SPECS[type].name)
    setSystemSpecText(PRESET_SPECS[type].spec)
    setError(null)
  }

  const handleAssess = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!systemName.trim()) {
      setError('System name is required.')
      return
    }
    if (systemSpecText.trim().length < 100) {
      setError('System specification must be at least 100 characters.')
      return
    }

    setLoading(true)
    setError(null)

    try {
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
      }
      if (apiKey) {
        headers['X-API-Key'] = apiKey
      }

      const payload = {
        system_name: systemName.trim(),
        model_type: modelType,
        system_spec_text: systemSpecText,
        strict_kill_switch_required: strictKillSwitch,
      }

      const res = await fetch(`${apiBaseUrl}/v1/compliance/algo-assessment`, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload),
      })

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}))
        throw new Error(errJson.detail || `Server returned error ${res.status}`)
      }

      const json: AlgoAssessmentResponseData = await res.json()
      setResult(json)
      if (onAssessmentComplete) {
        onAssessmentComplete(json)
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to assess algorithmic system'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  const copyRemedy = (text: string, id: string) => {
    navigator.clipboard.writeText(text)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 2000)
  }

  const getStatusColor = (status: ConformityStatus) => {
    switch (status) {
      case 'CONFORMANT':
        return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
      case 'CONDITIONAL':
        return 'bg-amber-500/10 text-amber-400 border-amber-500/30'
      case 'NON_CONFORMANT':
        return 'bg-rose-500/10 text-rose-400 border-rose-500/30'
    }
  }

  return (
    <div
      data-testid="algo-impact-view"
      className={`bg-slate-900 border border-slate-800 rounded-xl p-6 text-slate-100 ${className}`}
    >
      <div className="flex flex-col md:flex-row md:items-center justify-between pb-6 border-b border-slate-800 gap-4">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <span className="p-1.5 rounded-lg bg-indigo-500/20 text-indigo-400 text-sm">AI/ML</span>
            Algorithmic &amp; AI Impact Assessment Framework
          </h2>
          <p className="text-sm text-slate-400 mt-1">
            Automated statutory conformity evaluation under SEBI Algorithmic Trading Rules &amp; RBI Model Governance.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400">Presets:</span>
          <button
            type="button"
            onClick={() => handlePresetSelect('algorithmic_trading')}
            className={`px-2.5 py-1 text-xs rounded-md border transition-colors ${
              modelType === 'algorithmic_trading'
                ? 'bg-indigo-600 text-white border-indigo-500'
                : 'bg-slate-800 text-slate-300 border-slate-700 hover:bg-slate-700'
            }`}
          >
            HFT Algo
          </button>
          <button
            type="button"
            onClick={() => handlePresetSelect('credit_scoring')}
            className={`px-2.5 py-1 text-xs rounded-md border transition-colors ${
              modelType === 'credit_scoring'
                ? 'bg-indigo-600 text-white border-indigo-500'
                : 'bg-slate-800 text-slate-300 border-slate-700 hover:bg-slate-700'
            }`}
          >
            Credit AI
          </button>
          <button
            type="button"
            onClick={() => handlePresetSelect('llm_agent')}
            className={`px-2.5 py-1 text-xs rounded-md border transition-colors ${
              modelType === 'llm_agent'
                ? 'bg-indigo-600 text-white border-indigo-500'
                : 'bg-slate-800 text-slate-300 border-slate-700 hover:bg-slate-700'
            }`}
          >
            LLM Agent
          </button>
        </div>
      </div>

      <form onSubmit={handleAssess} className="mt-6 space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label htmlFor="system-name" className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1">
              System Identifier / Model Name
            </label>
            <input
              id="system-name"
              data-testid="system-name-input"
              type="text"
              value={systemName}
              onChange={(e) => setSystemName(e.target.value)}
              placeholder="e.g. Volatility Arbitrage Engine v3"
              className="w-full bg-slate-800/80 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              required
            />
          </div>

          <div>
            <label htmlFor="model-type" className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1">
              Regulatory Model Classification
            </label>
            <select
              id="model-type"
              data-testid="model-type-select"
              value={modelType}
              onChange={(e) => setModelType(e.target.value as ModelType)}
              className="w-full bg-slate-800/80 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="algorithmic_trading">Algorithmic Trading (SEBI Order Routing)</option>
              <option value="credit_scoring">Credit Underwriting AI (RBI Master Direction)</option>
              <option value="llm_agent">Autonomous LLM Financial Agent</option>
              <option value="fraud_detection">Real-Time Fraud Detection Model</option>
              <option value="general_ai">General Enterprise AI / ML System</option>
            </select>
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between mb-1">
            <label htmlFor="system-spec" className="block text-xs font-semibold text-slate-300 uppercase tracking-wider">
              System Architecture &amp; Risk Controls Specification
            </label>
            <span className="text-xs text-slate-500">{systemSpecText.length} characters</span>
          </div>
          <textarea
            id="system-spec"
            data-testid="system-spec-textarea"
            rows={7}
            value={systemSpecText}
            onChange={(e) => setSystemSpecText(e.target.value)}
            placeholder="Paste system documentation, kill switch specs, backtesting methodology, explainability models, and audit retention policies..."
            className="w-full bg-slate-800/80 border border-slate-700 rounded-lg p-3 text-sm text-slate-200 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500"
            required
          />
        </div>

        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pt-2">
          <label className="flex items-center gap-2 cursor-pointer text-xs text-slate-300">
            <input
              type="checkbox"
              checked={strictKillSwitch}
              onChange={(e) => setStrictKillSwitch(e.target.checked)}
              className="rounded bg-slate-800 border-slate-700 text-indigo-600 focus:ring-indigo-500 h-4 w-4"
            />
            <span>Strict Kill Switch Enforcement (Cap score &le; 45% if trading kill switch absent)</span>
          </label>

          <button
            type="submit"
            data-testid="audit-submit-btn"
            disabled={loading}
            className="px-6 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-sm transition-colors shadow-lg shadow-indigo-600/20 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {loading ? (
              <>
                <svg className="animate-spin h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                </svg>
                Evaluating Controls...
              </>
            ) : (
              'Run Impact Assessment'
            )}
          </button>
        </div>
      </form>

      {error && (
        <div className="mt-4 p-4 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-8 pt-6 border-t border-slate-800 space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-slate-800/60 border border-slate-700/80 rounded-xl p-4 flex flex-col justify-between">
              <span className="text-xs uppercase tracking-wider font-semibold text-slate-400">Conformity Score</span>
              <div className="my-2 flex items-baseline gap-2">
                <span
                  data-testid="conformity-score"
                  className="text-4xl font-extrabold text-white"
                >
                  {result.conformity_score}%
                </span>
                <span className="text-xs text-slate-400">/ 100</span>
              </div>
              <div className="w-full bg-slate-700 rounded-full h-2">
                <div
                  className={`h-2 rounded-full ${
                    result.conformity_score >= 75
                      ? 'bg-emerald-500'
                      : result.conformity_score >= 50
                      ? 'bg-amber-500'
                      : 'bg-rose-500'
                  }`}
                  style={{ width: `${Math.min(100, Math.max(0, result.conformity_score))}%` }}
                />
              </div>
            </div>

            <div className="bg-slate-800/60 border border-slate-700/80 rounded-xl p-4 flex flex-col justify-between">
              <span className="text-xs uppercase tracking-wider font-semibold text-slate-400">Regulatory Status</span>
              <div className="my-2">
                <span
                  data-testid="status-badge"
                  className={`px-3 py-1 rounded-full text-xs font-bold border ${getStatusColor(result.status)}`}
                >
                  {result.status}
                </span>
              </div>
              <p className="text-xs text-slate-400">
                {result.passed_controls.length} passed &middot; {result.failed_controls.length} failed
              </p>
            </div>

            <div className="bg-slate-800/60 border border-slate-700/80 rounded-xl p-4 flex flex-col justify-between">
              <span className="text-xs uppercase tracking-wider font-semibold text-slate-400">Audit Certificate</span>
              <div className="my-2">
                <span
                  data-testid="certificate-badge"
                  className="font-mono text-xs font-semibold px-2.5 py-1 bg-slate-900 border border-slate-700 rounded text-indigo-400 inline-block"
                >
                  {result.audit_certificate_id}
                </span>
              </div>
              <span className="text-xs text-slate-500">
                Issued {new Date(result.evaluated_at).toLocaleDateString()}
              </span>
            </div>
          </div>

          {result.negative_flags.length > 0 && (
            <div className="p-4 rounded-xl bg-rose-950/30 border border-rose-800/60 text-rose-200 text-xs space-y-1">
              <div className="font-semibold text-rose-400 flex items-center gap-1.5">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
                Critical Statutory Non-Compliance Detected
              </div>
              <ul className="list-disc list-inside space-y-0.5 text-slate-300">
                {result.negative_flags.map((flag, idx) => (
                  <li key={idx}>{flag}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-white uppercase tracking-wider">
              Statutory Control Findings ({result.failed_controls.length} Deficiencies)
            </h3>

            {result.failed_controls.length === 0 ? (
              <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-sm">
                All statutory controls passed! Model conforms with regulatory requirements.
              </div>
            ) : (
              <div className="space-y-3">
                {result.failed_controls.map((fc) => (
                  <div
                    key={fc.control_id}
                    data-testid="failed-control-item"
                    className="p-4 rounded-xl bg-slate-800/40 border border-slate-700/80 space-y-2"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-xs px-2 py-0.5 rounded bg-rose-500/10 text-rose-400 border border-rose-500/20">
                            {fc.control_id}
                          </span>
                          <span className="font-semibold text-sm text-slate-100">{fc.title}</span>
                        </div>
                        <p className="text-xs text-slate-400 mt-1">
                          <span className="text-slate-500">Statutory Citation:</span> {fc.regulation_ref}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => copyRemedy(fc.remedy, fc.control_id)}
                        className="px-2.5 py-1 text-xs rounded bg-slate-700 hover:bg-slate-600 text-slate-200 transition-colors whitespace-nowrap"
                      >
                        {copiedId === fc.control_id ? 'Copied Remedy!' : 'Copy Remedy'}
                      </button>
                    </div>

                    <div className="bg-slate-900/80 rounded-lg p-2.5 border border-slate-800 text-xs text-slate-300">
                      <span className="font-semibold text-indigo-400">Prescriptive Remedy: </span>
                      {fc.remedy}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {result.passed_controls.length > 0 && (
            <div className="space-y-2 pt-2">
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Passed Statutory Controls ({result.passed_controls.length})
              </h3>
              <div className="flex flex-wrap gap-2">
                {result.passed_controls.map((id) => (
                  <span
                    key={id}
                    data-testid="passed-control-item"
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 text-xs font-mono"
                  >
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M5 13l4 4L19 7" />
                    </svg>
                    {id}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
