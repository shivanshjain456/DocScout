// DocScout Enterprise Compliance Debt Register (FEAT-038)
// Real-time tracking of compliance exceptions, deprecated procedures, and remediation target dates.

import React, { useState } from 'react'

export interface ComplianceDebtItem {
  id: string
  tenant_id: string
  practice_name: string
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'
  status: 'OPEN' | 'IN_REMEDIATION' | 'RESOLVED'
  owner_email: string
  target_date: string
  justification: string
  deprecation_id?: string | null
  antipattern_id?: string | null
  created_at: string
  updated_at: string
}

export interface InstitutionalDebtScore {
  tenant_id: string
  total_items: number
  open_items: number
  in_remediation_items: number
  resolved_items: number
  debt_score: number
  severity_breakdown: Record<string, number>
}

export interface AuditEntry {
  id: string
  debt_item_id: string
  tenant_id: string
  previous_status: string | null
  new_status: string
  actor_email: string
  transition_notes?: string | null
  timestamp: string
}

const SEVERITY_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  CRITICAL: { bg: '#450a0a', text: '#f87171', border: '#b91c1c' },
  HIGH: { bg: '#451a03', text: '#fb923c', border: '#c2410c' },
  MEDIUM: { bg: '#172554', text: '#60a5fa', border: '#1d4ed8' },
  LOW: { bg: '#1e293b', text: '#94a3b8', border: '#475569' },
}

const STATUS_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  OPEN: { bg: '#422006', text: '#facc15', border: '#ca8a04' },
  IN_REMEDIATION: { bg: '#2e1065', text: '#c084fc', border: '#7e22ce' },
  RESOLVED: { bg: '#052e16', text: '#4ade80', border: '#15803d' },
}

const INITIAL_MOCK_ITEMS: ComplianceDebtItem[] = [
  {
    id: 'e100-debt-001',
    tenant_id: 'default',
    practice_name: 'SHA-1 Algorithm in Inter-Bank Messaging Gateway',
    severity: 'CRITICAL',
    status: 'IN_REMEDIATION',
    owner_email: 'ciso@bankgroup.in',
    target_date: '2026-12-15',
    justification: 'Legacy ISO 8583 switch requires firmware upgrade before SHA-256 certificate migration.',
    deprecation_id: 'DEP-CRYPTO-SHA1',
    antipattern_id: 'ANTI-WEAK-CIPHER',
    created_at: '2026-09-01T10:00:00Z',
    updated_at: '2026-10-10T14:30:00Z',
  },
  {
    id: 'e100-debt-002',
    tenant_id: 'default',
    practice_name: 'Plaintext Customer PAN Storage in Staging Enclave',
    severity: 'HIGH',
    status: 'OPEN',
    owner_email: 'compliance.lead@bankgroup.in',
    target_date: '2026-11-30',
    justification: 'Cardholder PAN masking pipeline under active deployment across staging database pods.',
    deprecation_id: 'DEP-PLAINTEXT-PAN',
    antipattern_id: 'ANTI-UNMASKED-PII',
    created_at: '2026-09-15T11:00:00Z',
    updated_at: '2026-09-15T11:00:00Z',
  },
  {
    id: 'e100-debt-003',
    tenant_id: 'default',
    practice_name: 'Single Region High-Availability Setup for Core Payment Switch',
    severity: 'MEDIUM',
    status: 'RESOLVED',
    owner_email: 'infra.architect@bankgroup.in',
    target_date: '2026-10-01',
    justification: 'Multi-region synchronous active-active replication validated across Mumbai and Hyderabad datacenters.',
    antipattern_id: 'ANTI-SINGLE-DC-SPOF',
    created_at: '2026-08-01T09:00:00Z',
    updated_at: '2026-09-28T16:45:00Z',
  },
]

export const DebtRegisterView: React.FC = () => {
  const [items, setItems] = useState<ComplianceDebtItem[]>(INITIAL_MOCK_ITEMS)
  const [filterStatus, setFilterStatus] = useState<string>('ALL')
  const [filterSeverity, setFilterSeverity] = useState<string>('ALL')
  const [isCreateOpen, setIsCreateOpen] = useState<boolean>(false)

  // Form state

  const [practiceName, setPracticeName] = useState('')
  const [ownerEmail, setOwnerEmail] = useState('')
  const [targetDate, setTargetDate] = useState('')
  const [justification, setJustification] = useState('')
  const [severity, setSeverity] = useState<'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'>('HIGH')
  const [deprecationId, setDeprecationId] = useState('')
  const [antipatternId, setAntipatternId] = useState('')
  const [formError, setFormError] = useState<string | null>(null)

  // Score calculation
  const total = items.length
  const openCount = items.filter((i) => i.status === 'OPEN').length
  const inRemedCount = items.filter((i) => i.status === 'IN_REMEDIATION').length
  const resolvedCount = items.filter((i) => i.status === 'RESOLVED').length
  const debtScore = items.reduce((acc, it) => {
    const weights: Record<string, number> = { CRITICAL: 10, HIGH: 5, MEDIUM: 2, LOW: 1 }
    const mults: Record<string, number> = { OPEN: 1.0, IN_REMEDIATION: 0.5, RESOLVED: 0.0 }
    return acc + (weights[it.severity] || 1) * (mults[it.status] || 0)
  }, 0)

  const handleCreateSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setFormError(null)

    if (!practiceName.trim()) {
      setFormError('Practice name is required.')
      return
    }
    if (!ownerEmail.includes('@') || !ownerEmail.includes('.')) {
      setFormError('Please enter a valid owner email address.')
      return
    }
    if (!targetDate) {
      setFormError('Target date is required.')
      return
    }
    if (new Date(targetDate) <= new Date()) {
      setFormError('Target date must be in the future.')
      return
    }
    if (justification.trim().length < 20) {
      setFormError('Justification must be at least 20 characters long.')
      return
    }

    const newItem: ComplianceDebtItem = {
      id: `debt-${Date.now()}`,
      tenant_id: 'default',
      practice_name: practiceName.trim(),
      severity,
      status: 'OPEN',
      owner_email: ownerEmail.trim(),
      target_date: targetDate,
      justification: justification.trim(),
      deprecation_id: deprecationId.trim() || null,
      antipattern_id: antipatternId.trim() || null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }

    setItems([newItem, ...items])
    setIsCreateOpen(false)
    setPracticeName('')
    setOwnerEmail('')
    setTargetDate('')
    setJustification('')
    setDeprecationId('')
    setAntipatternId('')
  }

  const handleStatusTransition = (itemId: string, newStatus: 'OPEN' | 'IN_REMEDIATION' | 'RESOLVED') => {
    setItems(
      items.map((it) => {
        if (it.id === itemId) {
          return {
            ...it,
            status: newStatus,
            updated_at: new Date().toISOString(),
          }
        }
        return it
      })
    )
  }

  const filteredItems = items.filter((it) => {
    if (filterStatus !== 'ALL' && it.status !== filterStatus) return false
    if (filterSeverity !== 'ALL' && it.severity !== filterSeverity) return false
    return true
  })

  return (
    <div style={{ padding: '24px', backgroundColor: '#090d16', minHeight: '100vh', color: '#f1f5f9', fontFamily: 'system-ui, sans-serif' }}>
      {/* Header & Scoreboard */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: '24px', fontWeight: 700, color: '#38bdf8' }}>
            Enterprise Compliance Debt Register
          </h1>
          <p style={{ margin: '4px 0 0', color: '#94a3b8', fontSize: '14px' }}>
            Multi-tenant exception tracking, deprecation lineage, and statutory audit obligations (FEAT-038).
          </p>
        </div>
        <button
          onClick={() => setIsCreateOpen(true)}
          style={{
            backgroundColor: '#0284c7',
            color: '#fff',
            border: 'none',
            borderRadius: '6px',
            padding: '10px 18px',
            fontSize: '14px',
            fontWeight: 600,
            cursor: 'pointer',
            boxShadow: '0 2px 4px rgba(0,0,0,0.4)',
          }}
        >
          + Log Compliance Debt Item
        </button>
      </div>

      {/* KPI Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '24px' }}>
        <div style={{ backgroundColor: '#131b2e', padding: '16px', borderRadius: '8px', border: '1px solid #1e293b' }}>
          <div style={{ color: '#94a3b8', fontSize: '13px', fontWeight: 600 }}>INSTITUTIONAL DEBT SCORE</div>
          <div style={{ fontSize: '28px', fontWeight: 700, color: '#f59e0b', marginTop: '4px' }}>{debtScore.toFixed(1)}</div>
          <div style={{ fontSize: '12px', color: '#64748b', marginTop: '2px' }}>Weighted risk index</div>
        </div>
        <div style={{ backgroundColor: '#131b2e', padding: '16px', borderRadius: '8px', border: '1px solid #1e293b' }}>
          <div style={{ color: '#94a3b8', fontSize: '13px', fontWeight: 600 }}>TOTAL REGISTERED</div>
          <div style={{ fontSize: '28px', fontWeight: 700, color: '#e2e8f0', marginTop: '4px' }}>{total}</div>
          <div style={{ fontSize: '12px', color: '#64748b', marginTop: '2px' }}>Exceptions across tenant</div>
        </div>
        <div style={{ backgroundColor: '#131b2e', padding: '16px', borderRadius: '8px', border: '1px solid #1e293b' }}>
          <div style={{ color: '#94a3b8', fontSize: '13px', fontWeight: 600 }}>OPEN ITEMS</div>
          <div style={{ fontSize: '28px', fontWeight: 700, color: '#f87171', marginTop: '4px' }}>{openCount}</div>
          <div style={{ fontSize: '12px', color: '#64748b', marginTop: '2px' }}>Requires immediate triage</div>
        </div>
        <div style={{ backgroundColor: '#131b2e', padding: '16px', borderRadius: '8px', border: '1px solid #1e293b' }}>
          <div style={{ color: '#94a3b8', fontSize: '13px', fontWeight: 600 }}>IN REMEDIATION</div>
          <div style={{ fontSize: '28px', fontWeight: 700, color: '#c084fc', marginTop: '4px' }}>{inRemedCount}</div>
          <div style={{ fontSize: '12px', color: '#64748b', marginTop: '2px' }}>Active engineering sprint</div>
        </div>
        <div style={{ backgroundColor: '#131b2e', padding: '16px', borderRadius: '8px', border: '1px solid #1e293b' }}>
          <div style={{ color: '#94a3b8', fontSize: '13px', fontWeight: 600 }}>RESOLVED</div>
          <div style={{ fontSize: '28px', fontWeight: 700, color: '#4ade80', marginTop: '4px' }}>{resolvedCount}</div>
          <div style={{ fontSize: '12px', color: '#64748b', marginTop: '2px' }}>Audit closed & verified</div>
        </div>
      </div>

      {/* Filter Toolbar */}
      <div style={{ display: 'flex', gap: '12px', marginBottom: '16px', alignItems: 'center' }}>
        <span style={{ fontSize: '13px', color: '#94a3b8', fontWeight: 600 }}>Filter Status:</span>
        {['ALL', 'OPEN', 'IN_REMEDIATION', 'RESOLVED'].map((st) => (
          <button
            key={st}
            onClick={() => setFilterStatus(st)}
            style={{
              padding: '6px 12px',
              fontSize: '12px',
              fontWeight: 600,
              borderRadius: '4px',
              border: '1px solid',
              borderColor: filterStatus === st ? '#38bdf8' : '#334155',
              backgroundColor: filterStatus === st ? '#0369a1' : '#1e293b',
              color: filterStatus === st ? '#fff' : '#cbd5e1',
              cursor: 'pointer',
            }}
          >
            {st}
          </button>
        ))}

        <span style={{ fontSize: '13px', color: '#94a3b8', fontWeight: 600, marginLeft: '16px' }}>Severity:</span>
        {['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].map((sev) => (
          <button
            key={sev}
            onClick={() => setFilterSeverity(sev)}
            style={{
              padding: '6px 12px',
              fontSize: '12px',
              fontWeight: 600,
              borderRadius: '4px',
              border: '1px solid',
              borderColor: filterSeverity === sev ? '#f59e0b' : '#334155',
              backgroundColor: filterSeverity === sev ? '#78350f' : '#1e293b',
              color: filterSeverity === sev ? '#fff' : '#cbd5e1',
              cursor: 'pointer',
            }}
          >
            {sev}
          </button>
        ))}
      </div>

      {/* Debt Register Items Table */}
      <div style={{ backgroundColor: '#111827', borderRadius: '8px', border: '1px solid #1f2937', overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '14px' }}>
          <thead>
            <tr style={{ backgroundColor: '#1f2937', color: '#9ca3af', borderBottom: '1px solid #374151' }}>
              <th style={{ padding: '12px 16px' }}>Practice / Exception</th>
              <th style={{ padding: '12px 16px' }}>Severity</th>
              <th style={{ padding: '12px 16px' }}>Status</th>
              <th style={{ padding: '12px 16px' }}>Target Date</th>
              <th style={{ padding: '12px 16px' }}>Owner</th>
              <th style={{ padding: '12px 16px' }}>Linked Reg Entities</th>
              <th style={{ padding: '12px 16px', textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredItems.length === 0 ? (
              <tr>
                <td colSpan={7} style={{ padding: '32px', textAlign: 'center', color: '#64748b' }}>
                  No compliance debt items matching selected filters.
                </td>
              </tr>
            ) : (
              filteredItems.map((item) => {
                const sevColor = SEVERITY_COLORS[item.severity] || SEVERITY_COLORS.MEDIUM
                const stColor = STATUS_COLORS[item.status] || STATUS_COLORS.OPEN
                const isOverdue = new Date(item.target_date) < new Date() && item.status !== 'RESOLVED'

                return (
                  <tr key={item.id} style={{ borderBottom: '1px solid #1f2937' }}>
                    <td style={{ padding: '14px 16px', maxWidth: '320px' }}>
                      <div style={{ fontWeight: 600, color: '#f8fafc' }}>{item.practice_name}</div>
                      <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '4px', lineHeight: 1.4 }}>
                        {item.justification}
                      </div>
                    </td>
                    <td style={{ padding: '14px 16px' }}>
                      <span
                        style={{
                          backgroundColor: sevColor.bg,
                          color: sevColor.text,
                          border: `1px solid ${sevColor.border}`,
                          padding: '3px 8px',
                          borderRadius: '4px',
                          fontSize: '11px',
                          fontWeight: 700,
                        }}
                      >
                        {item.severity}
                      </span>
                    </td>
                    <td style={{ padding: '14px 16px' }}>
                      <span
                        style={{
                          backgroundColor: stColor.bg,
                          color: stColor.text,
                          border: `1px solid ${stColor.border}`,
                          padding: '3px 8px',
                          borderRadius: '4px',
                          fontSize: '11px',
                          fontWeight: 700,
                        }}
                      >
                        {item.status}
                      </span>
                    </td>
                    <td style={{ padding: '14px 16px', whiteSpace: 'nowrap' }}>
                      <div style={{ color: isOverdue ? '#f87171' : '#e2e8f0', fontWeight: isOverdue ? 700 : 500 }}>
                        {item.target_date}
                      </div>
                      {isOverdue && (
                        <div style={{ fontSize: '10px', color: '#ef4444', fontWeight: 600 }}>OVERDUE</div>
                      )}
                    </td>
                    <td style={{ padding: '14px 16px', color: '#cbd5e1', fontSize: '13px' }}>
                      {item.owner_email}
                    </td>
                    <td style={{ padding: '14px 16px' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        {item.deprecation_id && (
                          <span style={{ fontSize: '11px', color: '#38bdf8', backgroundColor: '#082f49', padding: '2px 6px', borderRadius: '4px' }}>
                            Deprec: {item.deprecation_id}
                          </span>
                        )}
                        {item.antipattern_id && (
                          <span style={{ fontSize: '11px', color: '#fb923c', backgroundColor: '#431407', padding: '2px 6px', borderRadius: '4px' }}>
                            Antipattern: {item.antipattern_id}
                          </span>
                        )}
                        {!item.deprecation_id && !item.antipattern_id && (
                          <span style={{ fontSize: '11px', color: '#64748b' }}>None</span>
                        )}
                      </div>
                    </td>
                    <td style={{ padding: '14px 16px', textAlign: 'right' }}>
                      <div style={{ display: 'flex', gap: '6px', justifyContent: 'flex-end' }}>
                        {item.status === 'OPEN' && (
                          <button
                            onClick={() => handleStatusTransition(item.id, 'IN_REMEDIATION')}
                            style={{
                              backgroundColor: '#7c3aed',
                              color: '#fff',
                              border: 'none',
                              borderRadius: '4px',
                              padding: '5px 10px',
                              fontSize: '12px',
                              cursor: 'pointer',
                            }}
                          >
                            Remediate
                          </button>
                        )}
                        {item.status === 'IN_REMEDIATION' && (
                          <button
                            onClick={() => handleStatusTransition(item.id, 'RESOLVED')}
                            style={{
                              backgroundColor: '#16a34a',
                              color: '#fff',
                              border: 'none',
                              borderRadius: '4px',
                              padding: '5px 10px',
                              fontSize: '12px',
                              cursor: 'pointer',
                            }}
                          >
                            Close
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Modal for Creating Compliance Debt */}
      {isCreateOpen && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0,0,0,0.75)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
        >
          <div
            style={{
              backgroundColor: '#1e293b',
              padding: '28px',
              borderRadius: '8px',
              width: '520px',
              maxWidth: '90%',
              border: '1px solid #334155',
            }}
          >
            <h2 style={{ margin: '0 0 16px', fontSize: '18px', color: '#38bdf8' }}>
              Register Institutional Compliance Exception
            </h2>
            {formError && (
              <div
                style={{
                  backgroundColor: '#450a0a',
                  color: '#f87171',
                  border: '1px solid #b91c1c',
                  padding: '8px 12px',
                  borderRadius: '4px',
                  fontSize: '13px',
                  marginBottom: '16px',
                }}
              >
                {formError}
              </div>
            )}
            <form onSubmit={handleCreateSubmit}>
              <div style={{ marginBottom: '14px' }}>
                <label style={{ display: 'block', fontSize: '12px', color: '#94a3b8', marginBottom: '4px' }}>
                  Practice / Procedure Name
                </label>
                <input
                  type="text"
                  value={practiceName}
                  onChange={(e) => setPracticeName(e.target.value)}
                  placeholder="e.g. Weak cipher suite in payment gateway"
                  style={{ width: '100%', padding: '8px', backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: '4px', color: '#fff' }}
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '14px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '12px', color: '#94a3b8', marginBottom: '4px' }}>
                    Severity
                  </label>
                  <select
                    value={severity}
                    onChange={(e) => setSeverity(e.target.value as any)}
                    style={{ width: '100%', padding: '8px', backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: '4px', color: '#fff' }}
                  >
                    <option value="CRITICAL">CRITICAL</option>
                    <option value="HIGH">HIGH</option>
                    <option value="MEDIUM">MEDIUM</option>
                    <option value="LOW">LOW</option>
                  </select>
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '12px', color: '#94a3b8', marginBottom: '4px' }}>
                    Target Completion Date
                  </label>
                  <input
                    type="date"
                    value={targetDate}
                    onChange={(e) => setTargetDate(e.target.value)}
                    style={{ width: '100%', padding: '8px', backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: '4px', color: '#fff' }}
                  />
                </div>
              </div>

              <div style={{ marginBottom: '14px' }}>
                <label style={{ display: 'block', fontSize: '12px', color: '#94a3b8', marginBottom: '4px' }}>
                  Remediation Owner Email
                </label>
                <input
                  type="email"
                  value={ownerEmail}
                  onChange={(e) => setOwnerEmail(e.target.value)}
                  placeholder="lead@bank.in"
                  style={{ width: '100%', padding: '8px', backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: '4px', color: '#fff' }}
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '14px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '12px', color: '#94a3b8', marginBottom: '4px' }}>
                    Deprecation ID (Optional)
                  </label>
                  <input
                    type="text"
                    value={deprecationId}
                    onChange={(e) => setDeprecationId(e.target.value)}
                    placeholder="e.g. DEP-001"
                    style={{ width: '100%', padding: '8px', backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: '4px', color: '#fff' }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '12px', color: '#94a3b8', marginBottom: '4px' }}>
                    Antipattern ID (Optional)
                  </label>
                  <input
                    type="text"
                    value={antipatternId}
                    onChange={(e) => setAntipatternId(e.target.value)}
                    placeholder="e.g. AP-001"
                    style={{ width: '100%', padding: '8px', backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: '4px', color: '#fff' }}
                  />
                </div>
              </div>

              <div style={{ marginBottom: '18px' }}>
                <label style={{ display: 'block', fontSize: '12px', color: '#94a3b8', marginBottom: '4px' }}>
                  Statutory Justification (min 20 characters)
                </label>
                <textarea
                  rows={3}
                  value={justification}
                  onChange={(e) => setJustification(e.target.value)}
                  placeholder="Detailed justification explaining the technical root cause and remediation schedule."
                  style={{ width: '100%', padding: '8px', backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: '4px', color: '#fff' }}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
                <button
                  type="button"
                  onClick={() => setIsCreateOpen(false)}
                  style={{
                    backgroundColor: '#334155',
                    color: '#cbd5e1',
                    border: 'none',
                    borderRadius: '4px',
                    padding: '8px 16px',
                    cursor: 'pointer',
                  }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  style={{
                    backgroundColor: '#0284c7',
                    color: '#fff',
                    border: 'none',
                    borderRadius: '4px',
                    padding: '8px 16px',
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  Save & Register Item
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

export default DebtRegisterView
