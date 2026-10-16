// DocScout Indian Financial Unit Normalizer (FEAT-028)
// Interactive bidirectional conversion between Indian (Lakh/Crore)
// and International (Million/Billion) financial notations, bps, and percentages.

import React, { useState } from 'react'

export interface NormalizedQuantity {
  raw_expression: string
  canonical_value: number
  canonical_unit: string
  currency_symbol?: string | null
  scale_label: string
  scale_multiplier: number
  indian_words: string
  indian_numeric_formatted: string
  international_words: string
  international_numeric_formatted: string
  bps_equivalent?: number | null
  percent_equivalent?: number | null
  synonym_representations: string[]
  is_valid: boolean
}

const PRESET_CONVERSIONS = [
  { label: '₹ 50 Crore vs 500M INR', exprA: '₹ 50 Crore', exprB: '500 Million INR' },
  { label: '175 bps vs 1.75%', exprA: '175 bps', exprB: '1.75%' },
  { label: '₹ 10 Lakh vs 1M INR', exprA: '₹ 10 Lakh', exprB: '1 Million INR' },
  { label: '2.5 Billion vs 250 Crore', exprA: '2.5 Billion', exprB: '250 Crore' },
]

export const FinancialUnitNormalizer: React.FC = () => {
  const [inputExpression, setInputExpression] = useState<string>('₹ 50.5 Crore')
  const [exprA, setExprA] = useState<string>('₹ 50 Crore')
  const [exprB, setExprB] = useState<string>('500 Million INR')
  const [comparisonResult, setComparisonResult] = useState<{
    areEquivalent: boolean
    diff: number
    relDiff: number
  } | null>(null)
  const [normalizedResult, setNormalizedResult] = useState<NormalizedQuantity | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(false)

  const handleNormalize = async (text: string) => {
    setIsLoading(true)
    try {
      const apiKey = localStorage.getItem('docscout_api_key') || ''
      const res = await fetch('/v1/compliance/normalize-units', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': apiKey,
        },
        body: JSON.stringify({ expressions: [text] }),
      })
      if (res.ok) {
        const data = await res.json()
        if (data.results && data.results.length > 0) {
          setNormalizedResult(data.results[0])
        }
      }
    } catch {
      // Local fallback
    } finally {
      setIsLoading(false)
    }
  }

  const handleCompare = async () => {
    try {
      const apiKey = localStorage.getItem('docscout_api_key') || ''
      const res = await fetch('/v1/compliance/compare-quantities', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': apiKey,
        },
        body: JSON.stringify({ expression_a: exprA, expression_b: exprB, tolerance: 0.001 }),
      })
      if (res.ok) {
        const data = await res.json()
        setComparisonResult({
          areEquivalent: data.are_equivalent,
          diff: data.absolute_difference,
          relDiff: data.relative_difference,
        })
      }
    } catch {
      // fallback
    }
  }

  return (
    <div style={{ background: '#0a0f1d', color: '#e2e8f0', padding: '24px', borderRadius: '12px' }}>
      {/* Title */}
      <div style={{ marginBottom: '20px' }}>
        <h2 style={{ fontSize: '1.4rem', fontWeight: 700, margin: 0, color: '#f8fafc' }}>
          Indian Financial Unit Normalizer
        </h2>
        <p style={{ margin: '4px 0 0', color: '#94a3b8', fontSize: '0.85rem' }}>
          Bidirectional scaling between Lakh/Crore, Million/Billion, Basis Points (bps), and canonical floats.
        </p>
      </div>

      {/* Preset Buttons */}
      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '20px' }}>
        {PRESET_CONVERSIONS.map((preset, idx) => (
          <button
            key={idx}
            onClick={() => {
              setExprA(preset.exprA)
              setExprB(preset.exprB)
              setInputExpression(preset.exprA)
              handleNormalize(preset.exprA)
            }}
            style={{
              background: '#0f172a',
              border: '1px solid #1e293b',
              color: '#38bdf8',
              borderRadius: '6px',
              padding: '6px 12px',
              fontSize: '0.8rem',
              cursor: 'pointer',
              fontWeight: 500,
            }}
          >
            {preset.label}
          </button>
        ))}
      </div>

      {/* Interactive Expression Parser */}
      <div style={{ background: '#090d16', border: '1px solid #1e293b', borderRadius: '8px', padding: '16px', marginBottom: '20px' }}>
        <label style={{ fontSize: '0.8rem', color: '#94a3b8', display: 'block', marginBottom: '8px' }}>
          ENTER FINANCIAL QUANTITY (E.G. ₹ 50.5 CR, 150 BPS, 2.5 BILLION USD):
        </label>
        <div style={{ display: 'flex', gap: '10px' }}>
          <input
            type="text"
            value={inputExpression}
            onChange={(e) => setInputExpression(e.target.value)}
            style={{
              flex: 1,
              background: '#0a0f1d',
              border: '1px solid #334155',
              borderRadius: '6px',
              padding: '10px 14px',
              color: '#f8fafc',
              fontSize: '1rem',
              outline: 'none',
            }}
          />
          <button
            onClick={() => handleNormalize(inputExpression)}
            disabled={isLoading}
            style={{
              background: '#0284c7',
              color: '#fff',
              border: 'none',
              borderRadius: '6px',
              padding: '0 20px',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            {isLoading ? 'Converting...' : 'Normalize'}
          </button>
        </div>

        {/* Normalized Output Cards */}
        {normalizedResult && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px', marginTop: '16px' }}>
            <div style={{ background: '#0a0f1d', border: '1px solid #1e293b', borderRadius: '6px', padding: '12px' }}>
              <div style={{ fontSize: '0.7rem', color: '#64748b' }}>CANONICAL SI FLOAT</div>
              <div style={{ fontSize: '1.2rem', fontWeight: 700, color: '#38bdf8', marginTop: '4px' }}>
                {normalizedResult.canonical_value.toLocaleString()}
              </div>
              <div style={{ fontSize: '0.7rem', color: '#94a3b8', marginTop: '2px' }}>
                Unit: {normalizedResult.canonical_unit}
              </div>
            </div>

            <div style={{ background: '#0a0f1d', border: '1px solid #1e293b', borderRadius: '6px', padding: '12px' }}>
              <div style={{ fontSize: '0.7rem', color: '#64748b' }}>INDIAN SYSTEM (LAKH/CRORE)</div>
              <div style={{ fontSize: '1.1rem', fontWeight: 700, color: '#34d399', marginTop: '4px' }}>
                {normalizedResult.indian_words}
              </div>
              <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginTop: '2px' }}>
                {normalizedResult.indian_numeric_formatted}
              </div>
            </div>

            <div style={{ background: '#0a0f1d', border: '1px solid #1e293b', borderRadius: '6px', padding: '12px' }}>
              <div style={{ fontSize: '0.7rem', color: '#64748b' }}>INTERNATIONAL SYSTEM (MN/BN)</div>
              <div style={{ fontSize: '1.1rem', fontWeight: 700, color: '#a78bfa', marginTop: '4px' }}>
                {normalizedResult.international_words}
              </div>
              <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginTop: '2px' }}>
                {normalizedResult.international_numeric_formatted}
              </div>
            </div>

            {(normalizedResult.bps_equivalent !== null || normalizedResult.percent_equivalent !== null) && (
              <div style={{ background: '#0a0f1d', border: '1px solid #1e293b', borderRadius: '6px', padding: '12px' }}>
                <div style={{ fontSize: '0.7rem', color: '#64748b' }}>RATIO SPREAD / BASIS POINTS</div>
                <div style={{ fontSize: '1.1rem', fontWeight: 700, color: '#fbbf24', marginTop: '4px' }}>
                  {normalizedResult.bps_equivalent} bps ({normalizedResult.percent_equivalent}%)
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Equivalence Comparison Box */}
      <div style={{ background: '#090d16', border: '1px solid #1e293b', borderRadius: '8px', padding: '16px' }}>
        <h4 style={{ margin: '0 0 12px', fontSize: '0.9rem', color: '#38bdf8' }}>
          Quantitative Equivalence Test Bench
        </h4>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: '10px', alignItems: 'center' }}>
          <input
            type="text"
            value={exprA}
            onChange={(e) => setExprA(e.target.value)}
            placeholder="Expression A"
            style={{
              background: '#0a0f1d',
              border: '1px solid #334155',
              borderRadius: '6px',
              padding: '8px 12px',
              color: '#f8fafc',
            }}
          />
          <input
            type="text"
            value={exprB}
            onChange={(e) => setExprB(e.target.value)}
            placeholder="Expression B"
            style={{
              background: '#0a0f1d',
              border: '1px solid #334155',
              borderRadius: '6px',
              padding: '8px 12px',
              color: '#f8fafc',
            }}
          />
          <button
            onClick={handleCompare}
            style={{
              background: '#0284c7',
              color: '#fff',
              border: 'none',
              borderRadius: '6px',
              padding: '8px 16px',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Compare
          </button>
        </div>

        {comparisonResult && (
          <div style={{ marginTop: '12px', display: 'flex', alignItems: 'center', gap: '12px' }}>
            <span
              style={{
                padding: '4px 12px',
                borderRadius: '16px',
                fontSize: '0.75rem',
                fontWeight: 700,
                background: comparisonResult.areEquivalent ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)',
                color: comparisonResult.areEquivalent ? '#34d399' : '#f87171',
                border: `1px solid ${comparisonResult.areEquivalent ? 'rgba(16, 185, 129, 0.5)' : 'rgba(239, 68, 68, 0.5)'}`,
              }}
            >
              {comparisonResult.areEquivalent ? 'EQUIVALENT MATCH' : 'DIVERGENT MISMATCH'}
            </span>
            <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
              Absolute Delta: {comparisonResult.diff.toLocaleString()} | Relative Delta: {(comparisonResult.relDiff * 100).toFixed(4)}%
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
export default FinancialUnitNormalizer
