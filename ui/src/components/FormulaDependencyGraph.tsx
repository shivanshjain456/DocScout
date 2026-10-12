// DocScout Formula Dependency Graph Builder (FEAT-029)
// Interactive multi-stage regulatory DAG visualizer, topological execution tier inspector,
// prerequisite verification, and cascade evaluation test bench.

import React, { useState, useEffect } from 'react'

export interface GraphNode {
  node_id: string
  name: string
  node_type: 'INPUT' | 'INTERMEDIATE' | 'OUTPUT'
  expression?: string | null
  description: string
  category: string
  unit: string
  tier: number
  dependencies: string[]
}

export interface GraphEdge {
  source: string
  target: string
  parameter_name: string
}

export interface DependencyGraphData {
  graph_id: string
  name: string
  domain: string
  description: string
  nodes: Record<string, GraphNode>
  edges: GraphEdge[]
  topological_order: string[]
  execution_tiers: string[][]
  target_variables: string[]
}

export interface TraceStep {
  node_id: string
  node_type: string
  value?: number | null
  status: string
  expression?: string | null
  tier?: number | null
  missing_prerequisites?: string[] | null
  error?: string | null
}

export interface EvaluationResult {
  is_complete: boolean
  target_outputs: Record<string, number | null>
  computed_values: Record<string, number>
  trace: TraceStep[]
  missing_variables: string[]
  latency_ms: number
}

export interface PrerequisiteCheck {
  is_ready: boolean
  target_variables: string[]
  required_inputs_count: number
  provided_inputs: string[]
  missing_inputs: string[]
  completion_percentage: number
  resolvable_intermediates: string[]
}

const TEMPLATE_PRESETS = [
  { id: 'basel3_crar', label: 'Basel III CRAR & Capital Ratios' },
  { id: 'lcr_framework', label: 'Liquidity Coverage Ratio (LCR 30-Day)' },
  { id: 'asset_quality_irac', label: 'Asset Quality & Provision Coverage (IRAC)' },
  { id: 'software_carbon_intensity', label: 'ISO/IEC 21031 Software Carbon (SCI)' },
]

export const FormulaDependencyGraph: React.FC = () => {
  const [selectedTemplate, setSelectedTemplate] = useState<string>('basel3_crar')
  const [graphData, setGraphData] = useState<DependencyGraphData | null>(null)
  const [inputs, setInputs] = useState<Record<string, string>>({})
  const [evalResult, setEvalResult] = useState<EvaluationResult | null>(null)
  const [prereqCheck, setPrereqCheck] = useState<PrerequisiteCheck | null>(null)
  const [activeTab, setActiveTab] = useState<'tiers' | 'evaluation' | 'prereqs'>('tiers')
  const [isLoading, setIsLoading] = useState<boolean>(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const fetchGraph = async (templateId: string) => {
    setIsLoading(true)
    setErrorMsg(null)
    setEvalResult(null)
    setPrereqCheck(null)
    try {
      const apiKey = localStorage.getItem('docscout_api_key') || ''
      const res = await fetch(`/v1/compliance/dependency-graphs/${templateId}`, {
        headers: { 'X-API-Key': apiKey },
      })
      if (!res.ok) {
        throw new Error(`Failed to load calculation graph (${res.status})`)
      }
      const data: DependencyGraphData = await res.json()
      setGraphData(data)

      // Initialize inputs with reasonable defaults
      const initialInputs: Record<string, string> = {}
      Object.values(data.nodes).forEach((n) => {
        if (n.node_type === 'INPUT') {
          if (templateId === 'basel3_crar') {
            if (n.node_id === 'common_shares') initialInputs[n.node_id] = '5000'
            else if (n.node_id === 'retained_earnings') initialInputs[n.node_id] = '3200'
            else if (n.node_id === 'statutory_reserves') initialInputs[n.node_id] = '1800'
            else if (n.node_id === 'regulatory_deductions') initialInputs[n.node_id] = '200'
            else if (n.node_id === 'additional_tier1') initialInputs[n.node_id] = '1200'
            else if (n.node_id === 'subordinated_debt') initialInputs[n.node_id] = '1500'
            else if (n.node_id === 'general_provisions') initialInputs[n.node_id] = '300'
            else if (n.node_id === 'credit_rwa') initialInputs[n.node_id] = '65000'
            else if (n.node_id === 'market_rwa') initialInputs[n.node_id] = '8500'
            else if (n.node_id === 'operational_rwa') initialInputs[n.node_id] = '6500'
            else initialInputs[n.node_id] = '100'
          } else if (templateId === 'lcr_framework') {
            if (n.node_id === 'level1_cash_reserves') initialInputs[n.node_id] = '4500'
            else if (n.node_id === 'level1_gov_bonds') initialInputs[n.node_id] = '8500'
            else if (n.node_id === 'level2a_corporate_bonds') initialInputs[n.node_id] = '2000'
            else if (n.node_id === 'stressed_30d_cash_outflows') initialInputs[n.node_id] = '11000'
            else if (n.node_id === 'stressed_30d_cash_inflows') initialInputs[n.node_id] = '2500'
            else initialInputs[n.node_id] = '100'
          } else if (templateId === 'asset_quality_irac') {
            if (n.node_id === 'substandard_assets') initialInputs[n.node_id] = '1200'
            else if (n.node_id === 'doubtful_assets') initialInputs[n.node_id] = '800'
            else if (n.node_id === 'loss_assets') initialInputs[n.node_id] = '250'
            else if (n.node_id === 'cumulative_provisions') initialInputs[n.node_id] = '1600'
            else if (n.node_id === 'gross_advances') initialInputs[n.node_id] = '45000'
            else if (n.node_id === 'net_advances') initialInputs[n.node_id] = '43400'
            else initialInputs[n.node_id] = '100'
          } else if (templateId === 'software_carbon_intensity') {
            if (n.node_id === 'energy_consumption_kwh') initialInputs[n.node_id] = '14500'
            else if (n.node_id === 'grid_carbon_intensity') initialInputs[n.node_id] = '0.475'
            else if (n.node_id === 'embodied_carbon') initialInputs[n.node_id] = '820'
            else if (n.node_id === 'functional_unit_r') initialInputs[n.node_id] = '1000000'
            else initialInputs[n.node_id] = '100'
          } else {
            initialInputs[n.node_id] = '100'
          }
        }
      })
      setInputs(initialInputs)
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : String(err))
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    fetchGraph(selectedTemplate)
  }, [selectedTemplate])

  const handleInputChange = (nodeId: string, val: string) => {
    setInputs((prev) => ({ ...prev, [nodeId]: val }))
  }

  const handleCheckPrerequisites = async () => {
    if (!graphData) return
    setIsLoading(true)
    setErrorMsg(null)
    try {
      const apiKey = localStorage.getItem('docscout_api_key') || ''
      const numInputs: Record<string, number> = {}
      Object.entries(inputs).forEach(([k, v]) => {
        if (v.trim() !== '') {
          const parsed = parseFloat(v)
          if (!isNaN(parsed)) numInputs[k] = parsed
        }
      })

      const res = await fetch('/v1/compliance/dependency-graphs/prerequisites', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': apiKey,
        },
        body: JSON.stringify({
          template_id: graphData.graph_id,
          provided_inputs: numInputs,
        }),
      })

      if (!res.ok) {
        throw new Error(`Prerequisite verification failed (${res.status})`)
      }
      const data: PrerequisiteCheck = await res.json()
      setPrereqCheck(data)
      setActiveTab('prereqs')
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : String(err))
    } finally {
      setIsLoading(false)
    }
  }

  const handleEvaluateCascade = async () => {
    if (!graphData) return
    setIsLoading(true)
    setErrorMsg(null)
    try {
      const apiKey = localStorage.getItem('docscout_api_key') || ''
      const numInputs: Record<string, number> = {}
      Object.entries(inputs).forEach(([k, v]) => {
        if (v.trim() !== '') {
          const parsed = parseFloat(v)
          if (!isNaN(parsed)) numInputs[k] = parsed
        }
      })

      const res = await fetch('/v1/compliance/dependency-graphs/evaluate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': apiKey,
        },
        body: JSON.stringify({
          template_id: graphData.graph_id,
          provided_inputs: numInputs,
        }),
      })

      if (!res.ok) {
        throw new Error(`Cascade evaluation failed (${res.status})`)
      }
      const data: EvaluationResult = await res.json()
      setEvalResult(data)
      setActiveTab('evaluation')
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : String(err))
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div
      style={{
        background: '#040711',
        color: '#f8fafc',
        fontFamily: 'Inter, system-ui, sans-serif',
        padding: '24px',
        borderRadius: '10px',
        border: '1px solid #1e293b',
        maxWidth: '1200px',
        margin: '0 auto',
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '20px',
          borderBottom: '1px solid #1e293b',
          paddingBottom: '16px',
        }}
      >
        <div>
          <h2 style={{ margin: 0, fontSize: '1.4rem', fontWeight: 700, color: '#38bdf8' }}>
            Statutory Formula Dependency Graph Builder
          </h2>
          <p style={{ margin: '4px 0 0', color: '#94a3b8', fontSize: '0.85rem' }}>
            Topological calculation DAG, cycle detection, execution stages, and prerequisite auditor
          </p>
        </div>

        {/* Template Preset Selector */}
        <div>
          <label style={{ fontSize: '0.75rem', color: '#64748b', display: 'block', marginBottom: '4px' }}>
            REGULATORY TEMPLATE
          </label>
          <select
            value={selectedTemplate}
            onChange={(e) => setSelectedTemplate(e.target.value)}
            style={{
              background: '#090d16',
              border: '1px solid #334155',
              borderRadius: '6px',
              padding: '8px 12px',
              color: '#f8fafc',
              fontSize: '0.85rem',
            }}
          >
            {TEMPLATE_PRESETS.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {errorMsg && (
        <div
          style={{
            background: 'rgba(239, 68, 68, 0.1)',
            border: '1px solid #ef4444',
            color: '#fca5a5',
            padding: '12px',
            borderRadius: '6px',
            marginBottom: '16px',
            fontSize: '0.85rem',
          }}
        >
          {errorMsg}
        </div>
      )}

      {graphData && (
        <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: '20px' }}>
          {/* Left Column: Exogenous Inputs Panel */}
          <div
            style={{
              background: '#090d16',
              border: '1px solid #1e293b',
              borderRadius: '8px',
              padding: '16px',
              display: 'flex',
              flexDirection: 'column',
              gap: '12px',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 600, color: '#e2e8f0' }}>
                Exogenous Inputs
              </h3>
              <span
                style={{
                  fontSize: '0.75rem',
                  padding: '2px 6px',
                  borderRadius: '4px',
                  background: '#1e293b',
                  color: '#94a3b8',
                }}
              >
                {Object.values(graphData.nodes).filter((n) => n.node_type === 'INPUT').length} Vars
              </span>
            </div>

            <div style={{ maxHeight: '420px', overflowY: 'auto', paddingRight: '4px' }}>
              {Object.values(graphData.nodes)
                .filter((n) => n.node_type === 'INPUT')
                .map((n) => (
                  <div key={n.node_id} style={{ marginBottom: '10px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '2px' }}>
                      <label style={{ fontSize: '0.75rem', color: '#cbd5e1' }}>{n.name}</label>
                      <span style={{ fontSize: '0.7rem', color: '#64748b' }}>{n.node_id}</span>
                    </div>
                    <input
                      type="text"
                      value={inputs[n.node_id] || ''}
                      onChange={(e) => handleInputChange(n.node_id, e.target.value)}
                      placeholder="Enter value..."
                      style={{
                        width: '100%',
                        boxSizing: 'border-box',
                        background: '#040711',
                        border: '1px solid #334155',
                        borderRadius: '4px',
                        padding: '6px 8px',
                        color: '#f8fafc',
                        fontSize: '0.85rem',
                      }}
                    />
                  </div>
                ))}
            </div>

            {/* Action Buttons */}
            <div style={{ display: 'flex', gap: '8px', marginTop: 'auto', paddingTop: '8px' }}>
              <button
                onClick={handleCheckPrerequisites}
                disabled={isLoading}
                style={{
                  flex: 1,
                  background: '#1e293b',
                  border: '1px solid #334155',
                  color: '#e2e8f0',
                  padding: '8px 12px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '0.8rem',
                  fontWeight: 500,
                }}
              >
                Check Readiness
              </button>
              <button
                onClick={handleEvaluateCascade}
                disabled={isLoading}
                style={{
                  flex: 1,
                  background: '#0284c7',
                  border: 'none',
                  color: '#fff',
                  padding: '8px 12px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '0.8rem',
                  fontWeight: 600,
                }}
              >
                Evaluate DAG
              </button>
            </div>
          </div>

          {/* Right Column: Visualization & Execution Trace */}
          <div>
            {/* Tab Navigation */}
            <div
              style={{
                display: 'flex',
                gap: '8px',
                borderBottom: '1px solid #1e293b',
                paddingBottom: '8px',
                marginBottom: '16px',
              }}
            >
              <button
                onClick={() => setActiveTab('tiers')}
                style={{
                  background: activeTab === 'tiers' ? '#0f172a' : 'transparent',
                  border: activeTab === 'tiers' ? '1px solid #38bdf8' : '1px solid transparent',
                  color: activeTab === 'tiers' ? '#38bdf8' : '#94a3b8',
                  padding: '6px 14px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '0.85rem',
                  fontWeight: 600,
                }}
              >
                Execution Tiers ({graphData.execution_tiers.length} Stages)
              </button>
              <button
                onClick={() => setActiveTab('evaluation')}
                style={{
                  background: activeTab === 'evaluation' ? '#0f172a' : 'transparent',
                  border: activeTab === 'evaluation' ? '1px solid #10b981' : '1px solid transparent',
                  color: activeTab === 'evaluation' ? '#10b981' : '#94a3b8',
                  padding: '6px 14px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '0.85rem',
                  fontWeight: 600,
                }}
              >
                Cascade Results {evalResult ? `(${evalResult.latency_ms} ms)` : ''}
              </button>
              <button
                onClick={() => setActiveTab('prereqs')}
                style={{
                  background: activeTab === 'prereqs' ? '#0f172a' : 'transparent',
                  border: activeTab === 'prereqs' ? '1px solid #f59e0b' : '1px solid transparent',
                  color: activeTab === 'prereqs' ? '#f59e0b' : '#94a3b8',
                  padding: '6px 14px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '0.85rem',
                  fontWeight: 600,
                }}
              >
                Prerequisite Audit
              </button>
            </div>

            {/* Tab 1: Execution Tiers & Graph Stages */}
            {activeTab === 'tiers' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div style={{ fontSize: '0.85rem', color: '#94a3b8' }}>
                  Topological Sort Order: {graphData.topological_order.join(' -> ')}
                </div>

                {graphData.execution_tiers.map((tierNodes, idx) => (
                  <div
                    key={idx}
                    style={{
                      background: '#090d16',
                      border: '1px solid #1e293b',
                      borderRadius: '8px',
                      padding: '14px',
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        marginBottom: '10px',
                      }}
                    >
                      <span
                        style={{
                          fontSize: '0.8rem',
                          fontWeight: 700,
                          color: idx === 0 ? '#64748b' : idx === graphData.execution_tiers.length - 1 ? '#38bdf8' : '#fbbf24',
                          letterSpacing: '0.05em',
                        }}
                      >
                        STAGE {idx} {idx === 0 ? '(EXOGENOUS BASE)' : idx === graphData.execution_tiers.length - 1 ? '(TERMINAL METRICS)' : '(INTERMEDIATE COMPOSITES)'}
                      </span>
                      <span style={{ fontSize: '0.75rem', color: '#64748b' }}>
                        {tierNodes.length} nodes
                      </span>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: '10px' }}>
                      {tierNodes.map((nid) => {
                        const node = graphData.nodes[nid]
                        if (!node) return null
                        const isTarget = graphData.target_variables.includes(nid)
                        return (
                          <div
                            key={nid}
                            style={{
                              background: '#040711',
                              border: isTarget ? '1px solid #38bdf8' : '1px solid #334155',
                              borderRadius: '6px',
                              padding: '10px',
                            }}
                          >
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                              <span style={{ fontSize: '0.85rem', fontWeight: 600, color: '#f8fafc' }}>
                                {node.name}
                              </span>
                              <span
                                style={{
                                  fontSize: '0.65rem',
                                  padding: '1px 5px',
                                  borderRadius: '3px',
                                  background: node.node_type === 'INPUT' ? '#1e293b' : isTarget ? '#0369a1' : '#854d0e',
                                  color: '#fff',
                                }}
                              >
                                {node.node_type}
                              </span>
                            </div>
                            {node.expression && (
                              <div
                                style={{
                                  marginTop: '6px',
                                  fontSize: '0.72rem',
                                  fontFamily: 'monospace',
                                  color: '#a5f3fc',
                                  background: '#0a0f1d',
                                  padding: '4px 6px',
                                  borderRadius: '3px',
                                  overflowX: 'auto',
                                }}
                              >
                                = {node.expression}
                              </div>
                            )}
                            {node.dependencies.length > 0 && (
                              <div style={{ marginTop: '6px', fontSize: '0.7rem', color: '#64748b' }}>
                                Depends on: {node.dependencies.join(', ')}
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Tab 2: Cascade Evaluation Results */}
            {activeTab === 'evaluation' && (
              <div>
                {!evalResult ? (
                  <div style={{ textAlign: 'center', padding: '40px', color: '#64748b' }}>
                    Click "Evaluate DAG" to compute statutory outputs step-by-step.
                  </div>
                ) : (
                  <div>
                    {/* Key Output Metric Cards */}
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px', marginBottom: '20px' }}>
                      {Object.entries(evalResult.target_outputs).map(([metricKey, val]) => (
                        <div
                          key={metricKey}
                          style={{
                            background: '#090d16',
                            border: '1px solid #38bdf8',
                            borderRadius: '8px',
                            padding: '16px',
                          }}
                        >
                          <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                            {graphData.nodes[metricKey]?.name || metricKey.toUpperCase()}
                          </div>
                          <div style={{ fontSize: '1.6rem', fontWeight: 700, color: '#38bdf8', marginTop: '4px' }}>
                            {val !== null ? `${val} ${graphData.nodes[metricKey]?.unit || ''}` : 'N/A'}
                          </div>
                        </div>
                      ))}
                    </div>

                    {/* Step-by-Step Calculation Trace */}
                    <div style={{ background: '#090d16', border: '1px solid #1e293b', borderRadius: '8px', padding: '16px' }}>
                      <h4 style={{ margin: '0 0 12px', fontSize: '0.9rem', color: '#e2e8f0' }}>
                        Topological Calculation Trace ({evalResult.trace.length} Steps)
                      </h4>
                      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                        <thead>
                          <tr style={{ borderBottom: '1px solid #1e293b', color: '#64748b', textAlign: 'left' }}>
                            <th style={{ padding: '8px' }}>Node</th>
                            <th style={{ padding: '8px' }}>Type</th>
                            <th style={{ padding: '8px' }}>Formula</th>
                            <th style={{ padding: '8px' }}>Computed Value</th>
                            <th style={{ padding: '8px' }}>Status</th>
                          </tr>
                        </thead>
                        <tbody>
                          {evalResult.trace.map((step, sIdx) => (
                            <tr key={sIdx} style={{ borderBottom: '1px solid #0f172a' }}>
                              <td style={{ padding: '8px', fontWeight: 600, color: '#f8fafc' }}>{step.node_id}</td>
                              <td style={{ padding: '8px', color: '#94a3b8' }}>{step.node_type}</td>
                              <td style={{ padding: '8px', fontFamily: 'monospace', color: '#a5f3fc' }}>
                                {step.expression || '-'}
                              </td>
                              <td style={{ padding: '8px', fontWeight: 700, color: step.value !== null ? '#10b981' : '#f87171' }}>
                                {step.value !== null && step.value !== undefined ? step.value : 'None'}
                              </td>
                              <td style={{ padding: '8px' }}>
                                <span
                                  style={{
                                    padding: '2px 6px',
                                    borderRadius: '4px',
                                    fontSize: '0.7rem',
                                    background:
                                      step.status === 'COMPUTED'
                                        ? '#064e3b'
                                        : step.status === 'PROVIDED'
                                        ? '#1e293b'
                                        : '#7f1d1d',
                                    color: '#fff',
                                  }}
                                >
                                  {step.status}
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Tab 3: Prerequisite Verification Audit */}
            {activeTab === 'prereqs' && (
              <div>
                {!prereqCheck ? (
                  <div style={{ textAlign: 'center', padding: '40px', color: '#64748b' }}>
                    Click "Check Readiness" to evaluate missing prerequisite inputs.
                  </div>
                ) : (
                  <div style={{ background: '#090d16', border: '1px solid #1e293b', borderRadius: '8px', padding: '16px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                      <h4 style={{ margin: 0, fontSize: '0.95rem', color: prereqCheck.is_ready ? '#10b981' : '#f59e0b' }}>
                        {prereqCheck.is_ready ? 'Ready for Execution (100% Inputs Present)' : `Missing Inputs (${prereqCheck.completion_percentage}% Ready)`}
                      </h4>
                      <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
                        {prereqCheck.provided_inputs.length} of {prereqCheck.required_inputs_count} provided
                      </span>
                    </div>

                    {prereqCheck.missing_inputs.length > 0 && (
                      <div style={{ marginBottom: '16px' }}>
                        <div style={{ fontSize: '0.75rem', color: '#f87171', marginBottom: '6px', fontWeight: 600 }}>
                          MISSING PREREQUISITE INPUTS:
                        </div>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                          {prereqCheck.missing_inputs.map((m) => (
                            <span
                              key={m}
                              style={{
                                background: '#450a0a',
                                border: '1px solid #b91c1c',
                                color: '#fca5a5',
                                padding: '3px 8px',
                                borderRadius: '4px',
                                fontSize: '0.75rem',
                              }}
                            >
                              {m}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    <div>
                      <div style={{ fontSize: '0.75rem', color: '#38bdf8', marginBottom: '6px', fontWeight: 600 }}>
                        RESOLVABLE INTERMEDIATE VARIABLES:
                      </div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                        {prereqCheck.resolvable_intermediates.map((r) => (
                          <span
                            key={r}
                            style={{
                              background: '#042f2e',
                              border: '1px solid #0f766e',
                              color: '#5eead4',
                              padding: '3px 8px',
                              borderRadius: '4px',
                              fontSize: '0.75rem',
                            }}
                          >
                            {r}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
