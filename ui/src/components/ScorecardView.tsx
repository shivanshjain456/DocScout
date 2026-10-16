// DocScout Regulatory Risk Scorecard Generator (FEAT-040)
// Automated audit report generator grading policy documents against antipattern, deprecation, and standards catalogs.

import React, { useState } from 'react'

export interface ScorecardResponse {
  overall_grade: 'A' | 'B' | 'C' | 'D' | 'F'
  numerical_score: number
  antipatterns_count: number
  deprecations_count: number
  standards_coverage_score: number
  critical_risks: string[]
  remediation_timeline_days: number
  markdown_report: string
  pdf_content_base64?: string | null
  latency_ms: number
}

const SAMPLE_POLICY_DOSSIERS = [
  {
    label: 'Pristine Tier-1 Bank Compliance Dossier (Grade A Target)',
    orgType: 'scheduled_commercial_bank',
    text: `Standard Operating Procedure for Statutory Compliance - Zenith National Bank.
This comprehensive compliance policy establishes institutional adherence to the Reserve Bank of India
Master Direction on Know Your Customer (KYC) Direction, 2016 (Updated 2024), utilizing Central KYC
Records Registry (CKYCR) seeding and Video-based Customer Identification Process (V-CIP).
Capital adequacy is maintained strictly in accordance with Basel III Final Reforms CRE20 Standardised
Approach for Credit Risk, incorporating dynamic loan-to-value weighting and strict output floor metrics.
Information security governance adheres strictly to ISO/IEC 27001 and the RBI Cyber Security Framework,
enforcing continuous W3C distributed trace context propagation across all banking microservices and
mandatory 6-hour security incident notification. All credit underwriting utilizes metamorphic testing
and continuous model validation with monthly population stability index (PSI) recalibration. Continuous
evidence collection runs via automated policy-as-code telemetry with cryptographically signed audit trails.
Prevention of Money-laundering (Maintenance of Records) rules are verified at the amended 10% beneficial
ownership threshold across all corporate onboarding workflows.`,
  },
  {
    label: 'High-Risk Legacy Fintech Dossier (Grade F Warning)',
    orgType: 'fintech',
    text: `Internal Operations and Lending Technical Manual - QuickCredit Technologies.
Our digital onboarding verifies customer identity strictly relying on RBI KYC Guidelines 2002 under
DBOD.AML.BC.18/14.01.001/2002-03 circular references. Customer verification accepts manual physical photocopies
without central registry validation. For corporate borrower due diligence, our policy enforces the PMLA 25%
beneficial ownership threshold to identify controlling equity stakeholders.
In our software engineering lifecycle, we mandate 100% statement coverage as a release gate to approve code
for production deployment. Automated test suites execute with blind test retries in CI pipelines to eliminate
intermittent test flakiness. Our credit decisioning AI model was certified through independent model validation
conducted only prior to initial deployment as a one-time pre-launch sign-off. Telemetry is gathered by
instrumenting only the entry service and assuming traces will join up automatically. Blue-green traffic cutover
switches production traffic immediately without connection draining or in-flight session drainage.`,
  },
]

export const ScorecardView: React.FC = () => {
  const [orgType, setOrgType] = useState<string>('scheduled_commercial_bank')
  const [policyText, setPolicyText] = useState<string>(SAMPLE_POLICY_DOSSIERS[0].text)
  const [includePdf, setIncludePdf] = useState<boolean>(true)
  const [loading, setLoading] = useState<boolean>(false)
  const [scorecard, setScorecard] = useState<ScorecardResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleRunAudit = async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await fetch('/v1/compliance/scorecard', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': 'unit-test-key-aaaaaaaaaaaaaaaaaaaaaaaa',
        },
        body: JSON.stringify({
          policy_document_texts: [policyText],
          organization_type: orgType,
          include_pdf: includePdf,
        }),
      })

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}))
        throw new Error(errData.detail || `Audit failed with status ${response.status}`)
      }

      const data: ScorecardResponse = await response.json()
      setScorecard(data)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  const handleDownloadMarkdown = () => {
    if (!scorecard) return
    const blob = new Blob([scorecard.markdown_report], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `regulatory-scorecard-${orgType}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleDownloadPdf = () => {
    if (!scorecard?.pdf_content_base64) return
    const binary = atob(scorecard.pdf_content_base64)
    const array = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i++) {
      array[i] = binary.charCodeAt(i)
    }
    const blob = new Blob([array], { type: 'application/pdf' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `regulatory-scorecard-${orgType}.pdf`
    a.click()
    URL.revokeObjectURL(url)
  }

  const getGradeColor = (grade: string) => {
    switch (grade) {
      case 'A':
        return '#10b981'
      case 'B':
        return '#06b6d4'
      case 'C':
        return '#f59e0b'
      case 'D':
        return '#f97316'
      default:
        return '#ef4444'
    }
  }

  return (
    <div style={{ padding: '24px', fontFamily: 'system-ui, -apple-system, sans-serif', maxWidth: '1200px', margin: '0 auto' }}>
      <header style={{ marginBottom: '24px' }}>
        <h1 style={{ fontSize: '26px', fontWeight: 'bold', margin: '0 0 8px 0', color: '#1e293b' }}>
          Regulatory Risk Scorecard Generator
        </h1>
        <p style={{ color: '#64748b', margin: 0 }}>
          FEAT-040: Grade policy documents against canonical antipatterns, statutory deprecations, and mandatory standards.
        </p>
      </header>

      {/* Preset dossier selection */}
      <div style={{ marginBottom: '16px', display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
        {SAMPLE_POLICY_DOSSIERS.map((s, idx) => (
          <button
            key={idx}
            type="button"
            onClick={() => {
              setOrgType(s.orgType)
              setPolicyText(s.text)
            }}
            style={{
              padding: '6px 12px',
              fontSize: '13px',
              borderRadius: '6px',
              border: '1px solid #cbd5e1',
              backgroundColor: '#f8fafc',
              cursor: 'pointer',
            }}
          >
            Load: {s.label}
          </button>
        ))}
      </div>

      {/* Configuration Controls */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
        <div>
          <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, marginBottom: '6px', color: '#334155' }}>
            Regulated Entity Archetype:
          </label>
          <select
            value={orgType}
            onChange={(e) => setOrgType(e.target.value)}
            style={{
              width: '100%',
              padding: '8px 12px',
              borderRadius: '6px',
              border: '1px solid #cbd5e1',
              fontSize: '14px',
            }}
          >
            <option value="scheduled_commercial_bank">Scheduled Commercial Bank (RBI / Basel III)</option>
            <option value="nbfc">Non-Banking Financial Company (NBFC - SBR)</option>
            <option value="payment_aggregator">Payment Aggregator / PG (RBI CoFT & PAs)</option>
            <option value="fintech">Fintech Lending / Digital Platforms</option>
            <option value="general">General Regulated Enterprise</option>
          </select>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', marginTop: '24px' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '14px', cursor: 'pointer', color: '#334155' }}>
            <input
              type="checkbox"
              checked={includePdf}
              onChange={(e) => setIncludePdf(e.target.checked)}
              style={{ width: '16px', height: '16px' }}
            />
            Generate PDF/A Audit Archive Package
          </label>
        </div>
      </div>

      {/* Policy Text Area */}
      <div style={{ marginBottom: '16px' }}>
        <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, marginBottom: '6px', color: '#334155' }}>
          Policy Dossier Text (min. 100 words):
        </label>
        <textarea
          rows={8}
          value={policyText}
          onChange={(e) => setPolicyText(e.target.value)}
          placeholder="Paste internal policy, operational manual, or compliance text here..."
          style={{
            width: '100%',
            padding: '12px',
            borderRadius: '6px',
            border: '1px solid #cbd5e1',
            fontFamily: 'monospace',
            fontSize: '13px',
            resize: 'vertical',
            boxSizing: 'border-box',
          }}
        />
      </div>

      <div style={{ marginBottom: '24px' }}>
        <button
          type="button"
          onClick={handleRunAudit}
          disabled={loading || !policyText.trim()}
          style={{
            padding: '10px 20px',
            backgroundColor: '#2563eb',
            color: '#fff',
            border: 'none',
            borderRadius: '6px',
            fontSize: '14px',
            fontWeight: 600,
            cursor: loading ? 'not-allowed' : 'pointer',
            opacity: loading ? 0.7 : 1,
          }}
        >
          {loading ? 'Evaluating Policy Dossier against Regulatory Graph...' : 'Generate Executive Risk Scorecard'}
        </button>
      </div>

      {error && (
        <div style={{ padding: '12px 16px', backgroundColor: '#fee2e2', color: '#991b1b', borderRadius: '6px', marginBottom: '20px' }}>
          <strong>Audit Error:</strong> {error}
        </div>
      )}

      {/* Scorecard Results Dashboard */}
      {scorecard && (
        <div style={{ border: '1px solid #e2e8f0', borderRadius: '8px', padding: '24px', backgroundColor: '#ffffff', boxShadow: '0 1px 3px rgba(0,0,0,0.05)' }}>
          {/* Executive Grade Header */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #f1f5f9', paddingBottom: '20px', marginBottom: '20px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
              <div
                style={{
                  width: '72px',
                  height: '72px',
                  borderRadius: '12px',
                  backgroundColor: getGradeColor(scorecard.overall_grade),
                  color: '#ffffff',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '36px',
                  fontWeight: 900,
                }}
              >
                {scorecard.overall_grade}
              </div>
              <div>
                <h2 style={{ margin: '0 0 4px 0', fontSize: '20px', color: '#0f172a' }}>
                  Institutional Compliance Grade: {scorecard.overall_grade}
                </h2>
                <div style={{ color: '#64748b', fontSize: '14px' }}>
                  Numerical Score: <strong>{scorecard.numerical_score} / 100.0</strong> | Target Remediation: <strong>{scorecard.remediation_timeline_days} Days</strong> | Evaluation SLA: <strong>{scorecard.latency_ms} ms</strong>
                </div>
              </div>
            </div>

            <div style={{ display: 'flex', gap: '10px' }}>
              <button
                type="button"
                onClick={handleDownloadMarkdown}
                style={{
                  padding: '8px 14px',
                  borderRadius: '6px',
                  border: '1px solid #cbd5e1',
                  backgroundColor: '#f8fafc',
                  fontSize: '13px',
                  cursor: 'pointer',
                  fontWeight: 500,
                }}
              >
                Export Markdown
              </button>
              {scorecard.pdf_content_base64 && (
                <button
                  type="button"
                  onClick={handleDownloadPdf}
                  style={{
                    padding: '8px 14px',
                    borderRadius: '6px',
                    border: '1px solid #2563eb',
                    backgroundColor: '#eff6ff',
                    color: '#1d4ed8',
                    fontSize: '13px',
                    cursor: 'pointer',
                    fontWeight: 600,
                  }}
                >
                  Download PDF/A Archive
                </button>
              )}
            </div>
          </div>

          {/* Metric Sub-cards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px', marginBottom: '24px' }}>
            <div style={{ padding: '16px', borderRadius: '8px', backgroundColor: '#f8fafc', border: '1px solid #e2e8f0' }}>
              <div style={{ fontSize: '13px', color: '#64748b' }}>Technical Antipatterns</div>
              <div style={{ fontSize: '24px', fontWeight: 700, color: '#0f172a', margin: '4px 0' }}>
                {scorecard.antipatterns_count}
              </div>
              <div style={{ fontSize: '12px', color: '#64748b' }}>Detected design failure modes</div>
            </div>

            <div style={{ padding: '16px', borderRadius: '8px', backgroundColor: '#f8fafc', border: '1px solid #e2e8f0' }}>
              <div style={{ fontSize: '13px', color: '#64748b' }}>Statutory Deprecations</div>
              <div style={{ fontSize: '24px', fontWeight: 700, color: '#0f172a', margin: '4px 0' }}>
                {scorecard.deprecations_count}
              </div>
              <div style={{ fontSize: '12px', color: '#64748b' }}>Repealed circular citations</div>
            </div>

            <div style={{ padding: '16px', borderRadius: '8px', backgroundColor: '#f8fafc', border: '1px solid #e2e8f0' }}>
              <div style={{ fontSize: '13px', color: '#64748b' }}>Mandatory Standards Coverage</div>
              <div style={{ fontSize: '24px', fontWeight: 700, color: '#0f172a', margin: '4px 0' }}>
                {scorecard.standards_coverage_score.toFixed(0)}%
              </div>
              <div style={{ fontSize: '12px', color: '#64748b' }}>Required statutory frameworks cited</div>
            </div>
          </div>

          {/* Critical Risks Callout */}
          {scorecard.critical_risks.length > 0 && (
            <div style={{ padding: '16px', borderRadius: '8px', backgroundColor: '#fef2f2', border: '1px solid #fecaca', marginBottom: '24px' }}>
              <h3 style={{ margin: '0 0 8px 0', fontSize: '15px', color: '#991b1b', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span>[!]</span> Critical Regulatory Risks (Immediate Escalation Required)
              </h3>
              <ul style={{ margin: 0, paddingLeft: '20px', color: '#7f1d1d', fontSize: '13px' }}>
                {scorecard.critical_risks.map((risk, idx) => (
                  <li key={idx} style={{ marginBottom: '4px' }}>
                    {risk}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Markdown Preview */}
          <div>
            <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '8px', color: '#1e293b' }}>
              Scorecard Report Preview
            </h3>
            <pre
              style={{
                backgroundColor: '#f8fafc',
                border: '1px solid #e2e8f0',
                borderRadius: '6px',
                padding: '16px',
                fontSize: '12px',
                fontFamily: 'monospace',
                overflowX: 'auto',
                whiteSpace: 'pre-wrap',
                maxHeight: '400px',
                color: '#334155',
              }}
            >
              {scorecard.markdown_report}
            </pre>
          </div>
        </div>
      )}
    </div>
  )
}

export default ScorecardView
