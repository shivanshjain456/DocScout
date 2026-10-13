import React, { useState, useMemo, useEffect, useRef } from 'react'

export interface StandardMentionItem {
  span: [number, number]
  raw_text: string
  standard_id: string
  control_hint?: string | null
  standard_name?: string | null
  governing_body?: string | null
}

export interface DocumentReaderProps {
  title?: string
  documentId?: string
  content: string
  mentions?: StandardMentionItem[]
  enabled?: boolean
  onStandardClick?: (standardId: string) => void
  className?: string
}

interface ActivePopover {
  mention: StandardMentionItem
  rect: DOMRect
}

export const DocumentReader: React.FC<DocumentReaderProps> = ({
  title = 'Regulatory Circular Viewer',
  documentId,
  content,
  mentions = [],
  enabled = true,
  onStandardClick,
  className = '',
}) => {
  const [activePopover, setActivePopover] = useState<ActivePopover | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  // Close popover on Escape key
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape' && activePopover) {
        setActivePopover(null)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [activePopover])

  // Build annotated text slices
  const renderedContent = useMemo(() => {
    if (!enabled || !mentions || mentions.length === 0 || !content) {
      return <span>{content}</span>
    }

    // Sort mentions by char_start ascending
    const sorted = [...mentions].sort((a, b) => a.span[0] - b.span[0])
    const nodes: React.ReactNode[] = []
    let cursor = 0

    sorted.forEach((m, idx) => {
      const [start, end] = m.span
      if (start > cursor) {
        nodes.push(
          <span key={`txt-${cursor}-${start}`}>
            {content.slice(cursor, start)}
          </span>
        )
      }

      const isExpanded =
        activePopover !== null &&
        activePopover.mention.standard_id === m.standard_id &&
        activePopover.mention.span[0] === m.span[0]

      nodes.push(
        <span
          key={`mention-${m.standard_id}-${idx}-${start}`}
          className="standard-mention-badge"
          data-standard-id={m.standard_id}
          data-control-hint={m.control_hint || ''}
          role="button"
          tabIndex={0}
          aria-haspopup="dialog"
          aria-expanded={isExpanded}
          onClick={(e) => {
            const rect = e.currentTarget.getBoundingClientRect()
            setActivePopover(isExpanded ? null : { mention: m, rect })
            if (onStandardClick) {
              onStandardClick(m.standard_id)
            }
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              const rect = e.currentTarget.getBoundingClientRect()
              setActivePopover(isExpanded ? null : { mention: m, rect })
              if (onStandardClick) {
                onStandardClick(m.standard_id)
              }
            }
          }}
          style={{
            backgroundColor: 'rgba(56, 139, 253, 0.15)',
            borderBottom: '1.5px solid #58a6ff',
            color: '#79c0ff',
            padding: '1px 4px',
            borderRadius: '4px',
            cursor: 'pointer',
            fontWeight: 500,
            display: 'inline',
          }}
        >
          {m.raw_text}
        </span>
      )

      cursor = Math.max(cursor, end)
    })

    if (cursor < content.length) {
      nodes.push(
        <span key={`txt-${cursor}-end`}>
          {content.slice(cursor)}
        </span>
      )
    }

    return nodes
  }, [content, mentions, enabled, activePopover, onStandardClick])

  return (
    <div
      ref={containerRef}
      className={`document-reader-container ${className}`}
      style={{
        backgroundColor: '#0d1117',
        color: '#c9d1d9',
        border: '1px solid #30363d',
        borderRadius: '8px',
        padding: '24px',
        fontFamily: 'system-ui, -apple-system, sans-serif',
        position: 'relative',
        lineHeight: 1.6,
      }}
    >
      <header
        style={{
          borderBottom: '1px solid #21262d',
          paddingBottom: '16px',
          marginBottom: '20px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <div>
          <h2 style={{ margin: '0 0 6px 0', fontSize: '1.25rem', color: '#f0f6fc' }}>
            {title}
          </h2>
          {documentId && (
            <span style={{ fontSize: '0.85rem', color: '#8b949e', fontFamily: 'monospace' }}>
              Doc ID: {documentId}
            </span>
          )}
        </div>
        <div>
          <span
            className="mentions-count-badge"
            style={{
              backgroundColor: '#1f6feb',
              color: '#ffffff',
              padding: '4px 10px',
              borderRadius: '12px',
              fontSize: '0.8rem',
              fontWeight: 600,
            }}
          >
            {mentions.length} Standards Cited
          </span>
        </div>
      </header>

      <div
        className="document-body-content"
        style={{
          fontSize: '1rem',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
        }}
      >
        {renderedContent}
      </div>

      {activePopover && (
        <div
          role="dialog"
          aria-label={activePopover.mention.standard_name || activePopover.mention.standard_id}
          style={{
            position: 'fixed',
            top: `${Math.min(window.innerHeight - 200, activePopover.rect.bottom + 8)}px`,
            left: `${Math.max(16, Math.min(window.innerWidth - 320, activePopover.rect.left))}px`,
            backgroundColor: '#161b22',
            border: '1px solid #388bfd',
            borderRadius: '8px',
            padding: '16px',
            boxShadow: '0 8px 24px rgba(0, 0, 0, 0.4)',
            zIndex: 1000,
            width: '300px',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
            <span
              className="standard-title"
              style={{ fontWeight: 600, color: '#f0f6fc', fontSize: '0.95rem' }}
            >
              {activePopover.mention.standard_name || activePopover.mention.standard_id}
            </span>
            <button
              aria-label="Close"
              onClick={() => setActivePopover(null)}
              style={{
                background: 'transparent',
                border: 'none',
                color: '#8b949e',
                cursor: 'pointer',
                fontSize: '1rem',
              }}
            >
              x
            </button>
          </div>

          <div style={{ marginBottom: '8px' }}>
            <span
              className="standard-id-badge"
              style={{
                backgroundColor: '#21262d',
                color: '#58a6ff',
                padding: '2px 6px',
                borderRadius: '4px',
                fontSize: '0.75rem',
                fontFamily: 'monospace',
                marginRight: '6px',
              }}
            >
              {activePopover.mention.standard_id}
            </span>
            {activePopover.mention.governing_body && (
              <span
                className="standard-gov-body"
                style={{ fontSize: '0.75rem', color: '#8b949e' }}
              >
                {activePopover.mention.governing_body}
              </span>
            )}
          </div>

          {activePopover.mention.control_hint && (
            <div
              className="standard-control-hint"
              style={{
                backgroundColor: 'rgba(210, 153, 34, 0.15)',
                color: '#d29922',
                padding: '4px 8px',
                borderRadius: '4px',
                fontSize: '0.8rem',
                marginBottom: '12px',
                border: '1px solid rgba(210, 153, 34, 0.4)',
              }}
            >
              Control Hint: {activePopover.mention.control_hint}
            </div>
          )}

          <div>
            <a
              href={`/standards/${encodeURIComponent(activePopover.mention.standard_id)}`}
              className="standard-deep-link"
              style={{
                display: 'inline-block',
                color: '#58a6ff',
                textDecoration: 'none',
                fontSize: '0.85rem',
                fontWeight: 500,
              }}
              onClick={(e) => {
                if (onStandardClick) {
                  e.preventDefault()
                  onStandardClick(activePopover.mention.standard_id)
                }
              }}
            >
              View Standard Specification &rarr;
            </a>
          </div>
        </div>
      )}
    </div>
  )
}
