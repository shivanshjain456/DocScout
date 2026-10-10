// DocScout minimal citation-grounded regulatory search console
import { useState, useEffect } from 'react'

interface Passage {
  rank: number
  chunk_id: string
  title?: string | null
  published_date?: string | null
  canonical_url?: string | null
  text: string
  char_start: number
  char_end: number
}

interface SearchResponse {
  passages: Passage[]
  confidence?: { evidence_coverage: number; low_evidence: boolean }
  requestId?: string | null
}

export default function App() {
  const [apiKey, setApiKey] = useState(() => localStorage.getItem('docscout_api_key') || '')
  const [query, setQuery] = useState('What are the KYC requirements for foreign portfolio investors?')
  const [data, setData] = useState<SearchResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    localStorage.setItem('docscout_api_key', apiKey)
  }, [apiKey])

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setErr(null)
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (apiKey) headers['X-API-Key'] = apiKey
      const res = await fetch('/v1/search', {
        method: 'POST',
        headers,
        body: JSON.stringify({ query, k: 5 }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`)
      const json = await res.json()
      setData({ ...json, requestId: res.headers.get('X-Request-ID') })
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 960, margin: '0 auto', padding: 24, fontFamily: 'system-ui, sans-serif' }}>
      <header style={{ borderBottom: '1px solid #30363d', paddingBottom: 16, marginBottom: 20 }}>
        <h2>DocScout Console <span style={{ fontSize: 12, opacity: 0.7 }}>1.0.0</span></h2>
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <input
            type="password"
            placeholder="X-API-Key"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            style={{ padding: '6px 10px', width: 260 }}
          />
          <span style={{ fontSize: 12, alignSelf: 'center', color: '#888' }}>
            {apiKey ? 'API Key Active' : 'No Key (Public Search)'}
          </span>
        </div>
      </header>

      <form onSubmit={handleSearch} style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Regulatory query..."
          style={{ flex: 1, padding: '8px 12px', fontSize: 14 }}
        />
        <button type="submit" disabled={loading} style={{ padding: '8px 16px', fontWeight: 600 }}>
          {loading ? 'Searching...' : 'Search'}
        </button>
      </form>

      {err && <div style={{ color: '#f85149', marginBottom: 16 }}>{err}</div>}

      {data && (
        <section>
          <div style={{ display: 'flex', gap: 16, fontSize: 12, color: '#888', marginBottom: 12 }}>
            <span>Req ID: {data.requestId || 'n/a'}</span>
            <span>Coverage: {((data.confidence?.evidence_coverage || 0) * 100).toFixed(1)}%</span>
            <span>Status: {data.confidence?.low_evidence ? 'Low Evidence' : 'Grounded'}</span>
          </div>

          <div style={{ display: 'grid', gap: 12 }}>
            {data.passages.map((p) => (
              <article key={p.chunk_id} style={{ border: '1px solid #30363d', borderRadius: 6, padding: 14 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                  <a href={p.canonical_url || '#'} target="_blank" rel="noreferrer" style={{ fontWeight: 600, color: '#58a6ff' }}>
                    #{p.rank} {p.title || p.chunk_id}
                  </a>
                  <span style={{ fontSize: 12, color: '#888' }}>{p.published_date || 'Undated'}</span>
                </div>
                <p style={{ margin: '8px 0', fontSize: 13, lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>{p.text}</p>
                <div style={{ fontSize: 11, color: '#888' }}>
                  Span: [{p.char_start}..{p.char_end}] · ID: {p.chunk_id}
                </div>
              </article>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
