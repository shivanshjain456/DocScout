import React, { useState } from 'react'

export type VendorType = 'CLOUD' | 'SAAS' | 'PAYMENT_SWITCH' | 'DATACENTER'
export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

export interface MissingClause {
  clause_name: string
  statutory_requirement: string
  rbi_circular_citation: string
  risk_level: RiskLevel
  remediation_guidance: string
}

export interface DetectedClause {
  clause_name: string
  confidence: number
  matched_snippet: string
}

export interface VendorRiskReportData {
  vendor_name: string | null
  vendor_type: VendorType
  compliance_score: number
  risk_rating: RiskLevel
  mandatory_clauses_present: string[]
  missing_clauses: MissingClause[]
  detected_clauses: DetectedClause[]
  contract_char_count: number
  audit_timestamp: string
  strict_localization_enforced: boolean
}

export interface VendorRiskAuditViewProps {
  apiBaseUrl?: string
  apiKey?: string
  className?: string
  onAuditComplete?: (report: VendorRiskReportData) => void
}

export const VendorRiskAuditView: React.FC<VendorRiskAuditViewProps> = ({
  apiBaseUrl = '',
  apiKey = '',
  className = '',
  onAuditComplete,
}) => {
  const [contractText, setContractText] = useState<string>('')
  const [vendorType, setVendorType] = useState<VendorType>('CLOUD')
  const [vendorName, setVendorName] = useState<string>('')
  const [strictLocalization, setStrictLocalization] = useState<boolean>(true)
  const [loading, setLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [report, setReport] = useState<VendorRiskReportData | null>(null)
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null)

  const handleAudit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (contractText.trim().length < 100) {
      setError('Contract text must be at least 100 characters.')
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
        contract_text: contractText,
        vendor_type: vendorType,
        vendor_name: vendorName.trim() || null,
        strict_localization: strictLocalization,
      }

      const res = await fetch(`${apiBaseUrl}/v1/compliance/vendor-audit`, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload),
      })

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}))
        throw new Error(errJson.detail || `Server returned error ${res.status}`)
      }

      const json: VendorRiskReportData = await res.json()
      setReport(json)
      if (onAuditComplete) {
        onAuditComplete(json)
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to audit vendor contract'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  const copyRemediation = (text: string, index: number) => {
    navigator.clipboard.writeText(text)
    setCopiedIndex(index)
    setTimeout(() => setCopiedIndex(null), 2000)
  }

  const getRiskColor = (risk: RiskLevel) => {
    switch (risk) {
      case 'LOW':
        return '#3fb950'
      case 'MEDIUM':
        return '#d29922'
      case 'HIGH':
        return '#db6d28'
      case 'CRITICAL':
        return '#f85149'
      default:
        return '#8b949e'
    }
  }

  return (
    <div
      role="region"
      aria-label="Third-Party Vendor Risk Assessment Engine"
      className={`vendor-risk-view ${className}`}
      style={{
        backgroundColor: '#0d1117',
        border: '1px solid #30363d',
        borderRadius: '8px',
        padding: '24px',
        color: '#c9d1d9',
        fontFamily: 'system-ui, -apple-system, sans-serif',
      }}
    >
      <div style={{ borderBottom: '1px solid #21262d', paddingBottom: '14px', marginBottom: '18px' }}>
        <h2 id="vendor-risk-title" style={{ margin: 0, fontSize: '20px', fontWeight: 600, color: '#f0f6fc' }}>
          Third-Party Vendor Risk Assessment Engine
        </h2>
        <p style={{ margin: '6px 0 0 0', fontSize: '13px', color: '#8b949e' }}>
          Statutory Contract Evaluation under RBI IT Outsourcing Guidelines & SEBI Cloud Security Framework
        </p>
      </div>

      <form onSubmit={handleAudit} style={{ marginBottom: '24px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px', marginBottom: '16px' }}>
          <div>
            <label htmlFor="vendor-name-input" style={{ display: 'block', fontSize: '13px', marginBottom: '6px', color: '#c9d1d9' }}>
              Vendor Legal Name:
            </label>
            <input
              id="vendor-name-input"
              type="text"
              placeholder="e.g. Acme Cloud Services Private Limited"
              value={vendorName}
              onChange={(e) => setVendorName(e.target.value)}
              style={{
                width: '100%',
                backgroundColor: '#161b22',
                border: '1px solid #30363d',
                color: '#c9d1d9',
                borderRadius: '6px',
                padding: '8px 12px',
                fontSize: '13px',
                boxSizing: 'border-box',
              }}
            />
          </div>

          <div>
            <label htmlFor="vendor-type-select" style={{ display: 'block', fontSize: '13px', marginBottom: '6px', color: '#c9d1d9' }}>
              Vendor Classification:
            </label>
            <select
              id="vendor-type-select"
              value={vendorType}
              onChange={(e) => setVendorType(e.target.value as VendorType)}
              style={{
                width: '100%',
                backgroundColor: '#161b22',
                border: '1px solid #30363d',
                color: '#c9d1d9',
                borderRadius: '6px',
                padding: '8px 12px',
                fontSize: '13px',
                boxSizing: 'border-box',
              }}
            >
              <option value="CLOUD">Cloud Infrastructure Provider (IaaS/PaaS)</option>
              <option value="SAAS">SaaS & Application Software Provider</option>
              <option value="PAYMENT_SWITCH">Payment Switch & Card Processing Service</option>
              <option value="DATACENTER">Datacenter & Colocation Hosting Provider</option>
            </select>
          </div>
        </div>

        <div style={{ marginBottom: '16px' }}>
          <label htmlFor="contract-text-area" style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', marginBottom: '6px', color: '#c9d1d9' }}>
            <span>Vendor Agreement / Master Services Agreement (MSA) Text:</span>
            <span style={{ color: '#8b949e', fontSize: '12px' }}>{contractText.length} / 150,000 chars</span>
          </label>
          <textarea
            id="contract-text-area"
            rows={8}
            placeholder="Paste vendor agreement clauses or Master Services Agreement text here..."
            value={contractText}
            onChange={(e) => setContractText(e.target.value)}
            style={{
              width: '100%',
              backgroundColor: '#161b22',
              border: '1px solid #30363d',
              color: '#c9d1d9',
              borderRadius: '6px',
              padding: '12px',
              fontSize: '13px',
              fontFamily: 'monospace',
              boxSizing: 'border-box',
              resize: 'vertical',
            }}
          />
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: '#c9d1d9', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={strictLocalization}
              onChange={(e) => setStrictLocalization(e.target.checked)}
              style={{ accentColor: '#238636' }}
            />
            Enforce Strict Indian Data Localization (RBI/SEBI Onshore Mandate)
          </label>

          <button
            type="submit"
            disabled={loading || contractText.trim().length < 100}
            style={{
              backgroundColor: '#238636',
              color: '#ffffff',
              border: 'none',
              borderRadius: '6px',
              padding: '8px 18px',
              fontSize: '13px',
              fontWeight: 600,
              cursor: loading || contractText.trim().length < 100 ? 'not-allowed' : 'pointer',
              opacity: loading || contractText.trim().length < 100 ? 0.6 : 1.0,
            }}
          >
            {loading ? 'Evaluating Contract...' : 'Run Regulatory Audit'}
          </button>
        </div>
      </form>

      {error && (
        <div
          role="alert"
          style={{
            backgroundColor: 'rgba(248, 81, 73, 0.15)',
            border: '1px solid #f85149',
            borderRadius: '6px',
            padding: '12px 16px',
            marginBottom: '20px',
            color: '#ff7b72',
            fontSize: '13px',
          }}
        >
          {error}
        </div>
      )}

      {report && (
        <div data-testid="vendor-risk-results" style={{ borderTop: '1px solid #21262d', paddingTop: '20px' }}>
          {/* Summary Scorecards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '14px', marginBottom: '24px' }}>
            <div style={{ backgroundColor: '#161b22', border: '1px solid #30363d', borderRadius: '6px', padding: '16px', textAlign: 'center' }}>
              <div style={{ fontSize: '12px', color: '#8b949e', marginBottom: '6px' }}>Compliance Score</div>
              <div data-testid="compliance-score-gauge" style={{ fontSize: '32px', fontWeight: 700, color: getRiskColor(report.risk_rating) }}>
                {report.compliance_score}%
              </div>
            </div>

            <div style={{ backgroundColor: '#161b22', border: '1px solid #30363d', borderRadius: '6px', padding: '16px', textAlign: 'center' }}>
              <div style={{ fontSize: '12px', color: '#8b949e', marginBottom: '6px' }}>Overall Risk Rating</div>
              <span
                data-testid="risk-rating-badge"
                style={{
                  display: 'inline-block',
                  fontSize: '18px',
                  fontWeight: 700,
                  padding: '4px 14px',
                  borderRadius: '20px',
                  backgroundColor: `${getRiskColor(report.risk_rating)}22`,
                  color: getRiskColor(report.risk_rating),
                  border: `1px solid ${getRiskColor(report.risk_rating)}`,
                }}
              >
                {report.risk_rating}
              </span>
            </div>

            <div style={{ backgroundColor: '#161b22', border: '1px solid #30363d', borderRadius: '6px', padding: '16px', textAlign: 'center' }}>
              <div style={{ fontSize: '12px', color: '#8b949e', marginBottom: '6px' }}>Mandatory Clauses</div>
              <div data-testid="clauses-ratio-count" style={{ fontSize: '24px', fontWeight: 700, color: '#f0f6fc' }}>
                {report.mandatory_clauses_present.length} Present / {report.missing_clauses.length} Missing
              </div>
            </div>
          </div>

          {/* Missing Clauses Section */}
          {report.missing_clauses.length > 0 ? (
            <div style={{ marginBottom: '24px' }}>
              <h3 style={{ fontSize: '16px', fontWeight: 600, color: '#f85149', marginBottom: '12px' }}>
                Flagged Statutory Deficiencies ({report.missing_clauses.length})
              </h3>
              <div data-testid="missing-clauses-list" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {report.missing_clauses.map((clause, idx) => (
                  <div
                    key={clause.clause_name}
                    data-testid={`missing-clause-item-${idx}`}
                    style={{
                      backgroundColor: '#161b22',
                      border: '1px solid #30363d',
                      borderLeft: `4px solid ${getRiskColor(clause.risk_level)}`,
                      borderRadius: '6px',
                      padding: '16px',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                      <strong style={{ fontSize: '14px', color: '#f0f6fc' }}>{clause.clause_name}</strong>
                      <span
                        style={{
                          fontSize: '11px',
                          fontWeight: 600,
                          padding: '2px 8px',
                          borderRadius: '10px',
                          backgroundColor: `${getRiskColor(clause.risk_level)}25`,
                          color: getRiskColor(clause.risk_level),
                        }}
                      >
                        {clause.risk_level}
                      </span>
                    </div>

                    <p style={{ margin: '4px 0', fontSize: '12px', color: '#c9d1d9' }}>
                      <strong>Statutory Mandate:</strong> {clause.statutory_requirement}
                    </p>
                    <p style={{ margin: '4px 0 10px 0', fontSize: '11px', color: '#58a6ff' }}>
                      <strong>Regulatory Authority Citation:</strong> {clause.rbi_circular_citation}
                    </p>

                    <div style={{ backgroundColor: '#0d1117', border: '1px solid #21262d', borderRadius: '4px', padding: '10px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                        <span style={{ fontSize: '11px', fontWeight: 600, color: '#8b949e' }}>Prescriptive Amendment Clause:</span>
                        <button
                          type="button"
                          onClick={() => copyRemediation(clause.remediation_guidance, idx)}
                          style={{
                            backgroundColor: 'transparent',
                            border: '1px solid #30363d',
                            color: copiedIndex === idx ? '#3fb950' : '#58a6ff',
                            borderRadius: '4px',
                            padding: '2px 8px',
                            fontSize: '11px',
                            cursor: 'pointer',
                          }}
                        >
                          {copiedIndex === idx ? 'Copied!' : 'Copy Amendment'}
                        </button>
                      </div>
                      <code style={{ fontSize: '12px', color: '#7ee787', whiteSpace: 'pre-wrap' }}>
                        {clause.remediation_guidance}
                      </code>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div
              data-testid="no-deficiencies-banner"
              style={{
                backgroundColor: 'rgba(63, 185, 80, 0.15)',
                border: '1px solid #3fb950',
                borderRadius: '6px',
                padding: '16px',
                color: '#3fb950',
                fontSize: '14px',
                fontWeight: 600,
                textAlign: 'center',
                marginBottom: '20px',
              }}
            >
              All mandatory RBI Outsourcing and SEBI Cloud statutory clauses are satisfied.
            </div>
          )}
        </div>
      )}
    </div>
  )
}
