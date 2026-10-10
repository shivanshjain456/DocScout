// DocScout full-stack regulatory research console
// Integrates Auth0 identity (app/api/auth0.py:363 require_authenticated_user),
// Brevo digests (300/d quota per app/digests/brevo_client.py:48),
// OCR.Space inspection (1MB/3p per app/ingest/ocr_space.py:58), and agentic research.
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

interface UserProfile {
  user_id: string
  auth0_sub: string
  email: string
  role: string
  display_name: string
  is_service_key: boolean
}

interface Subscription {
  subscription_id: string
  email: string
  frequency: string
  is_active: boolean
  topics: string[]
  regulators: string[]
  unsubscribe_url?: string
}

interface OCRInspection {
  sha256: string
  status: string
  engine: string
  pages_processed: number
  clean_char_count: number
  extracted_text_sample: string
  latency_ms: number
  error_detail?: string | null
  cached: boolean
}

type TabKey = 'search' | 'identity' | 'digest' | 'ocr' | 'research'

export default function App() {
  const [activeTab, setActiveTab] = useState<TabKey>('search')
  const [apiKey, setApiKey] = useState(() => localStorage.getItem('docscout_api_key') || '')
  const [query, setQuery] = useState('What is the RBI digital lending guideline on first loss default guarantee?')
  const [searchData, setSearchData] = useState<SearchResponse | null>(null)
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchErr, setSearchErr] = useState<string | null>(null)

  // Subsystem states
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [profileErr, setProfileErr] = useState<string | null>(null)

  const [sub, setSub] = useState<Subscription | null>(null)
  const [subConsent, setSubConsent] = useState(true)
  const [subFreq, setSubFreq] = useState('weekly')
  const [subMsg, setSubMsg] = useState<string | null>(null)

  const [ocrDocId, setOcrDocId] = useState('ea4deaf3-5367-5274-8d16-34773447068a')
  const [ocrData, setOcrData] = useState<OCRInspection | null>(null)
  const [ocrMsg, setOcrMsg] = useState<string | null>(null)

  const [researchQuery, setResearchQuery] = useState('Comparative analysis of digital lending norms between RBI and SEBI')
  const [researchReport, setResearchReport] = useState<string | null>(null)
  const [researchLoading, setResearchLoading] = useState(false)

  useEffect(() => {
    localStorage.setItem('docscout_api_key', apiKey)
  }, [apiKey])

  const authHeaders = (): Record<string, string> => {
    const h: Record<string, string> = { 'Content-Type': 'application/json' }
    if (apiKey) {
      if (apiKey.startsWith('Bearer ')) h['Authorization'] = apiKey
      else h['X-API-Key'] = apiKey
    }
    return h
  }

  // 1. Evidence Search
  async function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    setSearchLoading(true)
    setSearchErr(null)
    try {
      const res = await fetch('/v1/search', {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ query, k: 5 }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`)
      const json = await res.json()
      setSearchData({ ...json, requestId: res.headers.get('X-Request-ID') })
    } catch (err: unknown) {
      setSearchErr(err instanceof Error ? err.message : String(err))
    } finally {
      setSearchLoading(false)
    }
  }

  // 2. Auth0 Identity (/v1/user/me)
  async function loadProfile() {
    setProfileErr(null)
    try {
      const res = await fetch('/v1/user/me', { headers: authHeaders() })
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.status === 401 ? 'Unauthenticated (provide Auth0 token or X-API-Key)' : await res.text()}`)
      setProfile(await res.json())
    } catch (err: unknown) {
      setProfileErr(err instanceof Error ? err.message : String(err))
      setProfile(null)
    }
  }

  // 3. Brevo Digests (/v1/subscriptions)
  async function loadSubscription() {
    setSubMsg(null)
    try {
      const res = await fetch('/v1/subscriptions', { headers: authHeaders() })
      if (!res.ok) {
        if (res.status === 404) setSubMsg('No active digest subscription found for this analyst.')
        else throw new Error(`HTTP ${res.status}`)
        setSub(null)
        return
      }
      setSub(await res.json())
    } catch (err: unknown) {
      setSubMsg(err instanceof Error ? err.message : String(err))
    }
  }

  async function saveSubscription() {
    setSubMsg(null)
    try {
      const res = await fetch('/v1/subscriptions', {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({
          frequency: subFreq,
          regulators: ['RBI', 'SEBI'],
          topics: ['ALL'],
          consent: subConsent,
        }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`)
      const data = await res.json()
      setSub(data)
      setSubMsg('Subscription active! Quota: 300/day max. Dedup key: uq_digest_delivery_version.')
    } catch (err: unknown) {
      setSubMsg(err instanceof Error ? err.message : String(err))
    }
  }

  // 4. OCR Inspector (/v1/documents/{id}/ocr)
  async function inspectOCR() {
    setOcrMsg(null)
    setOcrData(null)
    try {
      const res = await fetch(`/v1/documents/${ocrDocId}/ocr`, { headers: authHeaders() })
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`)
      setOcrData(await res.json())
    } catch (err: unknown) {
      setOcrMsg(err instanceof Error ? err.message : String(err))
    }
  }

  async function triggerOCR() {
    setOcrMsg(null)
    try {
      const res = await fetch(`/v1/documents/${ocrDocId}/ocr`, {
        method: 'POST',
        headers: authHeaders(),
      })
      if (!res.ok) {
        if (res.status === 403) throw new Error('HTTP 403: Admin privileges required to trigger OCR extraction')
        throw new Error(`HTTP ${res.status}: ${await res.text()}`)
      }
      setOcrData(await res.json())
      setOcrMsg('OCR extraction triggered via OCR.Space pipeline.')
    } catch (err: unknown) {
      setOcrMsg(err instanceof Error ? err.message : String(err))
    }
  }

  // 5. Agentic Research (/v1/research)
  async function runResearch() {
    setResearchLoading(true)
    setResearchReport(null)
    try {
      const res = await fetch('/v1/research', {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ query: researchQuery, k: 5, max_aspects: 3 }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`)
      const json = await res.json()
      setResearchReport(JSON.stringify(json, null, 2))
    } catch (err: unknown) {
      setResearchReport(`Error: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setResearchLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 960, margin: '0 auto', padding: '24px 20px', fontFamily: 'system-ui, sans-serif', color: '#f0f6fc', background: '#0d1117', minHeight: '100vh' }}>
      <header style={{ borderBottom: '1px solid #30363d', paddingBottom: 16, marginBottom: 20, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
            DocScout Console <span style={{ fontSize: 11, background: 'rgba(88,166,255,0.2)', color: '#58a6ff', padding: '2px 8px', borderRadius: 10 }}>1.0.1 PROD</span>
          </h1>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: '#8b949e' }}>Regulatory RAG over authoritative RBI &amp; SEBI circulars with provenance guard.</p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <input
            type="password"
            placeholder="Bearer token or X-API-Key"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            style={{ padding: '6px 10px', width: 240, background: '#161b22', border: '1px solid #30363d', color: '#f0f6fc', borderRadius: 6, fontSize: 12 }}
          />
          <span style={{ fontSize: 11, color: apiKey ? '#3fb950' : '#8b949e' }}>
            {apiKey ? 'Key Connected' : 'Guest Mode'}
          </span>
        </div>
      </header>

      {/* Navigation tabs */}
      <nav className="nav-tabs" style={{ display: 'flex', gap: 8, borderBottom: '1px solid #30363d', marginBottom: 20 }}>
        <button id="tab-search" onClick={() => setActiveTab('search')} style={{ background: activeTab === 'search' ? '#21262d' : 'transparent', color: activeTab === 'search' ? '#58a6ff' : '#8b949e', border: 'none', borderBottom: activeTab === 'search' ? '2px solid #58a6ff' : 'none', padding: '8px 14px', cursor: 'pointer', fontWeight: 600 }}>Evidence Search</button>
        <button id="tab-identity" onClick={() => { setActiveTab('identity'); loadProfile(); }} style={{ background: activeTab === 'identity' ? '#21262d' : 'transparent', color: activeTab === 'identity' ? '#58a6ff' : '#8b949e', border: 'none', borderBottom: activeTab === 'identity' ? '2px solid #58a6ff' : 'none', padding: '8px 14px', cursor: 'pointer', fontWeight: 600 }}>Auth0 Identity</button>
        <button id="tab-digest" onClick={() => { setActiveTab('digest'); loadSubscription(); }} style={{ background: activeTab === 'digest' ? '#21262d' : 'transparent', color: activeTab === 'digest' ? '#58a6ff' : '#8b949e', border: 'none', borderBottom: activeTab === 'digest' ? '2px solid #58a6ff' : 'none', padding: '8px 14px', cursor: 'pointer', fontWeight: 600 }}>Brevo Digests</button>
        <button id="tab-ocr" onClick={() => setActiveTab('ocr')} style={{ background: activeTab === 'ocr' ? '#21262d' : 'transparent', color: activeTab === 'ocr' ? '#58a6ff' : '#8b949e', border: 'none', borderBottom: activeTab === 'ocr' ? '2px solid #58a6ff' : 'none', padding: '8px 14px', cursor: 'pointer', fontWeight: 600 }}>OCR Inspector</button>
        <button id="tab-research" onClick={() => setActiveTab('research')} style={{ background: activeTab === 'research' ? '#21262d' : 'transparent', color: activeTab === 'research' ? '#58a6ff' : '#8b949e', border: 'none', borderBottom: activeTab === 'research' ? '2px solid #58a6ff' : 'none', padding: '8px 14px', cursor: 'pointer', fontWeight: 600 }}>Agentic Research</button>
      </nav>

      {/* Tab 1: Evidence Search */}
      {activeTab === 'search' && (
        <section>
          <form onSubmit={handleSearch} style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Ask an RBI or SEBI regulatory question..."
              style={{ flex: 1, padding: '10px 14px', fontSize: 14, background: '#161b22', border: '1px solid #30363d', color: '#f0f6fc', borderRadius: 6 }}
            />
            <button type="submit" disabled={searchLoading} style={{ padding: '10px 20px', background: '#58a6ff', color: '#0d1117', border: 'none', borderRadius: 6, fontWeight: 600, cursor: 'pointer' }}>
              {searchLoading ? 'Retrieving...' : 'Search'}
            </button>
          </form>

          {searchErr && <div style={{ color: '#f85149', background: 'rgba(248,81,73,0.1)', border: '1px solid #f85149', padding: 12, borderRadius: 6, marginBottom: 16 }}>{searchErr}</div>}

          {searchData && (
            <div>
              <div style={{ display: 'flex', gap: 16, fontSize: 12, color: '#8b949e', marginBottom: 14 }}>
                <span>Req ID: <code>{searchData.requestId || 'n/a'}</code></span>
                <span>Evidence Coverage: <b>{((searchData.confidence?.evidence_coverage || 0) * 100).toFixed(1)}%</b></span>
                <span style={{ color: searchData.confidence?.low_evidence ? '#d29922' : '#3fb950' }}>{searchData.confidence?.low_evidence ? 'Low Evidence' : 'Citation Grounded'}</span>
              </div>

              <div style={{ display: 'grid', gap: 14 }}>
                {searchData.passages.map((p) => (
                  <article key={p.chunk_id} style={{ border: '1px solid #30363d', background: '#161b22', borderRadius: 8, padding: 16 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8, flexWrap: 'wrap', gap: 8 }}>
                      <a href={p.canonical_url || '#'} target="_blank" rel="noreferrer" style={{ fontWeight: 600, color: '#58a6ff', textDecoration: 'none' }}>
                        #{p.rank} {p.title || p.chunk_id} &#8599;
                      </a>
                      <span style={{ fontSize: 12, color: '#8b949e' }}>{p.published_date || 'Undated'}</span>
                    </div>
                    <p style={{ margin: '8px 0', fontSize: 13.5, lineHeight: 1.55, whiteSpace: 'pre-wrap', color: '#c9d1d9' }}>{p.text}</p>
                    <div style={{ fontSize: 11, color: '#8b949e' }}>
                      Span: [{p.char_start}..{p.char_end}] &middot; Chunk: <code>{p.chunk_id}</code>
                    </div>
                  </article>
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      {/* Tab 2: Auth0 Identity */}
      {activeTab === 'identity' && (
        <section style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 8, padding: 20 }}>
          <h2 style={{ fontSize: 16, marginTop: 0 }}>Analyst Identity Profile (Auth0)</h2>
          <p style={{ color: '#8b949e', fontSize: 13 }}>Validated via <code>PyJWKClient</code> RS256 token verification or service key. Resolves user roles and permissions.</p>

          <button onClick={loadProfile} style={{ padding: '8px 14px', background: '#21262d', border: '1px solid #30363d', color: '#f0f6fc', borderRadius: 6, cursor: 'pointer', marginBottom: 16 }}>
            Refresh Profile (/v1/user/me)
          </button>

          {profileErr && <div style={{ color: '#d29922', background: 'rgba(210,153,34,0.1)', border: '1px solid #d29922', padding: 12, borderRadius: 6 }}>{profileErr}</div>}

          {profile && (
            <div style={{ display: 'grid', gap: 10, fontSize: 13 }}>
              <div><b>User ID:</b> <code>{profile.user_id}</code></div>
              <div><b>Auth0 Sub:</b> <code>{profile.auth0_sub}</code></div>
              <div><b>Email:</b> {profile.email}</div>
              <div><b>Role:</b> <span style={{ background: 'rgba(63,185,80,0.2)', color: '#3fb950', padding: '2px 8px', borderRadius: 8, fontWeight: 600 }}>{profile.role.toUpperCase()}</span></div>
              <div><b>Display Name:</b> {profile.display_name}</div>
              <div><b>Service Key:</b> {profile.is_service_key ? 'Yes' : 'No'}</div>
            </div>
          )}
        </section>
      )}

      {/* Tab 3: Brevo Regulatory Digests */}
      {activeTab === 'digest' && (
        <section style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 8, padding: 20 }}>
          <h2 style={{ fontSize: 16, marginTop: 0 }}>Brevo Personalized Regulatory Digests</h2>
          <p style={{ color: '#8b949e', fontSize: 13 }}>
            Scheduled digest delivery outside synchronous query path. Quota enforced: <b>300/day</b>.
            Unique delivery deduplication invariant: <code>uq_digest_delivery_version</code>.
          </p>

          <div style={{ display: 'flex', gap: 12, alignItems: 'center', margin: '16px 0', flexWrap: 'wrap' }}>
            <label style={{ fontSize: 13 }}>
              Frequency:{' '}
              <select value={subFreq} onChange={(e) => setSubFreq(e.target.value)} style={{ padding: '6px 10px', background: '#0d1117', border: '1px solid #30363d', color: '#f0f6fc', borderRadius: 6 }}>
                <option value="weekly">Weekly Digest</option>
                <option value="daily">Daily Briefing</option>
              </select>
            </label>

            <label style={{ fontSize: 13, display: 'flex', alignItems: 'center', gap: 6 }}>
              <input type="checkbox" checked={subConsent} onChange={(e) => setSubConsent(e.target.checked)} />
              Explicit consent to receive regulatory circular alerts
            </label>
          </div>

          <div style={{ display: 'flex', gap: 10 }}>
            <button onClick={saveSubscription} style={{ padding: '8px 16px', background: '#3fb950', color: '#0d1117', border: 'none', borderRadius: 6, fontWeight: 600, cursor: 'pointer' }}>
              Save Subscription
            </button>
            <button onClick={loadSubscription} style={{ padding: '8px 14px', background: '#21262d', border: '1px solid #30363d', color: '#f0f6fc', borderRadius: 6, cursor: 'pointer' }}>
              Check Status
            </button>
          </div>

          {subMsg && <div style={{ marginTop: 14, padding: 10, background: '#21262d', borderRadius: 6, fontSize: 13 }}>{subMsg}</div>}

          {sub && (
            <div style={{ marginTop: 16, borderTop: '1px solid #30363d', paddingTop: 14, fontSize: 13 }}>
              <div><b>Active:</b> {sub.is_active ? 'Yes' : 'No'} &middot; <b>Recipient:</b> {sub.email}</div>
              <div><b>Regulators:</b> {sub.regulators.join(', ')} &middot; <b>Topics:</b> {sub.topics.join(', ')}</div>
              {sub.unsubscribe_url && (
                <div style={{ marginTop: 8 }}>
                  <span style={{ color: '#8b949e' }}>One-Click Unsubscribe URL: </span>
                  <a href={sub.unsubscribe_url} target="_blank" rel="noreferrer" style={{ color: '#f85149', fontSize: 12 }}>{sub.unsubscribe_url}</a>
                </div>
              )}
            </div>
          )}
        </section>
      )}

      {/* Tab 4: OCR Inspector */}
      {activeTab === 'ocr' && (
        <section style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 8, padding: 20 }}>
          <h2 style={{ fontSize: 16, marginTop: 0 }}>OCR.Space Ingestion Fallback Inspector</h2>
          <p style={{ color: '#8b949e', fontSize: 13 }}>
            Inspect document extraction status and fallback cache. Pre-flight quota limits: <b>1 MB payload / 3 pages</b> (<code>ELIGIBILITY_EXCEEDED</code> rejection).
            Synthetic evaluation fixtures strictly marked <code>is_synthetic</code>.
          </p>

          <div style={{ display: 'flex', gap: 10, margin: '14px 0', flexWrap: 'wrap' }}>
            <input
              value={ocrDocId}
              onChange={(e) => setOcrDocId(e.target.value)}
              placeholder="Document UUID..."
              style={{ flex: 1, minWidth: 280, padding: '8px 12px', background: '#0d1117', border: '1px solid #30363d', color: '#f0f6fc', borderRadius: 6, fontSize: 13 }}
            />
            <button onClick={inspectOCR} style={{ padding: '8px 14px', background: '#58a6ff', color: '#0d1117', border: 'none', borderRadius: 6, fontWeight: 600, cursor: 'pointer' }}>
              Inspect Status
            </button>
            <button onClick={triggerOCR} style={{ padding: '8px 14px', background: '#21262d', border: '1px solid #30363d', color: '#f0f6fc', borderRadius: 6, cursor: 'pointer' }}>
              Trigger OCR (Admin)
            </button>
          </div>

          {ocrMsg && <div style={{ padding: 10, background: '#21262d', borderRadius: 6, fontSize: 13 }}>{ocrMsg}</div>}

          {ocrData && (
            <div style={{ marginTop: 14, borderTop: '1px solid #30363d', paddingTop: 14, fontSize: 13, display: 'grid', gap: 8 }}>
              <div><b>SHA256:</b> <code>{ocrData.sha256}</code></div>
              <div><b>Status:</b> <span style={{ color: ocrData.status === 'SUCCESS' ? '#3fb950' : '#d29922', fontWeight: 600 }}>{ocrData.status}</span> &middot; <b>Engine:</b> {ocrData.engine} &middot; <b>Cached:</b> {ocrData.cached ? 'Yes' : 'No'}</div>
              <div><b>Pages Processed:</b> {ocrData.pages_processed} &middot; <b>Clean Chars:</b> {ocrData.clean_char_count} &middot; <b>Latency:</b> {ocrData.latency_ms.toFixed(1)} ms</div>
              {ocrData.error_detail && <div style={{ color: '#f85149' }}><b>Error:</b> {ocrData.error_detail}</div>}
              {ocrData.extracted_text_sample && (
                <div style={{ background: '#0d1117', padding: 10, borderRadius: 6, marginTop: 6 }}>
                  <div style={{ color: '#8b949e', fontSize: 11, marginBottom: 4 }}>Extracted Sample:</div>
                  <pre style={{ margin: 0, fontSize: 12, whiteSpace: 'pre-wrap', color: '#c9d1d9' }}>{ocrData.extracted_text_sample}</pre>
                </div>
              )}
            </div>
          )}
        </section>
      )}

      {/* Tab 5: Agentic Research */}
      {activeTab === 'research' && (
        <section style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 8, padding: 20 }}>
          <h2 style={{ fontSize: 16, marginTop: 0 }}>Deterministic Agentic Research &amp; Workspaces</h2>
          <p style={{ color: '#8b949e', fontSize: 13 }}>
            Executes deterministic plan &rarr; retrieve &rarr; synthesize &rarr; critique loop (ADR-0021).
            Stored research artifacts accessible at <code>/v1/workspaces/&#123;id&#125;/artifacts</code>.
          </p>

          <div style={{ display: 'flex', gap: 10, margin: '14px 0' }}>
            <input
              value={researchQuery}
              onChange={(e) => setResearchQuery(e.target.value)}
              placeholder="Multi-aspect regulatory research query..."
              style={{ flex: 1, padding: '8px 12px', background: '#0d1117', border: '1px solid #30363d', color: '#f0f6fc', borderRadius: 6, fontSize: 13 }}
            />
            <button onClick={runResearch} disabled={researchLoading} style={{ padding: '8px 16px', background: '#58a6ff', color: '#0d1117', border: 'none', borderRadius: 6, fontWeight: 600, cursor: 'pointer' }}>
              {researchLoading ? 'Synthesizing...' : 'Run Research'}
            </button>
          </div>

          {researchReport && (
            <div style={{ background: '#0d1117', padding: 12, borderRadius: 6, border: '1px solid #30363d', overflowX: 'auto' }}>
              <pre style={{ margin: 0, fontSize: 12, color: '#c9d1d9' }}>{researchReport}</pre>
            </div>
          )}
        </section>
      )}
    </div>
  )
}
