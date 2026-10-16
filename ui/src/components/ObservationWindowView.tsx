import React, { useState, useEffect, useCallback } from 'react'

export interface ObservationStatusData {
  control_id: string
  tenant_id: string
  observation_window_days: number
  compliance_percentage: number
  unbroken_streak_days: number
  total_observations: number
  pass_count: number
  fail_count: number
  window_start: string | null
  window_end: string | null
  status: 'COMPLIANT' | 'NON_COMPLIANT' | 'INSUFFICIENT_DATA'
}

export interface ObservationWindowViewProps {
  controlId: string
  tenantId?: string
  windowDays?: number
  apiBaseUrl?: string
  apiKey?: string
  className?: string
  onRefresh?: () => void
}

export const ObservationWindowView: React.FC<ObservationWindowViewProps> = ({
  controlId,
  tenantId = 'default',
  windowDays = 90,
  apiBaseUrl = '',
  apiKey = '',
  className = '',
  onRefresh,
}) => {
  const [data, setData] = useState<ObservationStatusData | null>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)

  // Quick Ingest Telemetry state
  const [isIngesting, setIsIngesting] = useState<boolean>(false)
  const [ingestResult, setIngestResult] = useState<'PASS' | 'FAIL'>('PASS')
  const [ingestSuccessMsg, setIngestSuccessMsg] = useState<string | null>(null)

  const fetchStatus = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const url = `${apiBaseUrl}/v1/compliance/telemetry/window/${encodeURIComponent(
        controlId
      )}?tenant_id=${encodeURIComponent(tenantId)}&window_days=${windowDays}`

      const headers: Record<string, string> = {}
      if (apiKey) {
        headers['X-API-Key'] = apiKey
      }

      const res = await fetch(url, { headers })
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}))
        throw new Error(errJson.detail || `Server returned status ${res.status}`)
      }
      const json: ObservationStatusData = await res.json()
      setData(json)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to fetch observation window status'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }, [controlId, tenantId, windowDays, apiBaseUrl, apiKey])

  useEffect(() => {
    if (controlId) {
      fetchStatus()
    }
  }, [controlId, fetchStatus])

  const handleQuickIngest = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsIngesting(true)
    setIngestSuccessMsg(null)
    setError(null)

    try {
      const dummyHash = Array.from({ length: 64 }, () =>
        Math.floor(Math.random() * 16).toString(16)
      ).join('')

      const payload = {
        tenant_id: tenantId,
        control_id: controlId,
        observation_timestamp: new Date().toISOString(),
        check_result: ingestResult,
        evidence_hash: dummyHash,
      }

      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
      }
      if (apiKey) {
        headers['X-API-Key'] = apiKey
      }

      const res = await fetch(`${apiBaseUrl}/v1/compliance/telemetry/ingest`, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload),
      })

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}))
        throw new Error(errJson.detail || `Ingestion error ${res.status}`)
      }

      setIngestSuccessMsg(`Telemetry ${ingestResult} successfully logged and verified.`)
      await fetchStatus()
      if (onRefresh) {
        onRefresh()
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to ingest telemetry'
      setError(msg)
    } finally {
      setIsIngesting(false)
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'COMPLIANT':
        return '#3fb950'
      case 'NON_COMPLIANT':
        return '#f85149'
      default:
        return '#8b949e'
    }
  }

  return (
    <div
      role="region"
      aria-label="Continuous Compliance Observation Window Tracker"
      className={`observation-window-container ${className}`}
      style={{
        backgroundColor: '#0d1117',
        border: '1px solid #30363d',
        borderRadius: '8px',
        padding: '20px',
        color: '#c9d1d9',
        fontFamily: 'system-ui, -apple-system, sans-serif',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          borderBottom: '1px solid #21262d',
          paddingBottom: '12px',
          marginBottom: '16px',
        }}
      >
        <div>
          <h3
            id="observation-window-title"
            style={{ margin: 0, fontSize: '18px', fontWeight: 600, color: '#f0f6fc' }}
          >
            Observation Window Tracker: {controlId}
          </h3>
          <p style={{ margin: '4px 0 0 0', fontSize: '12px', color: '#8b949e' }}>
            Tenant: <strong>{tenantId}</strong> | Audit Window: <strong>{windowDays} Days</strong>
          </p>
        </div>

        <button
          type="button"
          onClick={() => fetchStatus()}
          disabled={loading}
          style={{
            backgroundColor: '#21262d',
            color: '#c9d1d9',
            border: '1px solid #30363d',
            borderRadius: '6px',
            padding: '6px 12px',
            fontSize: '13px',
            cursor: loading ? 'not-allowed' : 'pointer',
          }}
        >
          {loading ? 'Refreshing...' : 'Refresh Window'}
        </button>
      </div>

      {error && (
        <div
          role="alert"
          style={{
            backgroundColor: 'rgba(248, 81, 73, 0.15)',
            border: '1px solid #f85149',
            borderRadius: '6px',
            padding: '10px 14px',
            marginBottom: '16px',
            color: '#ff7b72',
            fontSize: '13px',
          }}
        >
          {error}
        </div>
      )}

      {loading && !data && (
        <div style={{ textAlign: 'center', padding: '30px', color: '#8b949e' }}>
          Loading observation telemetry data...
        </div>
      )}

      {data && (
        <div>
          {/* Top Metric Cards */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
              gap: '12px',
              marginBottom: '20px',
            }}
          >
            {/* Compliance Percentage Card */}
            <div
              style={{
                backgroundColor: '#161b22',
                border: '1px solid #30363d',
                borderRadius: '6px',
                padding: '14px',
                textAlign: 'center',
              }}
            >
              <div style={{ fontSize: '12px', color: '#8b949e', marginBottom: '6px' }}>
                Compliance Health Score
              </div>
              <div
                data-testid="compliance-percentage-gauge"
                style={{
                  fontSize: '28px',
                  fontWeight: 700,
                  color: getStatusColor(data.status),
                }}
              >
                {data.compliance_percentage}%
              </div>
              <span
                data-testid="compliance-status-badge"
                style={{
                  display: 'inline-block',
                  marginTop: '6px',
                  fontSize: '11px',
                  fontWeight: 600,
                  padding: '2px 8px',
                  borderRadius: '12px',
                  backgroundColor:
                    data.status === 'COMPLIANT'
                      ? 'rgba(63, 185, 80, 0.2)'
                      : data.status === 'NON_COMPLIANT'
                      ? 'rgba(248, 81, 73, 0.2)'
                      : 'rgba(139, 148, 158, 0.2)',
                  color: getStatusColor(data.status),
                }}
              >
                {data.status}
              </span>
            </div>

            {/* Unbroken Streak Card */}
            <div
              style={{
                backgroundColor: '#161b22',
                border: '1px solid #30363d',
                borderRadius: '6px',
                padding: '14px',
                textAlign: 'center',
              }}
            >
              <div style={{ fontSize: '12px', color: '#8b949e', marginBottom: '6px' }}>
                Unbroken Streak
              </div>
              <div
                data-testid="unbroken-streak-counter"
                style={{ fontSize: '28px', fontWeight: 700, color: '#58a6ff' }}
              >
                {data.unbroken_streak_days} <span style={{ fontSize: '14px' }}>Days</span>
              </div>
              <div style={{ fontSize: '11px', color: '#8b949e', marginTop: '6px' }}>
                Continuous 100% Pass
              </div>
            </div>

            {/* Total Observations */}
            <div
              style={{
                backgroundColor: '#161b22',
                border: '1px solid #30363d',
                borderRadius: '6px',
                padding: '14px',
                textAlign: 'center',
              }}
            >
              <div style={{ fontSize: '12px', color: '#8b949e', marginBottom: '6px' }}>
                Total Observations
              </div>
              <div
                data-testid="total-observations-count"
                style={{ fontSize: '28px', fontWeight: 700, color: '#f0f6fc' }}
              >
                {data.total_observations}
              </div>
              <div style={{ fontSize: '11px', color: '#8b949e', marginTop: '6px' }}>
                {data.pass_count} Pass | {data.fail_count} Fail
              </div>
            </div>
          </div>

          {/* Telemetry Ingestion Controls */}
          <div
            style={{
              backgroundColor: '#161b22',
              border: '1px solid #30363d',
              borderRadius: '6px',
              padding: '16px',
            }}
          >
            <h4 style={{ margin: '0 0 10px 0', fontSize: '14px', color: '#f0f6fc' }}>
              Simulate Continuous Telemetry Event
            </h4>
            <form
              onSubmit={handleQuickIngest}
              style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}
            >
              <label style={{ fontSize: '13px', color: '#8b949e' }}>
                Result:
                <select
                  value={ingestResult}
                  onChange={(e) => setIngestResult(e.target.value as 'PASS' | 'FAIL')}
                  style={{
                    marginLeft: '6px',
                    backgroundColor: '#0d1117',
                    border: '1px solid #30363d',
                    color: '#c9d1d9',
                    borderRadius: '4px',
                    padding: '4px 8px',
                  }}
                >
                  <option value="PASS">PASS</option>
                  <option value="FAIL">FAIL</option>
                </select>
              </label>

              <button
                type="submit"
                disabled={isIngesting}
                style={{
                  backgroundColor: ingestResult === 'PASS' ? '#238636' : '#da3633',
                  color: '#ffffff',
                  border: 'none',
                  borderRadius: '6px',
                  padding: '6px 14px',
                  fontSize: '13px',
                  fontWeight: 500,
                  cursor: isIngesting ? 'not-allowed' : 'pointer',
                }}
              >
                {isIngesting ? 'Submitting...' : `Log Telemetry Event (${ingestResult})`}
              </button>
            </form>

            {ingestSuccessMsg && (
              <p
                data-testid="ingest-success-badge"
                style={{ margin: '10px 0 0 0', fontSize: '12px', color: '#3fb950' }}
              >
                {ingestSuccessMsg}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
