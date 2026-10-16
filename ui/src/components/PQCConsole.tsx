import React, { useState, useMemo } from 'react'

export interface CryptoAssetItemData {
  asset_id: string
  tenant_id: string
  hostname: string
  hostname_hash: string
  tls_version: string
  cipher_suite: string
  cert_signature_algo: string
  cert_key_size?: number | null
  cert_expiry?: string | null
  classification:
    | 'PQC_READY'
    | 'HYBRID'
    | 'CLASSICAL_SAFE'
    | 'CLASSICAL_DEPRECATED'
    | 'UNKNOWN_AUDIT_REQUIRED'
  hndl_vulnerable: boolean
  quantum_safe_algo?: string | null
  warning?: string | null
  recommended_action: string
  scanned_at: string
}

export interface PQCReadinessReportData {
  total_assets: int_number
  quantum_vulnerable_count: int_number
  pqc_ready_count: int_number
  hybrid_count: int_number
  deprecated_count: int_number
  unknown_count: int_number
  hndl_exposure_score: number
  readiness_score: number
  migration_milestone: 'PHASE_1_INVENTORY' | 'PHASE_2_HYBRID_TRANSITION' | 'PHASE_3_QUANTUM_RESILIENT'
  assets: CryptoAssetItemData[]
  evaluated_at: string
}

type int_number = number

export interface PQCConsoleProps {
  initialReport?: PQCReadinessReportData
  tenantId?: string
  apiBaseUrl?: string
  apiKey?: string
  className?: string
  onScanComplete?: (report: PQCReadinessReportData) => void
}

const DEFAULT_MOCK_REPORT: PQCReadinessReportData = {
  total_assets: 8,
  quantum_vulnerable_count: 5,
  pqc_ready_count: 1,
  hybrid_count: 2,
  deprecated_count: 1,
  unknown_count: 1,
  hndl_exposure_score: 0.625,
  readiness_score: 31.25,
  migration_milestone: 'PHASE_2_HYBRID_TRANSITION',
  evaluated_at: new Date().toISOString(),
  assets: [
    {
      asset_id: '11111111-1111-1111-1111-111111111111',
      tenant_id: 'default',
      hostname: 'api.payments.docscout.internal',
      hostname_hash: 'a9f4c3b2d1e08765',
      tls_version: 'TLSv1.3',
      cipher_suite: 'TLS_AES_256_GCM_SHA384',
      cert_signature_algo: 'ecdsa-with-SHA384',
      cert_key_size: 384,
      cert_expiry: '2027-12-31',
      classification: 'HYBRID',
      hndl_vulnerable: false,
      quantum_safe_algo: 'Hybrid X25519 + FIPS 203 (ML-KEM-768)',
      recommended_action: 'Hybrid post-quantum key encapsulation protects against Harvest-Now-Decrypt-Later attacks',
      scanned_at: new Date().toISOString(),
    },
    {
      asset_id: '22222222-2222-2222-2222-222222222222',
      tenant_id: 'default',
      hostname: 'core-settlement.bank.internal',
      hostname_hash: 'b8e3d2c1f0a97654',
      tls_version: 'TLSv1.3',
      cipher_suite: 'TLS_MLKEM768_AES_256_GCM_SHA384',
      cert_signature_algo: 'mldsa65',
      cert_key_size: null,
      cert_expiry: '2028-06-30',
      classification: 'PQC_READY',
      hndl_vulnerable: false,
      quantum_safe_algo: 'FIPS 203 (ML-KEM) & FIPS 204 (ML-DSA)',
      recommended_action: 'Endpoint fully quantum-resilient under standardized NIST PQC specifications',
      scanned_at: new Date().toISOString(),
    },
    {
      asset_id: '33333333-3333-3333-3333-333333333333',
      tenant_id: 'default',
      hostname: 'auth-gateway.docscout.internal',
      hostname_hash: 'c7d2e1f0b9a86543',
      tls_version: 'TLSv1.3',
      cipher_suite: 'TLS_AES_256_GCM_SHA384',
      cert_signature_algo: 'sha256WithRSAEncryption',
      cert_key_size: 4096,
      cert_expiry: '2026-11-15',
      classification: 'CLASSICAL_SAFE',
      hndl_vulnerable: true,
      quantum_safe_algo: null,
      recommended_action: 'Upgrade key exchange to Hybrid ML-KEM (FIPS 203) to mitigate Harvest-Now-Decrypt-Later vulnerability',
      scanned_at: new Date().toISOString(),
    },
    {
      asset_id: '44444444-4444-4444-4444-444444444444',
      tenant_id: 'default',
      hostname: 'legacy-partner-gateway.bank.internal',
      hostname_hash: 'd6c1b0a9f8e75432',
      tls_version: 'TLSv1.2',
      cipher_suite: 'ECDHE-RSA-AES256-SHA',
      cert_signature_algo: 'sha256WithRSAEncryption',
      cert_key_size: 2048,
      cert_expiry: '2025-08-20',
      classification: 'CLASSICAL_DEPRECATED',
      hndl_vulnerable: true,
      quantum_safe_algo: null,
      warning: 'Vulnerable CBC mode or legacy SHA-1 cipher and RSA 2048 flagged per NIST SP 800-57',
      recommended_action: 'Migrate to AES-GCM or ChaCha20-Poly1305 AEAD ciphers and upgrade RSA key to >= 3072 bits',
      scanned_at: new Date().toISOString(),
    },
    {
      asset_id: '55555555-5555-5555-5555-555555555555',
      tenant_id: 'default',
      hostname: 'custom-switch.partner.internal',
      hostname_hash: 'e5b0a9f8e7d64321',
      tls_version: 'TLSv1.3',
      cipher_suite: 'CUSTOM_PROPRIETARY_CIPHER_999',
      cert_signature_algo: 'sha256WithRSAEncryption',
      cert_key_size: 3072,
      cert_expiry: '2027-04-10',
      classification: 'UNKNOWN_AUDIT_REQUIRED',
      hndl_vulnerable: true,
      quantum_safe_algo: null,
      warning: "UNKNOWN_AUDIT_REQUIRED: Cipher suite 'CUSTOM_PROPRIETARY_CIPHER_999' not recognized in standard IANA registry",
      recommended_action: 'Conduct manual cryptographic audit for non-standard or proprietary cipher suite',
      scanned_at: new Date().toISOString(),
    },
  ],
}

export const PQCConsole: React.FC<PQCConsoleProps> = ({
  initialReport = DEFAULT_MOCK_REPORT,
  className = '',
}) => {
  const [report] = useState<PQCReadinessReportData>(initialReport)
  const [filter, setFilter] = useState<string>('ALL')
  const [searchTerm, setSearchTerm] = useState<string>('')
  const [isScanning, setIsScanning] = useState<boolean>(false)

  const filteredAssets = useMemo(() => {
    return report.assets.filter((asset) => {
      const matchesFilter = filter === 'ALL' || asset.classification === filter
      const matchesSearch =
        searchTerm.trim() === '' ||
        asset.hostname.toLowerCase().includes(searchTerm.toLowerCase()) ||
        asset.cipher_suite.toLowerCase().includes(searchTerm.toLowerCase()) ||
        asset.hostname_hash.toLowerCase().includes(searchTerm.toLowerCase())
      return matchesFilter && matchesSearch
    })
  }, [report.assets, filter, searchTerm])

  const getMilestoneBadge = (milestone: string) => {
    switch (milestone) {
      case 'PHASE_3_QUANTUM_RESILIENT':
        return {
          label: 'Phase 3: Quantum Resilient',
          bg: 'bg-emerald-950 text-emerald-400 border-emerald-800',
        }
      case 'PHASE_2_HYBRID_TRANSITION':
        return {
          label: 'Phase 2: Hybrid Transition',
          bg: 'bg-indigo-950 text-indigo-400 border-indigo-800',
        }
      default:
        return {
          label: 'Phase 1: Classical Inventory',
          bg: 'bg-amber-950 text-amber-400 border-amber-800',
        }
    }
  }

  const getClassificationBadge = (cls: string) => {
    switch (cls) {
      case 'PQC_READY':
        return 'bg-emerald-900/50 text-emerald-300 border-emerald-700'
      case 'HYBRID':
        return 'bg-indigo-900/50 text-indigo-300 border-indigo-700'
      case 'CLASSICAL_SAFE':
        return 'bg-sky-900/50 text-sky-300 border-sky-700'
      case 'CLASSICAL_DEPRECATED':
        return 'bg-rose-900/50 text-rose-300 border-rose-700'
      default:
        return 'bg-amber-900/50 text-amber-300 border-amber-700'
    }
  }

  const milestoneInfo = getMilestoneBadge(report.migration_milestone)

  return (
    <div
      data-testid="pqc-console"
      className={`rounded-xl border border-slate-800 bg-slate-950 p-6 text-slate-100 shadow-2xl ${className}`}
    >
      {/* Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 pb-6 border-b border-slate-800">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-xl font-bold text-slate-100 tracking-tight">
              Post-Quantum Cryptographic Migration Tracker
            </h2>
            <span
              data-testid="migration-milestone-badge"
              className={`px-3 py-1 text-xs font-semibold rounded-full border ${milestoneInfo.bg}`}
            >
              {milestoneInfo.label}
            </span>
          </div>
          <p className="mt-1 text-sm text-slate-400">
            FIPS 203/204/205 post-quantum standard verification and Harvest-Now-Decrypt-Later (HNDL) risk monitoring.
          </p>
        </div>

        <button
          data-testid="trigger-scan-btn"
          onClick={() => {
            setIsScanning(true)
            setTimeout(() => setIsScanning(false), 800)
          }}
          disabled={isScanning}
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 active:bg-indigo-700 disabled:opacity-50 text-white font-medium text-sm rounded-lg transition-colors shadow-md flex items-center gap-2 self-start md:self-auto"
        >
          {isScanning ? 'Scanning Endpoints...' : 'Scan Cryptographic Inventory'}
        </button>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 my-6">
        {/* Readiness Score */}
        <div
          data-testid="readiness-score-gauge"
          className="rounded-lg border border-slate-800 bg-slate-900/60 p-4"
        >
          <div className="text-xs font-semibold uppercase text-slate-400">PQC Readiness Score</div>
          <div className="mt-2 text-3xl font-extrabold text-indigo-400">
            {report.readiness_score.toFixed(1)}%
          </div>
          <div className="mt-2 text-xs text-slate-400">
            Weighted adoption of pure PQC and hybrid key exchanges
          </div>
        </div>

        {/* HNDL Risk Exposure */}
        <div
          data-testid="hndl-exposure-meter"
          className="rounded-lg border border-slate-800 bg-slate-900/60 p-4"
        >
          <div className="text-xs font-semibold uppercase text-slate-400">HNDL Risk Exposure</div>
          <div className="mt-2 text-3xl font-extrabold text-rose-400">
            {(report.hndl_exposure_score * 100).toFixed(1)}%
          </div>
          <div className="mt-2 text-xs text-slate-400">
            {report.quantum_vulnerable_count} of {report.total_assets} endpoints vulnerable to interception
          </div>
        </div>

        {/* PQC Ready & Hybrid */}
        <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
          <div className="text-xs font-semibold uppercase text-slate-400">Quantum Resilient</div>
          <div className="mt-2 text-3xl font-extrabold text-emerald-400">
            {report.pqc_ready_count + report.hybrid_count}
          </div>
          <div className="mt-2 text-xs text-slate-400">
            {report.pqc_ready_count} pure PQC, {report.hybrid_count} hybrid key exchanges
          </div>
        </div>

        {/* Deprecated & Audited */}
        <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
          <div className="text-xs font-semibold uppercase text-slate-400">Action Required</div>
          <div className="mt-2 text-3xl font-extrabold text-amber-400">
            {report.deprecated_count + report.unknown_count}
          </div>
          <div className="mt-2 text-xs text-slate-400">
            {report.deprecated_count} deprecated, {report.unknown_count} non-standard ciphers
          </div>
        </div>
      </div>

      {/* Filter and Search Controls */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-1 bg-slate-900 border border-slate-800 p-1 rounded-lg text-xs">
          {[
            { id: 'ALL', label: 'All Assets' },
            { id: 'PQC_READY', label: 'PQC Ready' },
            { id: 'HYBRID', label: 'Hybrid' },
            { id: 'CLASSICAL_SAFE', label: 'Classical Safe' },
            { id: 'CLASSICAL_DEPRECATED', label: 'Deprecated' },
            { id: 'UNKNOWN_AUDIT_REQUIRED', label: 'Audit Required' },
          ].map((tab) => (
            <button
              key={tab.id}
              data-testid={`filter-tab-${tab.id.toLowerCase()}`}
              onClick={() => setFilter(tab.id)}
              className={`px-3 py-1.5 rounded-md font-medium transition-colors ${
                filter === tab.id
                  ? 'bg-indigo-600 text-white'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <input
          type="text"
          placeholder="Filter by hostname, hash, or cipher suite..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="w-full sm:w-72 px-3 py-1.5 bg-slate-900 border border-slate-800 rounded-lg text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
        />
      </div>

      {/* Inventory Table */}
      <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-900/30">
        <table data-testid="pqc-assets-table" className="w-full text-left text-xs">
          <thead className="bg-slate-900/80 text-slate-400 uppercase font-semibold border-b border-slate-800">
            <tr>
              <th className="py-3 px-4">Endpoint Hostname</th>
              <th className="py-3 px-3">TLS & Cipher Suite</th>
              <th className="py-3 px-3">Cert Algo / Key</th>
              <th className="py-3 px-3">Classification</th>
              <th className="py-3 px-3">HNDL Risk</th>
              <th className="py-3 px-4">Remediation Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 font-mono">
            {filteredAssets.length === 0 ? (
              <tr>
                <td colSpan={6} className="py-8 text-center text-slate-500">
                  No cryptographic assets matched the active filter.
                </td>
              </tr>
            ) : (
              filteredAssets.map((asset) => (
                <tr
                  key={asset.asset_id}
                  data-testid={`asset-row-${asset.asset_id}`}
                  className="hover:bg-slate-800/30 transition-colors"
                >
                  <td className="py-3 px-4">
                    <div className="font-sans font-semibold text-slate-200">{asset.hostname}</div>
                    <div className="text-[10px] text-slate-500">Hash: {asset.hostname_hash}</div>
                  </td>
                  <td className="py-3 px-3">
                    <div className="text-slate-300">{asset.cipher_suite}</div>
                    <div className="text-[10px] text-slate-500">{asset.tls_version}</div>
                  </td>
                  <td className="py-3 px-3">
                    <div className="text-slate-300">{asset.cert_signature_algo}</div>
                    <div className="text-[10px] text-slate-500">
                      {asset.cert_key_size ? `${asset.cert_key_size} bits` : 'PQC Post-Quantum'}
                      {asset.cert_expiry && ` | Exp: ${asset.cert_expiry}`}
                    </div>
                  </td>
                  <td className="py-3 px-3">
                    <span
                      data-testid={`classification-badge-${asset.classification.toLowerCase()}`}
                      className={`inline-block px-2.5 py-1 rounded-md text-[10px] font-semibold border ${getClassificationBadge(
                        asset.classification
                      )}`}
                    >
                      {asset.classification}
                    </span>
                    {asset.quantum_safe_algo && (
                      <div className="mt-1 text-[10px] text-emerald-400 font-sans">
                        {asset.quantum_safe_algo}
                      </div>
                    )}
                  </td>
                  <td className="py-3 px-3">
                    {asset.hndl_vulnerable ? (
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold bg-rose-950/80 text-rose-400 border border-rose-800">
                        VULNERABLE
                      </span>
                    ) : (
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-950/80 text-emerald-400 border border-emerald-800">
                        PROTECTED
                      </span>
                    )}
                  </td>
                  <td className="py-3 px-4 font-sans text-slate-400 text-xs">
                    {asset.warning && (
                      <div className="text-amber-400 text-[11px] mb-1 font-medium">
                        Warning: {asset.warning}
                      </div>
                    )}
                    <div>{asset.recommended_action}</div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
export default PQCConsole
