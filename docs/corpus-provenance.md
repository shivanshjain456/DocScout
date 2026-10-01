# Corpus provenance

Scope of this document: where DocScout's corpus comes from, under what terms, how documents are
identified and de-duplicated, and how versions are tracked. Written in Phase 0 against a verified
20-document sample; the full ingest lands in the build phase.

## Sources

| Source | Entry point | Document form | Verified |
|---|---|---|---|
| **RBI** — Reserve Bank of India notifications & master circulars | `https://www.rbi.org.in/Scripts/NotificationUser.aspx` and `.../BS_ViewMasCirculardetails.aspx` | direct PDF links on `rbidocs.rbi.org.in` | 2026-10-01, 10/10 fetched & extracted |
| **SEBI** — Securities and Exchange Board of India circulars & master circulars | `https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=7&smid=0` | listing → circular detail HTML → PDF in an `<iframe src=…file=…>` on `sebi.gov.in/sebi_data/attachdocs/` | 2026-10-01, 10/10 fetched & extracted |

### Access method notes (discovered, not assumed)

- **RBI** index pages are ASP.NET and most navigation is `__doPostBack` JavaScript, but the
  notification listings embed absolute `rbidocs.rbi.org.in/...pdf` URLs directly in the HTML, so a
  plain HTTP fetch is sufficient. No JS rendering needed.
- **SEBI** returns **HTTP 403** on directory-style paths (`/legal/circulars`, `/legal/master-circulars`)
  to non-browser clients, but serves individual circular detail pages (200) and the PDFs themselves.
  The detail page body is a near-empty stub (~227 chars extractable) — **the real content is the PDF
  referenced in an iframe**, not the HTML. Extracting the HTML alone would silently yield almost no
  text; this is the kind of failure that looks like success. Always follow the iframe.
- A descriptive User-Agent identifying the crawler is sent on every request.

## Terms of use / licensing

Both RBI and SEBI circulars are **public regulatory documents** published by Indian statutory
authorities for general compliance use, free to access without registration or paywall.

Pages consulted on 2026-10-01: the RBI notifications index and the SEBI circular listing above, plus
the fetched documents themselves. **No explicit machine-readable licence (e.g. a `LICENSE` page or
CC notice) was located on either site during Phase 0, and no `robots.txt`-level permission audit was
performed.** That audit is an outstanding item, recorded as a Known issue in `SETUP_REPORT.md`
rather than assumed away. Current posture:

- Fetch politely: low volume, rate-limited, descriptive UA, no authentication bypass, no scraping of
  anything behind a login.
- Treat documents as **reference material, quoted with attribution and a link to the source URL** —
  DocScout answers cite the originating circular rather than republishing corpora wholesale.
- Before any public deployment, re-check each site's terms and `robots.txt` and record the outcome
  here (see skill `deploy-protocol`).

## Identity, de-duplication and versioning

Each document is identified by the triple **(URL, fetch date, SHA-256 of the fetched bytes)**,
recorded in `corpus/raw/manifest.json`:

```json
{"n": 11, "url": "https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1787224027885.pdf",
 "source": "SEBI", "detail_page": "…", "fetch_ts": "2026-10-01T…Z", "http_status": 200,
 "bytes": 639304, "sha256": "…", "pages": 2, "extractor": "pypdf", "char_count": 2896, "ok": true}
```

- **De-duplication** is by content hash first (the same circular is often reachable from several
  index pages under different URLs), then by canonical URL.
- **Versioning:** regulators reissue circulars and silently replace PDFs at the same URL. A changed
  SHA-256 for a known URL is a **new version**, not an update-in-place: both are retained, the newer
  one becomes current, and the chunk IDs of the superseded version stay valid so historical eval
  results remain reproducible.
- **Supersession** (a master circular replacing earlier ones) is document metadata to be captured in
  the build phase — it materially affects answer correctness, since the right answer to "what is the
  current rule" depends on which circular is in force.
- `corpus/` is **gitignored**. The corpus is re-derivable from the manifest; only the manifest and
  this provenance document are tracked.

## Known extraction risks (carried into the build phase)

- **Scanned/image-only PDFs** extract near-zero text and need OCR. None appeared in the 20-document
  sample, but RBI archives contain older scanned material. Detection rule: a PDF with pages but
  <500 extracted chars is flagged, never silently ingested.
- **Tables** (rate schedules, timelines) flatten badly in `pypdf` text extraction — a known risk for
  numeric answer accuracy, and a build-phase decision (table-aware extraction vs accepting the loss).
- **Rotated/expired URLs**: SEBI attachment filenames are opaque timestamps and can change. The
  manifest's URL + hash makes breakage detectable rather than silent.
- Phase 0 sample result: **20/20 documents extracted >500 clean chars** (criterion was ≥18/20).
  Evidence: `docs/setup/verify/step8-corpus.txt`, `corpus/raw/manifest.json`.

## Injection posture

All corpus text is untrusted data (skill `corpus-injection-defense`). One synthetic injection canary
ships with the sample and will ship in the eval gold set as a graded negative test. The 20 real
documents were scanned for assistant-directed instructions: **0 matches**. See
`docs/security/injection-canary-log.md`.
