// DocScout Historical Formula Evolution & Versioning (FEAT-030)
// Interactive chronological formula timeline, point-in-time statutory resolver,
// and side-by-side formula diff engine.

import React, { useState, useEffect } from 'react'

export interface FormulaVersionData {
  id: string
  formula_id: string
  version_label: string
  regulatory_framework: string
  effective_from: string
  effective_to?: string | null
  expression: string
  eval_expression: string
  variables: string[]
  thresholds: Record<string, unknown>
  circular_reference?: string | null
  change_summary: string
  is_currently_active: boolean
}

export interface VersionDiffData {
  formula_id: string
  version_a_id: string
  version_b_id: string
  version_a_label: string
  version_b_label: string
  expression_changed: boolean
  expression_a: string
  expression_b: string
  variables_added: string[]
  variables_removed: string[]
  variables_retained: string[]
  threshold_changes: Record<string, { old?: unknown; new?: unknown }>
  change_type: string
  summary: string
}

export interface TrackedFormula {
  formula_id: string
  current_label: string
  regulatory_framework: string
  version_count: number
  earliest_effective: string
  current_expression: string
  current_thresholds: Record<string, unknown>
}

export const FormulaEvolutionTimeline: React.FC = () => {
  const [selectedFormula, setSelectedFormula] = useState<string>('crar')
  const [history, setHistory] = useState<FormulaVersionData[]>([])
  const [asOfDate, setAsOfDate] = useState<string>('2016-06-15')
  const [resolvedVersion, setResolvedVersion] = useState<FormulaVersionData | null>(null)
  const [versionA, setVersionA] = useState<string>('crar_basel2')
  const [versionB, setVersionB] = useState<string>('crar_basel3_current')
  const [diffResult, setDiffResult] = useState<VersionDiffData | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const fetchHistory = async (fid: string) => {
    setIsLoading(true)
    setErrorMsg(null)
    setDiffResult(null)
    setResolvedVersion(null)
    try {
      const apiKey = localStorage.getItem('docscout_api_key') || ''
      const res = await fetch(`/v1/compliance/formulas/${fid}/history`, {
        headers: { 'X-API-Key': apiKey },
      })
      if (!res.ok) {
        throw new Error(`Failed to load formula history (${res.status})`)
      }
      const data = await res.json()
      setHistory(data.history || [])
      if (data.history && data.history.length >= 2) {
        setVersionA(data.history[0].id)
        setVersionB(data.history[data.history.length - 1].id)
      }
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : String(err))
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    fetchHistory(selectedFormula)
  }, [selectedFormula])

  const handleResolveVersion = async () => {
    if (!asOfDate) return
    setIsLoading(true)
    setErrorMsg(null)
    try {
      const apiKey = localStorage.getItem('docscout_api_key') || ''
      const res = await fetch(`/v1/compliance/formulas/${selectedFormula}/resolve-version`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': apiKey,
        },
        body: JSON.stringify({ as_of_date: asOfDate }),
      })
      if (!res.ok) {
        throw new Error(`Version resolution failed (${res.status})`)
      }
      const data: FormulaVersionData = await res.json()
      setResolvedVersion(data)
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : String(err))
    } finally {
      setIsLoading(false)
    }
  }

  const handleCompareVersions = async () => {
    if (!versionA || !versionB) return
    setIsLoading(true)
    setErrorMsg(null)
    try {
      const apiKey = localStorage.getItem('docscout_api_key') || ''
      const res = await fetch('/v1/compliance/formulas/compare-versions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': apiKey,
        },
        body: JSON.stringify({ version_a_id: versionA, version_b_id: versionB }),
      })
      if (!res.ok) {
        throw new Error(`Formula version comparison failed (${res.status})`)
      }
      const data: VersionDiffData = await res.json()
      setDiffResult(data)
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
            Historical Regulatory Formula Evolution & Diff Engine
          </h2>
          <p style={{ margin: '4px 0 0', color: '#94a3b8', fontSize: '0.85rem' }}>
            Multi-decade statutory formula timeline, point-in-time version resolution, and semantic audit diffs
          </p>
        </div>

        {/* Metric Selector */}
        <div style={{ display: 'flex', gap: '8px' }}>
          {[
            { id: 'crar', label: 'CRAR (Basel I-III)' },
            { id: 'lcr', label: 'LCR (2015-2019)' },
            { id: 'pcr', label: 'PCR (IRAC Norms)' },
            { id: 'sci', label: 'SCI (ISO 21031)' },
          ].map((m) => (
            <button
              key={m.id}
              onClick={() => setSelectedFormula(m.id)}
              style={{
                background: selectedFormula === m.id ? '#0284c7' : '#090d16',
                border: '1px solid #334155',
                color: selectedFormula === m.id ? '#fff' : '#94a3b8',
                padding: '6px 12px',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '0.8rem',
                fontWeight: 600,
              }}
            >
              {m.label}
            </button>
          ))}
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

      {/* Chronological Evolution Timeline */}
      <div style={{ marginBottom: '24px' }}>
        <h3 style={{ margin: '0 0 12px', fontSize: '1rem', color: '#e2e8f0' }}>
          Chronological Statutory Versions ({history.length} Revisions)
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '12px' }}>
          {history.map((ver, idx) => (
            <div
              key={ver.id}
              style={{
                background: '#090d16',
                border: ver.is_currently_active ? '1px solid #38bdf8' : '1px solid #1e293b',
                borderRadius: '8px',
                padding: '14px',
                position: 'relative',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <span
                  style={{
                    fontSize: '0.7rem',
                    color: '#94a3b8',
                    textTransform: 'uppercase',
                    letterSpacing: '0.05em',
                  }}
                >
                  Epoch {idx + 1}
                </span>
                <span
                  style={{
                    fontSize: '0.65rem',
                    padding: '2px 6px',
                    borderRadius: '4px',
                    background: ver.is_currently_active ? '#0369a1' : '#1e293b',
                    color: ver.is_currently_active ? '#fff' : '#94a3b8',
                    fontWeight: 600,
                  }}
                >
                  {ver.is_currently_active ? 'ACTIVE' : 'SUPERSEDED'}
                </span>
              </div>

              <h4 style={{ margin: '8px 0 4px', fontSize: '0.9rem', color: '#f8fafc' }}>
                {ver.version_label}
              </h4>
              <div style={{ fontSize: '0.75rem', color: '#38bdf8', marginBottom: '8px' }}>
                {ver.effective_from} to {ver.effective_to || 'Present'}
              </div>

              <div
                style={{
                  background: '#040711',
                  border: '1px solid #1e293b',
                  borderRadius: '4px',
                  padding: '6px 8px',
                  fontFamily: 'monospace',
                  fontSize: '0.72rem',
                  color: '#a5f3fc',
                  marginBottom: '8px',
                  wordBreak: 'break-all',
                }}
              >
                {ver.expression}
              </div>

              <p style={{ margin: 0, fontSize: '0.75rem', color: '#94a3b8', lineHeight: 1.4 }}>
                {ver.change_summary}
              </p>

              {ver.circular_reference && (
                <div style={{ marginTop: '8px', fontSize: '0.7rem', color: '#64748b' }}>
                  Ref: {ver.circular_reference}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
        {/* Left Box: Point-in-Time Version Resolver */}
        <div style={{ background: '#090d16', border: '1px solid #1e293b', borderRadius: '8px', padding: '16px' }}>
          <h4 style={{ margin: '0 0 10px', fontSize: '0.95rem', color: '#38bdf8' }}>
            Point-in-Time Statutory Resolver
          </h4>
          <p style={{ margin: '0 0 12px', fontSize: '0.8rem', color: '#94a3b8' }}>
            Determine which statutory formula was legally enforceful for a historical inspection or audit date.
          </p>

          <div style={{ display: 'flex', gap: '10px', marginBottom: '16px' }}>
            <input
              type="date"
              value={asOfDate}
              onChange={(e) => setAsOfDate(e.target.value)}
              style={{
                flex: 1,
                background: '#040711',
                border: '1px solid #334155',
                borderRadius: '6px',
                padding: '8px 12px',
                color: '#f8fafc',
                fontSize: '0.85rem',
              }}
            />
            <button
              onClick={handleResolveVersion}
              disabled={isLoading}
              style={{
                background: '#0284c7',
                border: 'none',
                color: '#fff',
                padding: '8px 16px',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '0.85rem',
                fontWeight: 600,
              }}
            >
              Resolve
            </button>
          </div>

          {resolvedVersion && (
            <div
              style={{
                background: '#040711',
                border: '1px solid #0284c7',
                borderRadius: '6px',
                padding: '12px',
              }}
            >
              <div style={{ fontSize: '0.7rem', color: '#38bdf8', textTransform: 'uppercase' }}>
                ACTIVE DEFINITION AS OF {asOfDate}
              </div>
              <div style={{ fontSize: '1rem', fontWeight: 700, color: '#f8fafc', margin: '4px 0' }}>
                {resolvedVersion.version_label}
              </div>
              <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginBottom: '8px' }}>
                Effective window: {resolvedVersion.effective_from} to {resolvedVersion.effective_to || 'Present'}
              </div>
              <div
                style={{
                  background: '#0a0f1d',
                  padding: '8px',
                  borderRadius: '4px',
                  fontFamily: 'monospace',
                  fontSize: '0.75rem',
                  color: '#a5f3fc',
                  marginBottom: '8px',
                }}
              >
                {resolvedVersion.expression}
              </div>
              <div style={{ fontSize: '0.75rem', color: '#cbd5e1' }}>
                <strong>Thresholds:</strong> {JSON.stringify(resolvedVersion.thresholds)}
              </div>
            </div>
          )}
        </div>

        {/* Right Box: Formula Version Comparator (Diff Engine) */}
        <div style={{ background: '#090d16', border: '1px solid #1e293b', borderRadius: '8px', padding: '16px' }}>
          <h4 style={{ margin: '0 0 10px', fontSize: '0.95rem', color: '#10b981' }}>
            Regulatory Formula Diff & Impact Engine
          </h4>
          <p style={{ margin: '0 0 12px', fontSize: '0.8rem', color: '#94a3b8' }}>
            Compare any two historical epochs to audit parameter additions, phase-outs, and threshold changes.
          </p>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: '10px', marginBottom: '16px' }}>
            <select
              value={versionA}
              onChange={(e) => setVersionA(e.target.value)}
              style={{
                background: '#040711',
                border: '1px solid #334155',
                borderRadius: '6px',
                padding: '8px',
                color: '#f8fafc',
                fontSize: '0.8rem',
              }}
            >
              {history.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.version_label}
                </option>
              ))}
            </select>

            <select
              value={versionB}
              onChange={(e) => setVersionB(e.target.value)}
              style={{
                background: '#040711',
                border: '1px solid #334155',
                borderRadius: '6px',
                padding: '8px',
                color: '#f8fafc',
                fontSize: '0.8rem',
              }}
            >
              {history.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.version_label}
                </option>
              ))}
            </select>

            <button
              onClick={handleCompareVersions}
              disabled={isLoading}
              style={{
                background: '#059669',
                border: 'none',
                color: '#fff',
                padding: '8px 16px',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '0.85rem',
                fontWeight: 600,
              }}
            >
              Compare
            </button>
          </div>

          {diffResult && (
            <div
              style={{
                background: '#040711',
                border: '1px solid #059669',
                borderRadius: '6px',
                padding: '12px',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#f8fafc' }}>
                  {diffResult.version_a_label} vs {diffResult.version_b_label}
                </span>
                <span
                  style={{
                    fontSize: '0.65rem',
                    padding: '2px 6px',
                    borderRadius: '4px',
                    background: diffResult.change_type === 'breaking' ? '#7f1d1d' : '#064e3b',
                    color: '#fff',
                    fontWeight: 700,
                    textTransform: 'uppercase',
                  }}
                >
                  {diffResult.change_type}
                </span>
              </div>

              <p style={{ margin: '0 0 10px', fontSize: '0.75rem', color: '#94a3b8' }}>
                {diffResult.summary}
              </p>

              {/* Variable Changes */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.75rem' }}>
                {diffResult.variables_added.length > 0 && (
                  <div>
                    <strong style={{ color: '#34d399' }}>Added Variables: </strong>
                    {diffResult.variables_added.join(', ')}
                  </div>
                )}
                {diffResult.variables_removed.length > 0 && (
                  <div>
                    <strong style={{ color: '#f87171' }}>Phased Out Variables: </strong>
                    {diffResult.variables_removed.join(', ')}
                  </div>
                )}
                {Object.keys(diffResult.threshold_changes).length > 0 && (
                  <div>
                    <strong style={{ color: '#fbbf24' }}>Threshold Adjustments: </strong>
                    {Object.entries(diffResult.threshold_changes)
                      .map(([k, ch]) => `${k}: ${ch.old} -> ${ch.new}`)
                      .join(' | ')}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
