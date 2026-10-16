import { useState, useRef, useMemo, useEffect, useCallback } from 'react'
import { useTaxonomyDictionary, type TaxonomyTerm } from '../hooks/useTaxonomyDictionary'

export interface TermAnnotatorProps {
  content: string
  highlight?: boolean
  tooltipDelayMs?: number
  className?: string
  onTermHover?: (termId: string) => void
}

interface ActivePopover {
  term: TaxonomyTerm
  rect: DOMRect
}

export function TermAnnotator({
  content,
  highlight = true,
  tooltipDelayMs = 250,
  className = '',
  onTermHover,
}: TermAnnotatorProps) {
  const { termsList, lookupTerm } = useTaxonomyDictionary()
  const [activePopover, setActivePopover] = useState<ActivePopover | null>(null)
  const hoverTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const containerRef = useRef<HTMLSpanElement>(null)

  // Clear hover timer on unmount
  useEffect(() => {
    return () => {
      if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current)
    }
  }, [])

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

  // Build compiled regex of recognized terms & aliases
  const termsRegex = useMemo(() => {
    if (!highlight || termsList.length === 0) return null

    // Extract terms and aliases, filter out single letters or noise
    const tokens = new Set<string>()
    for (const t of termsList) {
      if (t.term && t.term.length >= 2) tokens.add(t.term)
      if (t.aliases) {
        for (const a of t.aliases) {
          if (a && a.length >= 2) tokens.add(a)
        }
      }
    }

    if (tokens.size === 0) return null

    // Sort descending by token length for greedy match
    const sortedTokens = Array.from(tokens).sort((a, b) => b.length - a.length)
    const escaped = sortedTokens.map((tok) => tok.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    return new RegExp(`\\b(${escaped.join('|')})\\b`, 'gi')
  }, [termsList, highlight])

  const triggerTelemetry = useCallback(
    (term: TaxonomyTerm) => {
      onTermHover?.(term.id)
      try {
        window.dispatchEvent(
          new CustomEvent('docscout:taxonomy_term_hover', {
            detail: { termId: term.id, term: term.term },
          })
        )
      } catch {
        // Opt-in telemetry failure must never disrupt UI
      }
    },
    [onTermHover]
  )

  const handleMouseEnter = (term: TaxonomyTerm, targetEl: HTMLElement) => {
    if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current)
    hoverTimerRef.current = setTimeout(() => {
      const rect = targetEl.getBoundingClientRect()
      setActivePopover({ term, rect })
      triggerTelemetry(term)
    }, tooltipDelayMs)
  }

  const handleMouseLeave = () => {
    if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current)
  }

  const handleTermClick = (e: React.MouseEvent<HTMLSpanElement>, term: TaxonomyTerm) => {
    e.stopPropagation()
    const rect = e.currentTarget.getBoundingClientRect()
    setActivePopover((prev) => (prev?.term.id === term.id ? null : { term, rect }))
    triggerTelemetry(term)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLSpanElement>, term: TaxonomyTerm) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      const rect = e.currentTarget.getBoundingClientRect()
      setActivePopover((prev) => (prev?.term.id === term.id ? null : { term, rect }))
      triggerTelemetry(term)
    }
  }

  // If highlighting disabled, invalid input, or no regex, render raw string cleanly
  if (!content || typeof content !== 'string') {
    return null
  }

  if (!highlight || !termsRegex) {
    return <span className={className}>{content}</span>
  }

  // Tokenize and build React element segments
  const elements: React.ReactNode[] = []
  let lastIndex = 0

  for (const match of content.matchAll(termsRegex)) {
    const matchStart = match.index ?? 0
    const matchText = match[0]
    const matchEnd = matchStart + matchText.length

    // Push preceding plain text segment
    if (matchStart > lastIndex) {
      elements.push(content.substring(lastIndex, matchStart))
    }

    const matchedTerm = lookupTerm(matchText)
    if (matchedTerm) {
      const termId = matchedTerm.id
      const isExpanded = activePopover?.term.id === termId
      elements.push(
        <span
          key={`term-${matchStart}-${termId}`}
          className="taxonomy-term"
          data-term-id={termId}
          tabIndex={0}
          role="button"
          aria-haspopup="dialog"
          aria-expanded={isExpanded}
          onMouseEnter={(e) => handleMouseEnter(matchedTerm, e.currentTarget)}
          onMouseLeave={handleMouseLeave}
          onClick={(e) => handleTermClick(e, matchedTerm)}
          onKeyDown={(e) => handleKeyDown(e, matchedTerm)}
          style={{
            borderBottom: '1.5px dotted #58a6ff',
            color: '#79c0ff',
            cursor: 'help',
            padding: '0 2px',
            borderRadius: 3,
            transition: 'background-color 0.15s ease',
            backgroundColor: isExpanded ? 'rgba(88, 166, 255, 0.15)' : 'transparent',
          }}
        >
          {matchText}
        </span>
      )
    } else {
      elements.push(matchText)
    }

    lastIndex = matchEnd
  }

  if (lastIndex < content.length) {
    elements.push(content.substring(lastIndex))
  }

  // Popover positioning calculations (clamped within viewport)
  let popoverStyle: React.CSSProperties = {}
  if (activePopover) {
    const top = Math.min(window.innerHeight - 240, activePopover.rect.bottom + 6)
    const left = Math.max(16, Math.min(window.innerWidth - 340, activePopover.rect.left - 20))
    popoverStyle = {
      position: 'fixed',
      top: `${Math.max(10, top)}px`,
      left: `${left}px`,
      width: '320px',
      maxWidth: '90vw',
      zIndex: 9999,
      background: '#161b22',
      border: '1px solid #388bfd',
      borderRadius: '8px',
      boxShadow: '0 8px 24px rgba(0,0,0,0.6)',
      padding: '12px 14px',
      color: '#c9d1d9',
      fontSize: '12.5px',
      lineHeight: 1.5,
      animation: 'fadeIn 0.12s ease-out',
    }
  }

  return (
    <span ref={containerRef} className={className}>
      {elements}

      {/* Floating Popover Overlay */}
      {activePopover && (
        <div
          role="dialog"
          aria-label={activePopover.term.term}
          style={popoverStyle}
          onClick={(e) => e.stopPropagation()}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
            <div>
              <span style={{ fontWeight: 600, color: '#58a6ff', fontSize: 13.5 }}>
                {activePopover.term.term}
              </span>
              {activePopover.term.layer && (
                <span
                  style={{
                    marginLeft: 6,
                    fontSize: 10,
                    padding: '1px 6px',
                    borderRadius: 10,
                    background: 'rgba(88, 166, 255, 0.15)',
                    color: '#79c0ff',
                    border: '1px solid rgba(88, 166, 255, 0.3)',
                  }}
                >
                  {activePopover.term.layer}
                </span>
              )}
            </div>
            <button
              onClick={() => setActivePopover(null)}
              aria-label="Close tooltip"
              style={{
                background: 'transparent',
                border: 'none',
                color: '#8b949e',
                cursor: 'pointer',
                fontSize: 15,
                lineHeight: 1,
                padding: '0 4px',
              }}
            >
              &times;
            </button>
          </div>

          <p style={{ margin: '4px 0 8px 0', color: '#e6edf3' }}>
            {activePopover.term.definition}
          </p>

          {activePopover.term.source && (
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>
              <b>Source Anchor:</b> {activePopover.term.source}
            </div>
          )}

          {activePopover.term.aliases && activePopover.term.aliases.length > 0 && (
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 6 }}>
              <b>Aliases / Acronyms:</b> {activePopover.term.aliases.join(', ')}
            </div>
          )}

          {activePopover.term.related && activePopover.term.related.length > 0 && (
            <div style={{ marginTop: 6, borderTop: '1px solid #30363d', paddingTop: 6 }}>
              <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>Related Concepts:</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {activePopover.term.related.map((relId) => {
                  const relTerm = lookupTerm(relId)
                  return (
                    <span
                      key={relId}
                      onClick={() => {
                        if (relTerm) {
                          setActivePopover((prev) => (prev ? { ...prev, term: relTerm } : null))
                        }
                      }}
                      style={{
                        fontSize: 10.5,
                        background: '#21262d',
                        border: '1px solid #30363d',
                        padding: '2px 6px',
                        borderRadius: 4,
                        color: '#58a6ff',
                        cursor: relTerm ? 'pointer' : 'default',
                      }}
                    >
                      {relTerm ? relTerm.term : relId}
                    </span>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </span>
  )
}
