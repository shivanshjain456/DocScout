"""The complete, self-contained DocScout regulatory analyst console.

Self-contained with zero external stylesheets, CDNs, or third-party scripts.
Operates reliably in sandboxed evaluation environments, provides full accessible UI
connecting identity (Auth0 / API keys), search & grounded citations, analyst watchlists,
Brevo regulatory digests with one-click unsubscribe, OCR.Space document inspection, and
live regulatory discovery.
"""

from __future__ import annotations

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DocScout  -  Indian Regulatory Research Console</title>
<style>
  :root {
    --bg: #0d1117;
    --panel: #161b22;
    --panel-border: #30363d;
    --panel-subtle: #21262d;
    --ink: #f0f6fc;
    --dim: #8b949e;
    --accent: #58a6ff;
    --accent-hover: #388bfd;
    --accent-subtle: rgba(56, 139, 253, 0.15);
    --good: #3fb950;
    --good-subtle: rgba(63, 185, 80, 0.15);
    --warn: #d29922;
    --warn-subtle: rgba(210, 153, 34, 0.15);
    --danger: #f85149;
    --danger-subtle: rgba(248, 81, 73, 0.15);
    --rbi: #58a6ff;
    --sebi: #3fb950;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--ink);
    font: 14px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    padding-bottom: 60px;
  }
  .wrap { max-width: 1040px; margin: 0 auto; padding: 24px 20px; }
  header {
    display: flex; justify-content: space-between; align-items: flex-start;
    border-bottom: 1px solid var(--panel-border); padding-bottom: 16px; margin-bottom: 20px;
    flex-wrap: wrap; gap: 16px;
  }
  .brand h1 { font-size: 20px; font-weight: 700; letter-spacing: -0.02em; display: flex; align-items: center; gap: 8px; }
  .brand .tagline { color: var(--dim); font-size: 13px; margin-top: 4px; }
  .auth-box {
    background: var(--panel); border: 1px solid var(--panel-border); border-radius: 8px;
    padding: 10px 14px; display: flex; flex-direction: column; gap: 8px; min-width: 340px;
  }
  .auth-row { display: flex; gap: 8px; align-items: center; }
  .auth-status {
    font-size: 12px; display: flex; align-items: center; justify-content: space-between;
    gap: 8px; padding-top: 4px; border-top: 1px solid var(--panel-border);
  }
  .nav-tabs {
    display: flex; gap: 6px; border-bottom: 1px solid var(--panel-border); margin-bottom: 20px;
    overflow-x: auto;
  }
  .tab-btn {
    background: transparent; color: var(--dim); border: none; border-bottom: 2px solid transparent;
    padding: 10px 14px; font-size: 13px; font-weight: 600; cursor: pointer; border-radius: 6px 6px 0 0;
    white-space: nowrap; transition: color 0.15s, border-color 0.15s;
  }
  .tab-btn:hover { color: var(--ink); }
  .tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); background: var(--panel-subtle); }

  .tab-pane { display: none; }
  .tab-pane.active { display: block; }

  .panel {
    background: var(--panel); border: 1px solid var(--panel-border); border-radius: 8px;
    padding: 18px 20px; margin-bottom: 20px;
  }
  .panel h2 { font-size: 16px; font-weight: 600; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
  .panel p.desc { color: var(--dim); font-size: 13px; margin-bottom: 16px; }

  label { display: block; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: var(--dim); margin-bottom: 6px; }
  input, select, textarea {
    width: 100%; background: var(--bg); color: var(--ink); border: 1px solid var(--panel-border);
    border-radius: 6px; padding: 8px 12px; font: inherit; transition: border-color 0.15s;
  }
  input:focus, select:focus, textarea:focus { outline: none; border-color: var(--accent); }
  .row { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
  .row > div { flex: 1; min-width: 140px; }

  button.btn {
    background: var(--accent); color: #0d1117; border: none; border-radius: 6px;
    padding: 8px 16px; font-weight: 600; font-size: 13px; cursor: pointer; transition: opacity 0.15s;
    display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  }
  button.btn:hover { opacity: 0.9; }
  button.btn:disabled { opacity: 0.5; cursor: not-allowed; }
  button.btn-sec {
    background: var(--panel-subtle); color: var(--ink); border: 1px solid var(--panel-border);
  }
  button.btn-sec:hover { background: var(--panel-border); }
  button.btn-danger {
    background: var(--danger-subtle); color: var(--danger); border: 1px solid var(--danger);
  }

  .pill {
    display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px;
    border-radius: 12px; font-size: 11px; font-weight: 600; text-transform: uppercase;
  }
  .pill-rbi { background: rgba(88, 166, 255, 0.18); color: var(--rbi); border: 1px solid rgba(88, 166, 255, 0.3); }
  .pill-sebi { background: rgba(63, 185, 80, 0.18); color: var(--sebi); border: 1px solid rgba(63, 185, 80, 0.3); }
  .pill-admin { background: rgba(210, 153, 34, 0.18); color: var(--warn); border: 1px solid rgba(210, 153, 34, 0.3); }
  .pill-reader { background: rgba(139, 148, 158, 0.18); color: var(--dim); border: 1px solid rgba(139, 148, 158, 0.3); }

  .hit {
    background: var(--panel); border: 1px solid var(--panel-border); border-radius: 8px;
    padding: 16px 18px; margin-bottom: 12px; transition: border-color 0.15s;
  }
  .hit:hover { border-color: #484f58; }
  .hit-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; flex-wrap: wrap; gap: 8px; }
  .hit-title { font-size: 14px; font-weight: 600; color: var(--ink); flex: 1; }
  .hit-badges { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  .hit-meta { font-size: 12px; color: var(--dim); margin-bottom: 8px; font-family: ui-monospace, Menlo, monospace; }
  .hit-body { font-size: 13.5px; line-height: 1.55; white-space: pre-wrap; background: var(--bg); padding: 12px; border-radius: 6px; border: 1px solid var(--panel-border); }
  .hit-actions { margin-top: 10px; display: flex; gap: 8px; align-items: center; font-size: 12px; }

  .empty-state {
    text-align: center; padding: 40px 20px; color: var(--dim);
    background: var(--panel-subtle); border-radius: 8px; border: 1px dashed var(--panel-border);
  }

  .preset-queries { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
  .preset-btn {
    background: var(--panel-subtle); border: 1px solid var(--panel-border); color: var(--dim);
    font-size: 11px; padding: 3px 8px; border-radius: 4px; cursor: pointer;
  }
  .preset-btn:hover { color: var(--accent); border-color: var(--accent); }

  .interests-cloud { display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0; }
  .interest-tag {
    background: var(--panel-subtle); border: 1px solid var(--panel-border); border-radius: 6px;
    padding: 4px 10px; font-size: 12px; display: flex; align-items: center; gap: 6px;
  }
  .interest-tag button {
    background: none; border: none; color: var(--danger); cursor: pointer; font-weight: 700;
  }

  table.data-table {
    width: 100%; border-collapse: collapse; font-size: 12.5px; text-align: left;
  }
  table.data-table th, table.data-table td {
    padding: 8px 12px; border-bottom: 1px solid var(--panel-border);
  }
  table.data-table th { background: var(--panel-subtle); color: var(--dim); font-weight: 600; }
  table.data-table tr:hover { background: var(--panel-subtle); }

  .notice-box {
    padding: 12px 14px; border-radius: 6px; font-size: 13px; margin-bottom: 16px;
    display: flex; gap: 10px; align-items: flex-start;
  }
  .notice-info { background: var(--accent-subtle); border: 1px solid rgba(88, 166, 255, 0.3); color: var(--accent); }
  .notice-good { background: var(--good-subtle); border: 1px solid rgba(63, 185, 80, 0.3); color: var(--good); }
  .notice-warn { background: var(--warn-subtle); border: 1px solid rgba(210, 153, 34, 0.3); color: var(--warn); }
  .notice-danger { background: var(--danger-subtle); border: 1px solid rgba(248, 81, 73, 0.3); color: var(--danger); }

  footer {
    margin-top: 36px; padding-top: 16px; border-top: 1px solid var(--panel-border);
    color: var(--dim); font-size: 12px; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px;
  }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand">
      <h1>DocScout <span class="pill pill-rbi" style="font-size:10px;">REGULATORY INTEL</span></h1>
      <p class="tagline">Citation-grounded research over authoritative RBI &amp; SEBI regulatory circulars.</p>
    </div>
    <div class="auth-box">
      <div class="auth-row">
        <input id="authToken" type="password" placeholder="Auth0 Bearer Token or X-API-Key" autocomplete="off" spellcheck="false" style="font-size:12px;">
        <button id="btnConnect" class="btn btn-sec" style="font-size:12px; white-space:nowrap;">Connect</button>
      </div>
      <div class="auth-status">
        <span id="authPill" class="pill pill-reader">GUEST / UNAUTHENTICATED</span>
        <span id="authEmail" style="color:var(--dim); font-size:11px;">Public Search Only</span>
      </div>
    </div>
  </header>

  <nav class="nav-tabs" role="tablist">
    <button class="tab-btn active" data-tab="tab-search">Evidence Search</button>
    <button class="tab-btn" data-tab="tab-interests">Analyst Watchlist</button>
    <button class="tab-btn" data-tab="tab-digests">Brevo Digests</button>
    <button class="tab-btn" data-tab="tab-ocr">OCR Inspector</button>
    <button class="tab-btn" data-tab="tab-discovery">Corpus Freshness &amp; Discovery</button>
  </nav>

  <!-- TAB 1: EVIDENCE SEARCH -->
  <main>
  <div id="tab-search" class="tab-pane active">
    <div class="panel">
      <h2>Regulatory Document Search</h2>
      <p class="desc">Every answer quotes verified spans traceable to authoritative regulator publications. Synthetic test fixtures and injection canaries are permanently excluded.</p>

      <div>
        <label for="q">Query / Research Question</label>
        <input id="q" value="What are the KYC requirements for foreign portfolio investors?">
        <div class="preset-queries">
          <span style="font-size:11px; color:var(--dim); align-self:center;">Presets:</span>
          <button class="preset-btn" data-q="What are the KYC requirements for foreign portfolio investors?">FPI KYC Norms</button>
          <button class="preset-btn" data-q="What are the capital adequacy norms and risk weights for banks?">Basel III Capital Adequacy</button>
          <button class="preset-btn" data-q="What is the timeframe for resolution of customer complaints in digital payments?">Digital Payment Complaints</button>
        </div>
      </div>

      <div class="row" style="margin-top: 14px;">
        <div>
          <label for="mode">Retrieval Mode</label>
          <select id="mode">
            <option value="hybrid">Hybrid (BM25 + Dense RRF)</option>
            <option value="dense">Dense Only (bge-small-en-v1.5)</option>
            <option value="bm25">BM25 Lexical Only</option>
          </select>
        </div>
        <div>
          <label for="k">Passages (k)</label>
          <input id="k" type="number" value="5" min="1" max="20">
        </div>
        <div>
          <label for="cache">Result Cache</label>
          <select id="cache">
            <option value="true">Use Cache</option>
            <option value="false">Bypass Cache</option>
          </select>
        </div>
      </div>

      <button id="btnSearch" class="btn">Search Evidence</button>
    </div>

    <div id="searchMeta" style="margin-bottom: 12px; font-size: 13px; color: var(--dim);"></div>
    <div id="searchResults"></div>
  </div>

  <!-- TAB 2: ANALYST WATCHLIST (INTERESTS) -->
  <div id="tab-interests" class="tab-pane">
    <div class="panel">
      <h2>Analyst Research Watchlists</h2>
      <p class="desc">Save specific regulatory focus areas under your individual analyst identity. Your interests determine which circulars are routed to your personalized regulatory digests.</p>

      <div id="interestAuthNotice" class="notice-box notice-warn" style="display:none;">
        <span>Please authenticate with an Auth0 Bearer token or API key above to load and manage your saved analyst watchlists.</span>
      </div>

      <div id="interestsSection">
        <label>Saved Regulatory Topics</label>
        <div id="interestsList" class="interests-cloud"></div>

        <div class="row" style="margin-top: 16px; max-width: 480px;">
          <div>
            <label for="newTopic">Add Research Interest Topic</label>
            <input id="newTopic" placeholder="e.g. KYC, FPI, CAPITAL_ADEQUACY, AML">
          </div>
        </div>
        <button id="btnAddInterest" class="btn">Add Topic to Watchlist</button>
      </div>
    </div>
  </div>

  <!-- TAB 3: REGULATORY DIGESTS (BREVO) -->
  <div id="tab-digests" class="tab-pane">
    <div class="panel">
      <h2>Brevo Personalized Regulatory Digests</h2>
      <p class="desc">Subscribe to grounded, authoritative regulatory digests. Notifications are delivered outside the synchronous search path, respect strict quotas (300/day), and provide tamper-proof one-click unsubscribe.</p>

      <div id="digestAuthNotice" class="notice-box notice-warn" style="display:none;">
        <span>Please authenticate above to manage your personal email digest subscription.</span>
      </div>

      <div id="digestSection">
        <div id="subStatusBox" class="notice-box notice-info" style="display:none;"></div>

        <div class="row">
          <div>
            <label for="subFreq">Delivery Frequency</label>
            <select id="subFreq">
              <option value="weekly">Weekly Digest</option>
              <option value="daily">Daily Briefing</option>
              <option value="immediate">Immediate Publication Alert</option>
            </select>
          </div>
          <div>
            <label for="subReg">Regulator Coverage</label>
            <select id="subReg">
              <option value="ALL">All Regulators (RBI + SEBI)</option>
              <option value="RBI">Reserve Bank of India (RBI) Only</option>
              <option value="SEBI">Securities and Exchange Board of India (SEBI) Only</option>
            </select>
          </div>
        </div>

        <div style="margin-bottom: 14px;">
          <label for="subTopics">Filter Topics (comma-separated or "ALL")</label>
          <input id="subTopics" value="ALL" placeholder="ALL or KYC, FPI, RISK">
        </div>

        <div style="margin-bottom: 18px;">
          <label style="display:flex; align-items:center; gap:8px; cursor:pointer; text-transform:none; font-size:13px; color:var(--ink);">
            <input id="subConsent" type="checkbox" style="width:auto;">
            I explicitly consent to receive grounded regulatory digests and alerts at my registered email address.
          </label>
        </div>

        <div style="display:flex; gap:10px; flex-wrap:wrap;">
          <button id="btnSaveSub" class="btn">Save Subscription</button>
          <button id="btnUnsub" class="btn btn-danger" style="display:none;">One-Click Unsubscribe</button>
          <button id="btnDispatchAdmin" class="btn btn-sec" style="display:none;">Admin: Dispatch Pending Digests</button>
        </div>
      </div>
    </div>
  </div>

  <!-- TAB 4: OCR INSPECTOR (OCR.SPACE) -->
  <div id="tab-ocr" class="tab-pane">
    <div class="panel">
      <h2>OCR.Space Ingestion Fallback Inspector</h2>
      <p class="desc">Inspect document extraction fidelity. For scanned public PDFs where ordinary extraction yields insufficient clean characters, DocScout triggers OCR.Space within verified limits (1 MB / 3 pages).</p>

      <div class="row">
        <div style="flex: 2 1 200px;">
          <label for="ocrDocId">Document ID (UUID)</label>
          <input id="ocrDocId" placeholder="e.g. 7f59d571-0814-411a-8b89-251fce8d5382">
        </div>
      </div>

      <div style="display:flex; gap:10px; flex-wrap:wrap; margin-bottom:16px;">
        <button id="btnInspectOCR" class="btn">Inspect Extraction Status</button>
        <button id="btnTriggerOCR" class="btn btn-sec">Trigger OCR Fallback</button>
      </div>

      <div id="ocrReport" style="display:none;"></div>
    </div>
  </div>

  <!-- TAB 5: DISCOVERY & CORPUS FRESHNESS -->
  <div id="tab-discovery" class="tab-pane">
    <div class="panel">
      <h2>Regulatory Corpus Freshness &amp; Ongoing Discovery</h2>
      <p class="desc">Active discovery crawls authoritative publication listings from RBI and SEBI, identifying new circulars, supersessions, and revisions without altering raw evidence provenance.</p>

      <div class="notice-box notice-info">
        <strong>Evidence Integrity Guarantee:</strong> Synthetic evaluation fixtures and injection canaries are marked with <code>is_synthetic = true</code> and are permanently excluded from production retrieval and email digests.
      </div>

      <div style="display:flex; gap:10px; flex-wrap:wrap; margin-bottom:16px;">
        <button id="btnRunDiscovery" class="btn">Run Live Discovery Crawl</button>
        <button id="btnCheckHealth" class="btn btn-sec">Check System Health</button>
      </div>

      <div id="discoveryStatus" style="font-size:13px; color:var(--dim); margin-bottom:12px;"></div>
      <div id="discoveryResults"></div>
    </div>
  </div>
  </main>

  <footer>
    <div>
      DocScout Production Service &middot; Powered by PostgreSQL 18 &amp; pgvector
      &middot; <a href="/docs">OpenAPI Documentation</a> &middot; <a href="/healthz">Health Endpoint</a>
    </div>
    <div style="color:var(--dim);">
      Integrations: Auth0 (OAuth2/OIDC) &middot; Brevo (Sendinblue v3) &middot; OCR.Space
    </div>
  </footer>
</div>

<script>
(function() {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  let currentAuth = localStorage.getItem('docscout_auth_token') || '';
  let currentUser = null;

  // Tabs navigation
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      const target = $(btn.getAttribute('data-tab'));
      if (target) target.classList.add('active');

      if (btn.getAttribute('data-tab') === 'tab-interests') loadInterests();
      if (btn.getAttribute('data-tab') === 'tab-digests') loadSubscription();
    });
  });

  // Preset queries
  document.querySelectorAll('.preset-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      $('q').value = btn.getAttribute('data-q');
      runSearch();
    });
  });

  // Headers helper
  function getHeaders() {
    const headers = { 'Content-Type': 'application/json' };
    if (currentAuth) {
      if (currentAuth.startsWith('ey')) {
        headers['Authorization'] = 'Bearer ' + currentAuth;
      } else {
        headers['X-API-Key'] = currentAuth;
      }
    }
    return headers;
  }

  // Auth Connect
  async function connectAuth() {
    const token = $('authToken').value.trim();
    currentAuth = token;
    localStorage.setItem('docscout_auth_token', token);
    await checkUserSession();
  }

  async function checkUserSession() {
    if (!currentAuth) {
      $('authPill').className = 'pill pill-reader';
      $('authPill').textContent = 'GUEST';
      $('authEmail').textContent = 'Public Search Only';
      currentUser = null;
      $('interestAuthNotice').style.display = 'block';
      $('digestAuthNotice').style.display = 'block';
      $('btnDispatchAdmin').style.display = 'none';
      return;
    }

    try {
      const res = await fetch('/v1/user/me', { headers: getHeaders() });
      if (res.ok) {
        currentUser = await res.json();
        const isAdmin = currentUser.role === 'admin';
        $('authPill').className = isAdmin ? 'pill pill-admin' : 'pill pill-reader';
        $('authPill').textContent = currentUser.role.toUpperCase();
        $('authEmail').textContent = currentUser.email;
        $('interestAuthNotice').style.display = 'none';
        $('digestAuthNotice').style.display = 'none';
        if (isAdmin) $('btnDispatchAdmin').style.display = 'inline-flex';
      } else {
        $('authPill').className = 'pill pill-reader';
        $('authPill').textContent = 'INVALID TOKEN';
        $('authEmail').textContent = 'Authentication Failed';
        currentUser = null;
      }
    } catch (e) {
      $('authPill').textContent = 'OFFLINE';
    }
  }

  $('btnConnect').addEventListener('click', connectAuth);
  $('authToken').value = currentAuth;
  if (currentAuth) checkUserSession();

  // 1. Evidence Search
  async function runSearch() {
    const q = $('q').value.trim();
    if (!q) return;
    const meta = $('searchMeta'), out = $('searchResults'), btn = $('btnSearch');
    out.innerHTML = '';
    meta.textContent = 'Searching regulatory corpus\\u2026';
    btn.disabled = true;

    try {
      const res = await fetch('/v1/search', {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          query: q,
          k: Number($('k').value),
          mode: $('mode').value,
          use_cache: $('cache').value === 'true'
        })
      });

      const data = await res.json();
      if (!res.ok) {
        meta.textContent = '';
        out.innerHTML = '<div class="notice-box notice-danger"><b>' + res.status + ':</b> ' + esc(data.detail || 'Search request failed') + '</div>';
        return;
      }

      const t = data.timings;
      meta.innerHTML = '<span style="color:var(--good);font-weight:600;">' + data.passages.length + ' passages</span> returned in ' +
        t.total_ms.toFixed(1) + ' ms ' +
        (t.cache_hit ? '(cache hit)' : '(retrieval ' + t.retrieval_ms.toFixed(1) + ' ms)') +
        ' &middot; Embedder: ' + esc(data.provenance.embedding_model) +
        ' &middot; Active corpus: ' + data.provenance.corpus_chunks + ' chunks';

      if (!data.passages.length) {
        out.innerHTML = '<div class="empty-state">No authoritative circulars matched this question in the verified corpus.</div>';
        return;
      }

      out.innerHTML = data.passages.map(p => {
        const sourcePill = p.source === 'RBI' ? 'pill-rbi' : 'pill-sebi';
        const sourceLink = p.canonical_url
          ? ' <a href="' + esc(p.canonical_url) + '" target="_blank" rel="noopener noreferrer">&#8599; Authoritative Source</a>' : '';

        return '<div class="hit">' +
          '<div class="hit-header">' +
            '<div class="hit-title">' + esc(p.title || 'Untitled Circular') +
              (p.published_date ? ' <span style="font-weight:normal;color:var(--dim);font-size:12px;">(' + esc(p.published_date) + ')</span>' : '') +
            '</div>' +
            '<div class="hit-badges">' +
              '<span class="pill ' + sourcePill + '">' + esc(p.source) + '</span>' +
              '<span class="pill pill-reader">Rank #' + p.rank + '</span>' +
              '<span class="pill pill-reader">Score ' + p.score.toFixed(4) + '</span>' +
            '</div>' +
          '</div>' +
          '<div class="hit-meta">' +
            'Chunk ID: ' + esc(p.chunk_id) + ' &middot; Span: chars ' + p.char_start + '&#8211;' + p.char_end +
          '</div>' +
          '<div class="hit-body">' + esc(p.text) + '</div>' +
          '<div class="hit-actions">' +
            sourceLink +
            ' &middot; <a href="#" onclick="inspectDoc(\\'' + esc(p.document_id || '') + '\\'); return false;">Inspect Ingestion &amp; OCR</a>' +
          '</div>' +
        '</div>';
      }).join('');
    } catch (e) {
      meta.textContent = '';
      out.innerHTML = '<div class="notice-box notice-danger">' + esc(String(e)) + '</div>';
    } finally {
      btn.disabled = false;
    }
  }

  $('btnSearch').addEventListener('click', runSearch);
  $('q').addEventListener('keydown', e => { if (e.key === 'Enter') runSearch(); });

  window.inspectDoc = function(docId) {
    if (!docId) return;
    $('ocrDocId').value = docId;
    document.querySelector('[data-tab="tab-ocr"]').click();
    inspectOCR();
  };

  // 2. Analyst Watchlist
  async function loadInterests() {
    if (!currentAuth) return;
    const list = $('interestsList');
    list.innerHTML = '<span style="color:var(--dim);font-size:12px;">Loading watchlists\\u2026</span>';

    try {
      const res = await fetch('/v1/user/interests', { headers: getHeaders() });
      if (!res.ok) {
        list.innerHTML = '<span style="color:var(--danger);font-size:12px;">Failed to load watchlists.</span>';
        return;
      }
      const data = await res.json();
      if (!data.topics.length) {
        list.innerHTML = '<span style="color:var(--dim);font-size:12px;">No research interests saved yet.</span>';
        return;
      }
      list.innerHTML = data.topics.map(t =>
        '<div class="interest-tag">' +
          '<span>' + esc(t) + '</span>' +
          '<button onclick="removeInterest(\\'' + esc(t) + '\\')">&times;</button>' +
        '</div>'
      ).join('');
    } catch (e) {
      list.innerHTML = '<span style="color:var(--danger);font-size:12px;">Error: ' + esc(String(e)) + '</span>';
    }
  }

  window.removeInterest = async function(topic) {
    try {
      const res = await fetch('/v1/user/interests/' + encodeURIComponent(topic), {
        method: 'DELETE',
        headers: getHeaders()
      });
      if (res.ok) loadInterests();
    } catch (e) {
      alert('Failed to remove topic: ' + e);
    }
  };

  $('btnAddInterest').addEventListener('click', async () => {
    const topic = $('newTopic').value.trim();
    if (!topic) return;
    try {
      const res = await fetch('/v1/user/interests', {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ topics: [topic] })
      });
      if (res.ok) {
        $('newTopic').value = '';
        loadInterests();
      } else {
        const err = await res.json();
        alert('Error: ' + (err.detail || 'Could not add topic'));
      }
    } catch (e) {
      alert('Error: ' + e);
    }
  });

  // 3. Brevo Digests & Subscriptions
  async function loadSubscription() {
    if (!currentAuth) return;
    const box = $('subStatusBox');
    try {
      const res = await fetch('/v1/subscriptions', { headers: getHeaders() });
      if (res.ok) {
        const sub = await res.json();
        box.style.display = 'block';
        box.className = sub.is_active ? 'notice-box notice-good' : 'notice-box notice-warn';
        box.innerHTML = '<div>' +
          '<strong>Subscription: ' + (sub.is_active ? 'ACTIVE' : 'PAUSED') + '</strong><br>' +
          'Frequency: <code>' + esc(sub.frequency) + '</code> &middot; Recipient: ' + esc(sub.email) + '<br>' +
          'Topics: ' + esc(sub.topics.join(', ')) + ' &middot; Regulators: ' + esc(sub.regulators.join(', ')) + '<br>' +
          '<a href="' + esc(sub.unsubscribe_url) + '" target="_blank">One-Click Unsubscribe Link</a>' +
        '</div>';
        $('subFreq').value = sub.frequency;
        $('subTopics').value = sub.topics.join(', ');
        $('subConsent').checked = true;
        $('btnUnsub').style.display = sub.is_active ? 'inline-flex' : 'none';
        $('btnUnsub').setAttribute('data-token', sub.unsubscribe_token);
      } else if (res.status === 404) {
        box.style.display = 'block';
        box.className = 'notice-box notice-info';
        box.textContent = 'No active subscription found. Configure your preferences and consent below to start receiving digests.';
        $('btnUnsub').style.display = 'none';
      }
    } catch (e) {
      box.style.display = 'block';
      box.className = 'notice-box notice-danger';
      box.textContent = 'Error checking subscription: ' + e;
    }
  }

  $('btnSaveSub').addEventListener('click', async () => {
    if (!$('subConsent').checked) {
      alert('Explicit consent is required to activate regulatory digests.');
      return;
    }
    const topics = $('subTopics').value.split(',').map(s => s.trim()).filter(Boolean);
    const regs = $('subReg').value === 'ALL' ? ['ALL'] : [$('subReg').value];

    try {
      const res = await fetch('/v1/subscriptions', {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          frequency: $('subFreq').value,
          topics: topics.length ? topics : ['ALL'],
          regulators: regs,
          consent: true
        })
      });
      if (res.ok) {
        alert('Regulatory digest subscription saved successfully.');
        loadSubscription();
      } else {
        const err = await res.json();
        alert('Failed to save subscription: ' + (err.detail || 'check parameters'));
      }
    } catch (e) {
      alert('Error: ' + e);
    }
  });

  $('btnUnsub').addEventListener('click', async () => {
    const token = $('btnUnsub').getAttribute('data-token');
    if (!token) return;
    if (!confirm('Are you sure you want to deactivate your regulatory digest subscription?')) return;
    try {
      const res = await fetch('/v1/subscriptions/unsubscribe?token=' + encodeURIComponent(token), { method: 'POST' });
      const data = await res.json();
      alert(data.message || 'Unsubscribed successfully.');
      loadSubscription();
    } catch (e) {
      alert('Error: ' + e);
    }
  });

  $('btnDispatchAdmin').addEventListener('click', async () => {
    if (!confirm('Run scheduled digest dispatch now via Brevo Transactional Email API?')) return;
    try {
      const res = await fetch('/v1/admin/digests/dispatch?force=true', {
        method: 'POST',
        headers: getHeaders()
      });
      const data = await res.json();
      alert('Dispatch complete:\\nDelivered: ' + data.delivered + '\\nSkipped (unchanged): ' + data.skipped_unchanged + '\\nFailed: ' + data.failed);
    } catch (e) {
      alert('Dispatch error: ' + e);
    }
  });

  // 4. OCR Inspector
  async function inspectOCR() {
    const docId = $('ocrDocId').value.trim();
    if (!docId) { alert('Please enter a Document ID (UUID)'); return; }
    const rep = $('ocrReport');
    rep.style.display = 'block';
    rep.innerHTML = '<span style="color:var(--dim);">Inspecting extraction &amp; OCR metadata\\u2026</span>';

    try {
      const res = await fetch('/v1/documents/' + encodeURIComponent(docId) + '/ocr', { headers: getHeaders() });
      if (!res.ok) {
        rep.innerHTML = '<div class="notice-box notice-danger">Document not found or inaccessible.</div>';
        return;
      }
      const data = await res.json();
      rep.innerHTML = '<table class="data-table">' +
        '<tr><th>Document Title</th><td>' + esc(data.title || 'Untitled') + '</td></tr>' +
        '<tr><th>Source Regulator</th><td><span class="pill pill-' + (data.source === 'RBI' ? 'rbi' : 'sebi') + '">' + esc(data.source) + '</span></td></tr>' +
        '<tr><th>Published Date</th><td>' + esc(data.published_date || 'Unknown') + '</td></tr>' +
        '<tr><th>Active Extractor</th><td><code>' + esc(data.extractor) + '</code></td></tr>' +
        '<tr><th>OCR Extraction Status</th><td><strong>' + esc(data.ocr_status) + '</strong></td></tr>' +
        '<tr><th>Eligibility Check</th><td>' + (data.is_eligible ? '<span style="color:var(--good);">&#10003; Eligible for Free-Tier OCR (&le;1MB, &le;3 pages)</span>' : '<span style="color:var(--danger);">&#10007; Ineligible: ' + esc(data.ineligible_reason || '') + '</span>') + '</td></tr>' +
        '<tr><th>File Size</th><td>' + (data.bytes ? (data.bytes / 1024).toFixed(1) + ' KB' : 'Unknown') + '</td></tr>' +
        '<tr><th>Pages</th><td>' + (data.pages || 1) + ' page(s)</td></tr>' +
        '<tr><th>Clean Characters</th><td>' + data.clean_chars + ' chars (Floor: 200)</td></tr>' +
        '<tr><th>Content Hash</th><td><code>' + esc(data.sha256) + '</code></td></tr>' +
      '</table>';
    } catch (e) {
      rep.innerHTML = '<div class="notice-box notice-danger">Error: ' + esc(String(e)) + '</div>';
    }
  }

  $('btnInspectOCR').addEventListener('click', inspectOCR);
  $('btnTriggerOCR').addEventListener('click', async () => {
    const docId = $('ocrDocId').value.trim();
    if (!docId) return;
    try {
      const res = await fetch('/v1/documents/' + encodeURIComponent(docId) + '/ocr?force_ocr=true', {
        method: 'POST',
        headers: getHeaders()
      });
      if (res.ok) {
        alert('OCR fallback executed successfully.');
        inspectOCR();
      } else {
        const err = await res.json();
        alert('OCR request failed: ' + (err.detail || 'check document eligibility'));
      }
    } catch (e) {
      alert('Error: ' + e);
    }
  });

  // 5. Discovery Crawl
  $('btnRunDiscovery').addEventListener('click', async () => {
    const status = $('discoveryStatus'), out = $('discoveryResults');
    status.textContent = 'Crawling RBI and SEBI circular indexes\\u2026';
    out.innerHTML = '';

    try {
      const res = await fetch('/v1/admin/discovery/run', {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ sources: ['RBI', 'SEBI'], limit_per_source: 10, dry_run: false })
      });

      if (!res.ok) {
        const err = await res.json();
        status.textContent = '';
        out.innerHTML = '<div class="notice-box notice-danger">Discovery crawl failed: ' + esc(err.detail || res.statusText) + '</div>';
        return;
      }

      const rep = await res.json();
      status.innerHTML = '<span style="color:var(--good);font-weight:600;">Discovery Crawl Complete</span> &middot; ' +
        'Found ' + rep.discovered_count + ' circulars &middot; ' +
        rep.new_documents + ' new &middot; ' +
        rep.content_revisions + ' revisions &middot; ' +
        rep.unchanged + ' unchanged';

      out.innerHTML = '<table class="data-table">' +
        '<thead><tr><th>Source</th><th>Status</th><th>Classification</th><th>Detail</th></tr></thead>' +
        '<tbody>' +
        rep.items.map(item =>
          '<tr>' +
            '<td><span class="pill pill-' + (item.source === 'RBI' ? 'rbi' : 'sebi') + '">' + esc(item.source) + '</span></td>' +
            '<td>' + (item.http_status ? 'HTTP ' + item.http_status : '-') + '</td>' +
            '<td><code>' + esc(item.classification) + '</code></td>' +
            '<td><a href="' + esc(item.url) + '" target="_blank">' + esc(item.url.split('/').pop()) + '</a><br><small style="color:var(--dim);">' + esc(item.detail) + '</small></td>' +
          '</tr>'
        ).join('') +
        '</tbody></table>';
    } catch (e) {
      status.textContent = '';
      out.innerHTML = '<div class="notice-box notice-danger">Error: ' + esc(String(e)) + '</div>';
    }
  });

  $('btnCheckHealth').addEventListener('click', async () => {
    try {
      const res = await fetch('/healthz');
      const data = await res.json();
      alert('System Health: ' + data.status.toUpperCase() + '\\nDB Latency: ' + (data.database_latency_ms || 0) + ' ms\\nGeneration: ' + data.corpus_generation);
    } catch (e) {
      alert('Health check error: ' + e);
    }
  });

})();
</script>
</body>
</html>
"""
