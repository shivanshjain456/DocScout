import React, { useState, useEffect } from 'react'

export type ExportFormat = 'PDF' | 'ZIP' | 'MARKDOWN'

export interface ExportModalProps {
  isOpen: boolean
  onClose: () => void
  query: string
  passageIds: string[]
  apiBaseUrl?: string
  apiKey?: string
  className?: string
  onExportSuccess?: (downloadUrl: string, sha256: string) => void
}

export interface ExportResponseData {
  download_url: string
  file_sha256: string
  expires_at: string
  items_included: number
  format: ExportFormat
  audit_reference_id: string
}


export const ExportModal: React.FC<ExportModalProps> = ({
  isOpen,
  onClose,
  query,
  passageIds,
  apiBaseUrl = '',
  apiKey = '',
  className = '',
  onExportSuccess,
}) => {
  const [format, setFormat] = useState<ExportFormat>('PDF')
  const [auditRef, setAuditRef] = useState<string>('')
  const [isLoading, setIsLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [exportResult, setExportResult] = useState<ExportResponseData | null>(null)

  // Pre-fill default reference ID on open
  useEffect(() => {
    if (isOpen) {
      const today = new Date().toISOString().slice(0, 10).replace(/-/g, '')
      setAuditRef(`AUD-${today}-${Math.floor(1000 + Math.random() * 9000)}`)
      setError(null)
      setExportResult(null)
    }
  }, [isOpen])

  // Close on Escape key
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape' && isOpen) {
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

  if (!isOpen) return null

  const handleExport = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!auditRef.trim()) {
      setError('Audit Reference ID is required.')
      return
    }
    if (passageIds.length === 0) {
      setError('At least one passage ID must be selected for export.')
      return
    }
    if (passageIds.length > 50) {
      setError('A maximum of 50 passage IDs can be bundled per export package.')
      return
    }

    setIsLoading(true)
    setError(null)

    try {
      const response = await fetch(`${apiBaseUrl}/v1/compliance/export-evidence`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
        },
        body: JSON.stringify({
          query,
          passage_ids: passageIds,
          format,
          audit_reference_id: auditRef.trim(),
          include_control_mappings: true,
        }),
      })

      if (!response.ok) {
        const errJson = await response.json().catch(() => null)
        const msg = errJson?.detail || `Export failed with status ${response.status}`
        throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg))
      }

      const data: ExportResponseData = await response.json()
      setExportResult(data)
      if (onExportSuccess) {
        onExportSuccess(data.download_url, data.file_sha256)
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Unknown export error'
      setError(msg)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div
      className={`export-modal-backdrop ${className}`}
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.75)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 9999,
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        role="dialog"
        aria-labelledby="export-modal-title"
        aria-modal="true"
        style={{
          backgroundColor: '#161b22',
          border: '1px solid #30363d',
          borderRadius: '10px',
          padding: '24px',
          width: '520px',
          maxWidth: '90vw',
          color: '#c9d1d9',
          boxShadow: '0 16px 32px rgba(0, 0, 0, 0.5)',
          fontFamily: 'system-ui, -apple-system, sans-serif',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h2 id="export-modal-title" style={{ margin: 0, fontSize: '1.25rem', color: '#f0f6fc' }}>
            Export Audit Evidence Package
          </h2>
          <button
            aria-label="Close"
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: '#8b949e',
              fontSize: '1.2rem',
              cursor: 'pointer',
            }}
          >
            x
          </button>
        </div>

        <p style={{ margin: '0 0 16px 0', fontSize: '0.875rem', color: '#8b949e' }}>
          Bundle retrieved circular clauses, timestamped citations, and cryptographic provenance digests into a certified dossier.
        </p>

        {error && (
          <div
            className="export-error-banner"
            style={{
              backgroundColor: 'rgba(248, 81, 73, 0.15)',
              border: '1px solid #f85149',
              borderRadius: '6px',
              padding: '10px 14px',
              marginBottom: '16px',
              color: '#ff7b72',
              fontSize: '0.85rem',
            }}
          >
            {error}
          </div>
        )}

        {exportResult ? (
          <div className="export-success-container" style={{ textAlign: 'center', padding: '12px 0' }}>
            <div style={{ color: '#3fb950', fontSize: '1.1rem', fontWeight: 600, marginBottom: '8px' }}>
              Dossier Successfully Compiled!
            </div>
            <p style={{ fontSize: '0.85rem', color: '#8b949e', marginBottom: '16px' }}>
              Format: <strong>{exportResult.format}</strong> | Items Included: <strong>{exportResult.items_included}</strong>
            </p>

            <div style={{ marginBottom: '16px', textAlign: 'left', backgroundColor: '#0d1117', padding: '12px', borderRadius: '6px', border: '1px solid #21262d' }}>
              <div style={{ fontSize: '0.75rem', color: '#8b949e', marginBottom: '4px' }}>SHA-256 Provenance Digest:</div>
              <code className="file-sha256-display" style={{ fontSize: '0.75rem', color: '#58a6ff', wordBreak: 'break-all' }}>
                {exportResult.file_sha256}
              </code>
            </div>

            <div style={{ display: 'flex', gap: '12px', justifyContent: 'center' }}>
              <a
                href={exportResult.download_url}
                download
                className="download-button"
                style={{
                  backgroundColor: '#238636',
                  color: '#ffffff',
                  padding: '8px 16px',
                  borderRadius: '6px',
                  textDecoration: 'none',
                  fontSize: '0.9rem',
                  fontWeight: 600,
                  display: 'inline-block',
                }}
              >
                Download Package
              </a>
              <button
                type="button"
                onClick={onClose}
                style={{
                  backgroundColor: '#21262d',
                  color: '#c9d1d9',
                  border: '1px solid #30363d',
                  padding: '8px 16px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '0.9rem',
                }}
              >
                Close
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleExport}>
            <div style={{ marginBottom: '14px' }}>
              <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, marginBottom: '6px', color: '#c9d1d9' }}>
                Target Mandate / Query:
              </label>
              <div style={{ backgroundColor: '#0d1117', padding: '8px 12px', borderRadius: '6px', border: '1px solid #21262d', fontSize: '0.85rem', color: '#8b949e' }}>
                {query || '(No query provided)'}
              </div>
            </div>

            <div style={{ marginBottom: '14px' }}>
              <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, marginBottom: '6px', color: '#c9d1d9' }}>
                Auditor Reference ID:
              </label>
              <input
                type="text"
                className="audit-reference-input"
                value={auditRef}
                onChange={(e) => setAuditRef(e.target.value)}
                placeholder="e.g. AUD-2026-Q3-001"
                required
                style={{
                  width: '100%',
                  boxSizing: 'border-box',
                  backgroundColor: '#0d1117',
                  border: '1px solid #30363d',
                  borderRadius: '6px',
                  padding: '8px 12px',
                  color: '#f0f6fc',
                  fontSize: '0.9rem',
                }}
              />
            </div>

            <div style={{ marginBottom: '16px' }}>
              <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, marginBottom: '6px', color: '#c9d1d9' }}>
                Export Archive Format:
              </label>
              <select
                className="format-select"
                value={format}
                onChange={(e) => setFormat(e.target.value as ExportFormat)}
                style={{
                  width: '100%',
                  boxSizing: 'border-box',
                  backgroundColor: '#0d1117',
                  border: '1px solid #30363d',
                  borderRadius: '6px',
                  padding: '8px 12px',
                  color: '#f0f6fc',
                  fontSize: '0.9rem',
                }}
              >
                <option value="PDF">PDF (ISO 19005-1 Compliant Archival Dossier)</option>
                <option value="ZIP">ZIP Archive (with manifest.json & individual clause files)</option>
                <option value="MARKDOWN">Markdown Report (Standalone text & hash tables)</option>
              </select>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
              <span className="passages-count-badge" style={{ fontSize: '0.85rem', color: '#8b949e' }}>
                Included Passages: <strong>{passageIds.length}</strong> (Max 50)
              </span>
              <span style={{ fontSize: '0.75rem', color: '#8b949e' }}>
                Retention: 60-min automatic expiry
              </span>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
              <button
                type="button"
                onClick={onClose}
                disabled={isLoading}
                style={{
                  backgroundColor: '#21262d',
                  color: '#c9d1d9',
                  border: '1px solid #30363d',
                  padding: '8px 16px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '0.9rem',
                }}
              >
                Cancel
              </button>
              <button
                type="submit"
                className="export-submit-button"
                disabled={isLoading}
                style={{
                  backgroundColor: '#238636',
                  color: '#ffffff',
                  border: 'none',
                  padding: '8px 18px',
                  borderRadius: '6px',
                  cursor: isLoading ? 'not-allowed' : 'pointer',
                  fontWeight: 600,
                  fontSize: '0.9rem',
                }}
              >
                {isLoading ? 'Compiling Dossier...' : 'Compile & Export'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
