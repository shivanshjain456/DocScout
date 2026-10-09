"""The demo page, as a single self-contained string.

No external stylesheet, font, script or image. Two reasons, both practical: the page is
served from a sandboxed frame with no network access during review, where a CDN reference
degrades silently into an unstyled page; and a demo that pulls third-party JavaScript onto
a page where someone pastes an API key is a bad habit regardless of how harmless the CDN is.

The key is held in a form field and sent in the `X-API-Key` header. It is never placed in
the URL, because query strings end up in proxy logs and browser history.
"""

from __future__ import annotations

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DocScout — citation-grounded regulatory search</title>
<style>
  :root {
    --bg:#0f1117; --panel:#171a23; --line:#262b38; --ink:#e6e9f0; --dim:#9aa3b5;
    --accent:#7aa2f7; --good:#9ece6a; --warn:#e0af68;
  }
  * { box-sizing:border-box; }
  body {
    margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  }
  .wrap { max-width:900px; margin:0 auto; padding:28px 20px 64px; }
  h1 { font-size:22px; margin:0 0 4px; letter-spacing:-.01em; }
  .sub { color:var(--dim); margin:0 0 22px; font-size:14px; }
  .panel { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:16px; }
  label { display:block; font-size:12px; text-transform:uppercase; letter-spacing:.06em;
          color:var(--dim); margin:0 0 6px; }
  input, select, textarea {
    width:100%; background:#0b0d13; color:var(--ink); border:1px solid var(--line);
    border-radius:7px; padding:10px 12px; font:inherit;
  }
  input:focus, select:focus, textarea:focus { outline:2px solid var(--accent); outline-offset:-1px; }
  .row { display:flex; gap:12px; flex-wrap:wrap; margin-top:12px; }
  .row > div { flex:1; min-width:130px; }
  button {
    margin-top:14px; background:var(--accent); color:#0b0d13; border:0; border-radius:7px;
    padding:11px 20px; font:600 15px/1 inherit; cursor:pointer;
  }
  button:disabled { opacity:.55; cursor:progress; }
  .meta { margin:18px 0 10px; color:var(--dim); font-size:13px; }
  .hit { background:var(--panel); border:1px solid var(--line); border-radius:10px;
         padding:14px 16px; margin-bottom:12px; }
  .hit h3 { margin:0 0 8px; font-size:13px; color:var(--dim); font-weight:600;
            display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
  .rank { background:var(--accent); color:#0b0d13; border-radius:5px; padding:1px 7px;
          font-weight:700; }
  .tag { border:1px solid var(--line); border-radius:5px; padding:1px 7px; }
  .cid { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:11px; color:var(--dim); }
  .txt { white-space:pre-wrap; font-size:14px; }
  a { color:var(--accent); }
  .err { border-color:#7a3b3b; color:#ff9e9e; }
  .ok { color:var(--good); }
  footer { margin-top:28px; color:var(--dim); font-size:12px; border-top:1px solid var(--line);
           padding-top:14px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>DocScout</h1>
  <p class="sub">
    Citation-grounded retrieval over RBI and SEBI circulars. Returns the <em>evidence</em>,
    not a generated answer &mdash; every passage carries a stable chunk id and character
    span you can check against the source document.
  </p>

  <div class="panel">
    <label for="key">API key</label>
    <input id="key" type="password" placeholder="X-API-Key" autocomplete="off" spellcheck="false">
    <div class="row">
      <div style="flex:3 1 100%">
        <label for="q">Question</label>
        <input id="q" value="What are the KYC requirements for foreign portfolio investors?">
      </div>
    </div>
    <div class="row">
      <div>
        <label for="mode">Mode</label>
        <select id="mode">
          <option value="hybrid">hybrid (serving)</option>
          <option value="bm25">bm25 only</option>
          <option value="dense">dense only</option>
        </select>
      </div>
      <div>
        <label for="k">Passages</label>
        <input id="k" type="number" value="5" min="1" max="20">
      </div>
      <div>
        <label for="cache">Cache</label>
        <select id="cache"><option value="true">use</option><option value="false">bypass</option></select>
      </div>
    </div>
    <button id="go">Search</button>
  </div>

  <div id="meta" class="meta"></div>
  <div id="out"></div>

  <footer>
    Retrieval only &mdash; no LLM is in the request path.
    <a href="/docs">OpenAPI docs</a> &middot; <a href="/healthz">health</a>
  </footer>
</div>
<script>
const $ = (id) => document.getElementById(id);
const esc = (s) => s.replace(/[&<>"']/g, c => (
  {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

async function run() {
  const key = $('key').value.trim();
  const out = $('out'), meta = $('meta');
  out.innerHTML = ''; meta.textContent = 'searching\\u2026';
  $('go').disabled = true;
  try {
    // Relative URL on purpose: the browser is not inside the sandbox, so anything
    // pointing at localhost would resolve to the reviewer's own machine.
    const res = await fetch('/v1/search', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-API-Key': key},
      body: JSON.stringify({
        query: $('q').value,
        k: Number($('k').value),
        mode: $('mode').value,
        use_cache: $('cache').value === 'true'
      })
    });
    const data = await res.json();
    if (!res.ok) {
      meta.textContent = '';
      out.innerHTML = '<div class="hit err"><b>' + res.status + '</b> ' +
        esc(data.detail || 'request failed') +
        (data.problems ? '<div class="txt">' + esc(JSON.stringify(data.problems)) + '</div>' : '') +
        '</div>';
      return;
    }
    const t = data.timings;
    meta.innerHTML = '<span class="ok">' + data.passages.length + ' passages</span> in ' +
      t.total_ms.toFixed(1) + ' ms ' +
      (t.cache_hit ? '(cache hit)' : '(retrieval ' + t.retrieval_ms.toFixed(1) + ' ms)') +
      ' &middot; ' + esc(data.provenance.embedding_model) +
      ' &middot; ' + data.provenance.corpus_chunks + ' chunks';
    out.innerHTML = data.passages.map(p => {
      const arms = Object.entries(p.arm_ranks)
        .map(([a, r]) => '<span class="tag">' + esc(a) + ' #' + r + '</span>').join(' ');
      const url = p.canonical_url
        ? ' <a href="' + esc(p.canonical_url) + '" target="_blank" rel="noopener noreferrer">source</a>' : '';
      const docHeader = p.title
        ? '<div style="margin:4px 0 8px;font-weight:600;color:var(--ink);font-size:14px;">' + esc(p.title) +
          (p.published_date ? ' <span style="font-weight:normal;color:var(--dim);font-size:12px;">(' + esc(p.published_date) + ')</span>' : '') +
          '</div>' : '';
      return '<div class="hit"><h3><span class="rank">' + p.rank + '</span>' +
        '<span class="tag">' + esc(p.source) + '</span>' + arms +
        '<span class="tag">score ' + p.score.toFixed(4) + '</span>' +
        '<span class="tag">chars ' + p.char_start + '\\u2013' + p.char_end + '</span>' +
        url + '</h3>' +
        docHeader +
        '<div class="cid">' + esc(p.chunk_id) + '</div>' +
        '<div class="txt">' + esc(p.text) + '</div></div>';
    }).join('');
  } catch (e) {
    meta.textContent = '';
    out.innerHTML = '<div class="hit err">' + esc(String(e)) + '</div>';
  } finally {
    $('go').disabled = false;
  }
}
$('go').addEventListener('click', run);
$('q').addEventListener('keydown', e => { if (e.key === 'Enter') run(); });
</script>
</body>
</html>
"""
