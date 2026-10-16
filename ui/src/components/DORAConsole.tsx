import React, { useState, useMemo } from 'react'

export interface PillarStatusData {
  pillar_name: string
  compliance_pct: number
  gaps: string[]
  articles: string[]
}

export interface ICTSystemData {
  system_id: string
  name: string
  criticality: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'
  is_third_party: boolean
  third_party_provider?: string | null
  is_critical_third_party: boolean
  has_exit_strategy: boolean
  last_tlpt_date?: string | null
  rto_minutes?: number | null
  rpo_minutes?: number | null
  has_incident_plan: boolean
  has_threat_intel_sharing: boolean
  metadata?: Record<string, unknown>
}

export interface DORAComplianceReportData {
  tenant_id: string
  total_systems: number
  critical_systems: number
  overall_readiness: number
  pillars: Record<string, PillarStatusData>
  recommendations: string[]
  evaluated_at: string
}

export interface DORAConsoleProps {
  initialReport?: DORAComplianceReportData
  initialSystems?: ICTSystemData[]
  tenantId?: string
  apiBaseUrl?: string
  apiKey?: string
  className?: string
  onAssessComplete?: (report: DORAComplianceReportData) => void
}

const DEFAULT_MOCK_REPORT: DORAComplianceReportData = {
  tenant_id: 'default',
  total_systems: 6,
  critical_systems: 2,
  overall_readiness: 76.5,
  evaluated_at: new Date().toISOString(),
  pillars: {
    pillar_1_risk_management: {
      pillar_name: 'ICT Risk Management',
      compliance_pct: 88.0,
      gaps: [],
      articles: ['Articles 5-16'],
    },
    pillar_2_incident_reporting: {
      pillar_name: 'ICT Incident Management and Reporting',
      compliance_pct: 100.0,
      gaps: [],
      articles: ['Articles 17-23'],
    },
    pillar_3_resilience_testing: {
      pillar_name: 'Digital Operational Resilience Testing',
      compliance_pct: 65.0,
      gaps: [
        "Critical system 'Core Payment Engine' last TLPT test was 2.8 years ago; renewal scheduled.",
      ],
      articles: ['Articles 24-27'],
    },
    pillar_4_third_party_risk: {
      pillar_name: 'ICT Third-Party Risk Management',
      compliance_pct: 55.0,
      gaps: [
        "Critical ICT third-party provider 'CloudHosting Global' lacks tested transition exit strategy under Article 28(8).",
      ],
      articles: ['Articles 28-44'],
    },
    pillar_5_info_sharing: {
      pillar_name: 'Information-Sharing Arrangements',
      compliance_pct: 74.5,
      gaps: [
        'Cyber threat intelligence sharing agreement requires expansion to cover auxiliary channels.',
      ],
      articles: ['Article 45'],
    },
  },
  recommendations: [
    'Establish contractual exit strategies and alternative provider arrangements for Critical ICT Third-Party Providers.',
    'Schedule and execute mandatory Threat-Led Penetration Testing (TLPT/TIBER-EU) for critical systems.',
    'Maintain current operational resilience posture and conduct annual DORA readiness review.',
  ],
}

const DEFAULT_MOCK_SYSTEMS: ICTSystemData[] = [
  {
    system_id: 'sys-core-01',
    name: 'Core Banking Ledger',
    criticality: 'CRITICAL',
    is_third_party: false,
    third_party_provider: null,
    is_critical_third_party: false,
    has_exit_strategy: true,
    last_tlpt_date: '2025-05-15',
    rto_minutes: 60,
    rpo_minutes: 15,
    has_incident_plan: true,
    has_threat_intel_sharing: true,
  },
  {
    system_id: 'sys-pay-02',
    name: 'Core Payment Engine',
    criticality: 'CRITICAL',
    is_third_party: true,
    third_party_provider: 'CloudHosting Global',
    is_critical_third_party: true,
    has_exit_strategy: false,
    last_tlpt_date: '2023-11-20',
    rto_minutes: 120,
    rpo_minutes: 30,
    has_incident_plan: true,
    has_threat_intel_sharing: true,
  },
  {
    system_id: 'sys-crm-03',
    name: 'Client Portal & CRM',
    criticality: 'HIGH',
    is_third_party: true,
    third_party_provider: 'SaaS Platform Inc',
    is_critical_third_party: false,
    has_exit_strategy: true,
    last_tlpt_date: null,
    rto_minutes: 240,
    rpo_minutes: 60,
    has_incident_plan: true,
    has_threat_intel_sharing: false,
  },
  {
    system_id: 'sys-settle-04',
    name: 'SWIFT Gateway',
    criticality: 'HIGH',
    is_third_party: false,
    third_party_provider: null,
    is_critical_third_party: false,
    has_exit_strategy: true,
    last_tlpt_date: '2025-08-10',
    rto_minutes: 90,
    rpo_minutes: 15,
    has_incident_plan: true,
    has_threat_intel_sharing: true,
  },
  {
    system_id: 'sys-hr-05',
    name: 'Internal HR Directory',
    criticality: 'LOW',
    is_third_party: true,
    third_party_provider: 'WorkHR Cloud',
    is_critical_third_party: false,
    has_exit_strategy: false,
    last_tlpt_date: null,
    rto_minutes: 1440,
    rpo_minutes: 720,
    has_incident_plan: true,
    has_threat_intel_sharing: false,
  },
  {
    system_id: 'sys-rep-06',
    name: 'Regulatory Reporting Store',
    criticality: 'MEDIUM',
    is_third_party: false,
    third_party_provider: null,
    is_critical_third_party: false,
    has_exit_strategy: true,
    last_tlpt_date: null,
    rto_minutes: 480,
    rpo_minutes: 120,
    has_incident_plan: true,
    has_threat_intel_sharing: true,
  },
]

export const DORAConsole: React.FC<DORAConsoleProps> = ({
  initialReport,
  initialSystems,
  tenantId = 'default',
  apiBaseUrl = '',
  apiKey = '',
  className = '',
  onAssessComplete,
}) => {
  const [report, setReport] = useState<DORAComplianceReportData>(
    initialReport || DEFAULT_MOCK_REPORT
  )
  const [systems] = useState<ICTSystemData[]>(
    initialSystems || DEFAULT_MOCK_SYSTEMS
  )
  const [criticalityFilter, setCriticalityFilter] = useState<string>('ALL')
  const [searchQuery, setSearchQuery] = useState<string>('')
  const [isAssessing, setIsAssessing] = useState<boolean>(false)
  const [activeTab, setActiveTab] = useState<'pillars' | 'systems' | 'recommendations'>('pillars')

  const filteredSystems = useMemo(() => {
    return systems.filter((s) => {
      const matchesCrit =
        criticalityFilter === 'ALL' || s.criticality === criticalityFilter
      const matchesSearch =
        s.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        s.system_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (s.third_party_provider &&
          s.third_party_provider.toLowerCase().includes(searchQuery.toLowerCase()))
      return matchesCrit && matchesSearch
    })
  }, [systems, criticalityFilter, searchQuery])

  const triggerAssessment = async () => {
    setIsAssessing(true)
    try {
      if (apiBaseUrl) {
        const res = await fetch(`${apiBaseUrl}/v1/compliance/dora/assess?tenant_id=${tenantId}`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
          },
          body: JSON.stringify({
            tenant_id: tenantId,
            ict_systems: systems,
          }),
        })
        if (res.ok) {
          const data: DORAComplianceReportData = await res.json()
          setReport(data)
          if (onAssessComplete) {
            onAssessComplete(data)
          }
        }
      } else {
        // Local simulation fallback
        const updated = {
          ...report,
          evaluated_at: new Date().toISOString(),
        }
        setReport(updated)
        if (onAssessComplete) {
          onAssessComplete(updated)
        }
      }
    } catch {
      // Keep existing state on error
    } finally {
      setIsAssessing(false)
    }
  }

  const getScoreBadgeClass = (score: number) => {
    if (score >= 80) return 'bg-emerald-950/80 text-emerald-400 border-emerald-800'
    if (score >= 60) return 'bg-amber-950/80 text-amber-400 border-amber-800'
    return 'bg-rose-950/80 text-rose-400 border-rose-800'
  }

  return (
    <div
      data-testid="dora-console"
      className={`bg-slate-950 text-slate-100 rounded-xl border border-slate-800 p-6 shadow-2xl ${className}`}
    >
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-slate-800">
        <div>
          <div className="flex items-center gap-3">
            <span className="inline-flex items-center justify-center p-2 rounded-lg bg-indigo-950 border border-indigo-800 text-indigo-400">
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
              </svg>
            </span>
            <div>
              <h2 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                Digital Operational Resilience (DORA) Console
                <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-950 border border-indigo-800 text-indigo-300 font-mono">
                  EU 2022/2554
                </span>
              </h2>
              <p className="text-sm text-slate-400">
                Pillars 1-5 Operational Scorecards, TLPT Cadence, and Critical Third-Party Risk Oversight
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            data-testid="trigger-assessment-btn"
            onClick={triggerAssessment}
            disabled={isAssessing}
            className="px-4 py-2 text-sm font-semibold rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white transition-colors flex items-center gap-2 shadow-lg shadow-indigo-950/40"
          >
            {isAssessing ? (
              <>
                <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
                Evaluating Framework...
              </>
            ) : (
              'Run DORA Assessment'
            )}
          </button>
        </div>
      </div>

      {/* KPI Banner */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 my-6">
        <div
          data-testid="overall-readiness-gauge"
          className="bg-slate-900/80 border border-slate-800 rounded-lg p-4 flex flex-col justify-between"
        >
          <div className="text-xs font-medium text-slate-400 uppercase tracking-wider">
            Overall DORA Readiness
          </div>
          <div className="flex items-baseline gap-2 my-2">
            <span className="text-3xl font-extrabold text-white tracking-tight">
              {report.overall_readiness}%
            </span>
            <span
              className={`text-xs px-2 py-0.5 rounded border font-semibold ${getScoreBadgeClass(
                report.overall_readiness
              )}`}
            >
              {report.overall_readiness >= 80
                ? 'High Resilience'
                : report.overall_readiness >= 60
                ? 'Moderate Gaps'
                : 'Deficient'}
            </span>
          </div>
          <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
            <div
              className={`h-full transition-all duration-500 ${
                report.overall_readiness >= 80
                  ? 'bg-emerald-500'
                  : report.overall_readiness >= 60
                  ? 'bg-amber-500'
                  : 'bg-rose-500'
              }`}
              style={{ width: `${report.overall_readiness}%` }}
            />
          </div>
        </div>

        <div className="bg-slate-900/80 border border-slate-800 rounded-lg p-4 flex flex-col justify-between">
          <div className="text-xs font-medium text-slate-400 uppercase tracking-wider">
            Total Ingested Systems
          </div>
          <div className="text-3xl font-extrabold text-white tracking-tight my-2">
            {report.total_systems}
          </div>
          <div className="text-xs text-slate-400">
            Across tenant <span className="font-mono text-slate-300">{report.tenant_id}</span>
          </div>
        </div>

        <div className="bg-slate-900/80 border border-slate-800 rounded-lg p-4 flex flex-col justify-between">
          <div className="text-xs font-medium text-slate-400 uppercase tracking-wider">
            Critical Infrastructure
          </div>
          <div className="text-3xl font-extrabold text-amber-400 tracking-tight my-2">
            {report.critical_systems}
          </div>
          <div className="text-xs text-slate-400">
            Subject to mandatory Article 26 TLPT
          </div>
        </div>

        <div className="bg-slate-900/80 border border-slate-800 rounded-lg p-4 flex flex-col justify-between">
          <div className="text-xs font-medium text-slate-400 uppercase tracking-wider">
            Identified Compliance Gaps
          </div>
          <div className="text-3xl font-extrabold text-rose-400 tracking-tight my-2">
            {Object.values(report.pillars).reduce((acc, p) => acc + p.gaps.length, 0)}
          </div>
          <div className="text-xs text-slate-400">
            Statutory remediations required
          </div>
        </div>
      </div>

      {/* Navigation Tabs */}
      <div className="flex border-b border-slate-800 mb-6 gap-6">
        <button
          type="button"
          onClick={() => setActiveTab('pillars')}
          className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'pillars'
              ? 'border-indigo-500 text-indigo-400'
              : 'border-transparent text-slate-400 hover:text-slate-300'
          }`}
        >
          Statutory 5 Pillars Scorecard
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('systems')}
          className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'systems'
              ? 'border-indigo-500 text-indigo-400'
              : 'border-transparent text-slate-400 hover:text-slate-300'
          }`}
        >
          ICT Systems & Third-Party Inventory ({systems.length})
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('recommendations')}
          className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'recommendations'
              ? 'border-indigo-500 text-indigo-400'
              : 'border-transparent text-slate-400 hover:text-slate-300'
          }`}
        >
          Remediation Plan ({report.recommendations.length})
        </button>
      </div>

      {/* Tab: 5 Pillars Scorecard */}
      {activeTab === 'pillars' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Object.entries(report.pillars).map(([pillarKey, pillar]) => (
            <div
              key={pillarKey}
              data-testid={`pillar-card-${pillarKey}`}
              className="bg-slate-900 border border-slate-800 rounded-lg p-5 flex flex-col justify-between hover:border-slate-700 transition-colors"
            >
              <div>
                <div className="flex items-start justify-between gap-2 mb-2">
                  <h3 className="font-semibold text-white text-base leading-snug">
                    {pillar.pillar_name}
                  </h3>
                  <span
                    className={`text-xs px-2 py-0.5 rounded border font-mono font-bold ${getScoreBadgeClass(
                      pillar.compliance_pct
                    )}`}
                  >
                    {pillar.compliance_pct}%
                  </span>
                </div>
                <div className="text-xs text-slate-400 mb-3 font-mono">
                  {pillar.articles.join(', ')}
                </div>

                <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden mb-4">
                  <div
                    className={`h-full transition-all duration-500 ${
                      pillar.compliance_pct >= 80
                        ? 'bg-emerald-500'
                        : pillar.compliance_pct >= 60
                        ? 'bg-amber-500'
                        : 'bg-rose-500'
                    }`}
                    style={{ width: `${pillar.compliance_pct}%` }}
                  />
                </div>

                {pillar.gaps.length > 0 ? (
                  <div className="space-y-2 mt-3">
                    <div className="text-xs font-semibold text-rose-400 uppercase tracking-wider">
                      Identified Gaps ({pillar.gaps.length})
                    </div>
                    <ul className="space-y-1.5">
                      {pillar.gaps.map((gap, idx) => (
                        <li
                          key={idx}
                          className="text-xs text-rose-300 bg-rose-950/40 border border-rose-900/50 rounded p-2"
                        >
                          {gap}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <div className="text-xs text-emerald-400 bg-emerald-950/40 border border-emerald-900/50 rounded p-2 flex items-center gap-1.5 mt-3">
                    <svg className="w-4 h-4 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                    </svg>
                    Full statutory compliance verified.
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Tab: ICT Systems & Third-Party Inventory */}
      {activeTab === 'systems' && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row gap-3 justify-between items-center bg-slate-900 p-3 rounded-lg border border-slate-800">
            <div className="flex items-center gap-2 w-full sm:w-auto">
              <input
                type="text"
                placeholder="Search systems or vendors..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="bg-slate-950 border border-slate-700 text-sm rounded px-3 py-1.5 text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 w-full sm:w-64"
              />
            </div>
            <div className="flex items-center gap-2 w-full sm:w-auto justify-end">
              <label htmlFor="filter-criticality-select" className="text-xs text-slate-400">Criticality:</label>
              <select
                id="filter-criticality-select"
                data-testid="filter-criticality"
                value={criticalityFilter}
                onChange={(e) => setCriticalityFilter(e.target.value)}
                className="bg-slate-950 border border-slate-700 text-xs rounded px-2.5 py-1.5 text-slate-200 focus:outline-none focus:border-indigo-500"
              >
                <option value="ALL">All Tiers</option>
                <option value="CRITICAL">CRITICAL</option>
                <option value="HIGH">HIGH</option>
                <option value="MEDIUM">MEDIUM</option>
                <option value="LOW">LOW</option>
              </select>
            </div>
          </div>

          <div className="overflow-x-auto rounded-lg border border-slate-800">
            <table data-testid="dora-systems-table" className="w-full text-left text-sm text-slate-300">
              <thead className="bg-slate-900 text-xs uppercase tracking-wider text-slate-400 border-b border-slate-800">
                <tr>
                  <th className="px-4 py-3">System Name / ID</th>
                  <th className="px-4 py-3">Tier</th>
                  <th className="px-4 py-3">Third Party / CTPP</th>
                  <th className="px-4 py-3">Exit Strategy</th>
                  <th className="px-4 py-3">Last TLPT</th>
                  <th className="px-4 py-3">RTO / RPO</th>
                  <th className="px-4 py-3">Intel Sharing</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800 bg-slate-950/60">
                {filteredSystems.map((s) => (
                  <tr key={s.system_id} className="hover:bg-slate-900/40 transition-colors">
                    <td className="px-4 py-3 font-medium text-white">
                      <div>{s.name}</div>
                      <div className="text-xs font-mono text-slate-500">{s.system_id}</div>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`text-xs px-2 py-0.5 rounded font-bold border ${
                          s.criticality === 'CRITICAL'
                            ? 'bg-rose-950/60 text-rose-400 border-rose-800'
                            : s.criticality === 'HIGH'
                            ? 'bg-amber-950/60 text-amber-400 border-amber-800'
                            : 'bg-slate-800 text-slate-300 border-slate-700'
                        }`}
                      >
                        {s.criticality}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {s.is_third_party ? (
                        <div>
                          <div className="text-xs font-medium text-indigo-300">
                            {s.third_party_provider || 'External Vendor'}
                          </div>
                          {s.is_critical_third_party && (
                            <span className="text-[10px] px-1.5 py-0.2 rounded bg-purple-950 border border-purple-800 text-purple-300 font-semibold">
                              CTPP (Art. 28)
                            </span>
                          )}
                        </div>
                      ) : (
                        <span className="text-xs text-slate-500">Internal</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {s.has_exit_strategy ? (
                        <span className="text-xs text-emerald-400 font-medium">Verified</span>
                      ) : s.is_critical_third_party ? (
                        <span className="text-xs text-rose-400 font-bold">Missing (Gap)</span>
                      ) : (
                        <span className="text-xs text-slate-500">N/A</span>
                      )}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">
                      {s.last_tlpt_date ? (
                        <span className="text-slate-300">{s.last_tlpt_date}</span>
                      ) : s.criticality === 'CRITICAL' ? (
                        <span className="text-rose-400 font-bold">None (Gap)</span>
                      ) : (
                        <span className="text-slate-500">Not required</span>
                      )}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">
                      {s.rto_minutes !== null && s.rto_minutes !== undefined ? (
                        <span>
                          RTO: {s.rto_minutes}m / RPO: {s.rpo_minutes ?? '-'}m
                        </span>
                      ) : (
                        <span className="text-slate-500">Undefined</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {s.has_threat_intel_sharing ? (
                        <span className="text-xs text-emerald-400">Active</span>
                      ) : (
                        <span className="text-xs text-slate-500">No</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tab: Recommendations */}
      {activeTab === 'recommendations' && (
        <div data-testid="recommendations-list" className="space-y-3">
          <div className="text-sm text-slate-400 mb-2">
            Prioritized operational resilience action items synthesized across statutory audit findings:
          </div>
          {report.recommendations.map((rec, idx) => (
            <div
              key={idx}
              className="bg-slate-900 border border-slate-800 hover:border-slate-700 p-4 rounded-lg flex items-start gap-3 transition-colors"
            >
              <span className="flex-shrink-0 w-6 h-6 rounded-full bg-indigo-950 border border-indigo-800 text-indigo-400 flex items-center justify-center text-xs font-bold">
                {idx + 1}
              </span>
              <div className="text-sm text-slate-200">{rec}</div>
            </div>
          ))}
        </div>
      )}

      {/* Footer Info */}
      <div className="mt-6 pt-4 border-t border-slate-800 flex flex-col sm:flex-row justify-between items-center text-xs text-slate-500">
        <div>
          Last evaluated:{' '}
          <span className="font-mono text-slate-400">
            {new Date(report.evaluated_at).toLocaleString()}
          </span>
        </div>
        <div>
          DocScout Enterprise-100 Continuous Resilience Runner (FEAT-058)
        </div>
      </div>
    </div>
  )
}
export default DORAConsole
