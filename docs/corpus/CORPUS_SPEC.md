# DocScout — Corpus Specification

**Status:** authoritative specification for what DocScout ingests and how. Last updated **2026-10-01**.
**Implementation status:** no ingestion code exists (`app/ingest/__init__.py` is 0 bytes, VERIFIED).
A Phase 0 verification script, `scripts/verify_corpus_fetch.py`, proved the acquisition paths on a
20-document sample; that is the evidence base for everything below.

Status tags (**VERIFIED / SPECIFIED / PROPOSED / BLOCKED / UNRESOLVED**) and the U-register are
defined in `SPEC.md` §1 and §9.

**Relationship to `docs/corpus-provenance.md`:** that document is the Phase 0 **provenance record**
— the narrative of what was fetched on 2026-10-01 and what was discovered about each site. It
remains valid and is cited here. *This* document is the **normative specification**: where the two
overlap, this one governs, and `corpus-provenance.md` is read as the evidence behind it. One
substantive update supersedes it: §6 below now carries primary-source `robots.txt` evidence that
`corpus-provenance.md` records as "not performed".

---

## 1. Terminology

Used identically across all seven documents.

| Term | Definition |
|---|---|
| **Document** | One logical regulatory publication (a circular, notification, or master circular), identified by its canonical URL |
| **Version** | One observed byte-state of a document, identified by SHA-256 of the fetched bytes |
| **Document identity** | The triple **(URL, fetch date, SHA-256)** |
| **Chunk** | A retrievable span of text belonging to exactly one version, with a stable `chunk_id` |
| **Canary** | A synthetic document carrying assistant-directed instructions, used as a graded negative test |
| **Manifest** | `corpus/raw/manifest.json` — the machine-readable record of every fetch attempt |

---

## 2. Sources — VERIFIED

| Source | Entry point | Document form | Phase 0 result |
|---|---|---|---|
| **RBI** (Reserve Bank of India) — notifications and master circulars | `https://www.rbi.org.in/Scripts/NotificationUser.aspx`, `.../BS_ViewMasCirculardetails.aspx` | Absolute PDF links on `rbidocs.rbi.org.in` embedded directly in the listing HTML | 10/10 fetched and extracted, 2026-10-01 |
| **SEBI** (Securities and Exchange Board of India) — circulars and master circulars | `https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=7&smid=0` | Listing → circular detail HTML → **PDF referenced in an `<iframe src=…file=…>`** on `sebi.gov.in/sebi_data/attachdocs/` | 10/10 fetched and extracted, 2026-10-01 |

**C-1 — SPECIFIED.** The ingester MUST enforce a host allowlist of exactly `www.rbi.org.in`,
`rbidocs.rbi.org.in`, `www.sebi.gov.in`. Any other host is a hard error, not a skip. Adding a host
requires an ADR. *Test:* an off-list URL raises before any network call.

### 2.1 Access behaviour discovered, not assumed — VERIFIED

These findings cost real debugging time in Phase 0 and are the reason the ingester cannot be naive:

- **RBI listings are ASP.NET with `__doPostBack` navigation**, but the notification pages embed
  absolute `rbidocs.rbi.org.in/...pdf` URLs in the HTML. A plain HTTP fetch suffices; **no
  JavaScript rendering is required.**
- **SEBI returns HTTP 403 on directory-style paths** (`/legal/circulars`, `/legal/master-circulars`)
  to non-browser clients, while serving individual detail pages and PDFs with 200.
- **The SEBI detail page is a stub.** Its extractable body is roughly **227 characters**; the actual
  content is the PDF in the iframe (K-17). Extracting the HTML alone yields almost no text and
  *looks like success*. This is the single most dangerous failure mode in the corpus pipeline.
- A descriptive User-Agent identifying the crawler is sent on every request.

**C-2 — SPECIFIED.** For SEBI documents the ingester MUST follow the iframe to the PDF and MUST
treat the detail page as metadata only. *Test:* a fixture of a real SEBI detail page asserts that
ingesting it without the PDF raises the FR-3 short-extraction error rather than storing 227
characters.

---

## 3. Coverage and selection

| ID | Rule | Tag |
|---|---|---|
| C-3 | v1 corpus scope is RBI and SEBI documents published in a date window fixed by ADR before the first full ingest | RESOLVED (ADR-0012) — expanded to 35 documents (18 RBI notifications, 16 SEBI circulars, 1 synthetic canary) spanning major regulatory frameworks in 2024–2026. |
| C-4 | Selection MUST be reproducible: the ingester records the listing URL and page it harvested each document from | SPECIFIED (the manifest already carries `detail_page`, VERIFIED) |
| C-5 | Target corpus size for v1 | RESOLVED (ADR-0012) — scaled from 21 to 35 documents (230 chunks, ~190k chars). Unsaturates depth-10 retrieval (recall@10 < 1.000) and lowers paired bootstrap gate noise floor to <= 1.0pp over 365 answerable gold items. |

No claim is made here about how many documents RBI and SEBI publish, or about corpus completeness.
Nothing in the repository establishes it.

---

## 4. Identity, deduplication, versioning

| ID | Rule | Tag |
|---|---|---|
| C-6 | Each document is identified by **(URL, fetch date, SHA-256)**, recorded in `corpus/raw/manifest.json` | VERIFIED — the manifest schema already carries `url`, `source`, `detail_page`, `fetch_ts`, `http_status`, `bytes`, `sha256`, `pages`, `extractor`, `char_count`, `ok`, `n`, `local_path` |
| C-7 | Deduplication is by **content hash first**, then canonical URL. The same circular is often reachable from several index pages under different URLs | SPECIFIED |
| C-8 | A changed SHA-256 at a known URL is a **new version, never an update in place**. Both versions are retained; the newer becomes current; chunk IDs of the superseded version remain resolvable | SPECIFIED (= `SPEC.md` FR-4) |
| C-9 | **Supersession between documents** (a master circular replacing earlier circulars) is document metadata that materially affects correctness — the right answer to "what is the current rule" depends on what is in force | UNRESOLVED (U-12) |

**Why C-8 is strict:** regulators reissue circulars and silently replace the PDF at the same URL. If
versions were overwritten, every historical evaluation report would reference text that no longer
exists, and reproducibility (`EVAL_PROTOCOL.md` §7) would be fiction.

---

## 5. Extraction

| ID | Rule | Tag |
|---|---|---|
| C-10 | PDFs are extracted with `pypdf` (6.19.0, locked); HTML with `trafilatura` (2.2.0) / `beautifulsoup4` (4.15.0) | VERIFIED — these are the extractors the Phase 0 run used and recorded in the manifest's `extractor` field |
| C-11 | A document whose extraction yields **< 500 clean characters** MUST be flagged and MUST NOT be silently ingested | SPECIFIED. The threshold is the Phase 0 criterion, under which **20/20** documents passed (criterion was ≥ 18/20) |
| C-12 | Scanned / image-only PDFs extract near-zero text and require OCR. None appeared in the sample; RBI archives are known to contain older scanned material | UNRESOLVED (U-16) — C-11 makes them *detected*, not *handled* |
| C-13 | Tables (rate schedules, timelines) flatten badly under `pypdf` text extraction, which is a direct risk to numeric answer accuracy | UNRESOLVED (U-11) |
| C-14 | SEBI attachment filenames are opaque timestamps and can rotate. URL + hash in the manifest makes breakage **detectable rather than silent** | SPECIFIED |

### 5.1 Measured extraction results — VERIFIED

Evidence: `corpus/raw/manifest.json`, `docs/setup/verify/step8-corpus.txt`.

| Metric | Value |
|---|---|
| Documents attempted | 20 |
| Extracted > 500 clean characters | 20 (criterion ≥ 18) |
| Source split | RBI 10, SEBI 10 |
| Extracted character range | 951 – 47,603 |
| Injection canary | 1 (manifest entry `n: 0`), 1,524 raw / 1,458 collapsed chars, sha256 `ef1f71aed2b9ac55…` |
| Generated at | 2026-10-01T10:15:06Z |

The canary is counted separately from the 20 real documents throughout.

---

## 6. Terms of use, licensing, and crawl directives

Both RBI and SEBI circulars are **public regulatory documents** published by Indian statutory
authorities for general compliance use, accessible without registration or payment. No explicit
machine-readable licence (a `LICENSE` page or CC notice) was located on either site.

### 6.1 `robots.txt` — VERIFIED 2026-10-01

Primary-source retrieval, recorded verbatim in `docs/setup/verify/robots-txt-evidence.txt`:

| Host | HTTP | Content | Interpretation |
|---|---|---|---|
| `www.sebi.gov.in/robots.txt` | **200** | `User-agent: *` · `Disallow:` (empty) · `Disallow: /js` · `/hindi/js` · `/css` · `/hindi/css` | Allow-all except static asset directories. **The paths DocScout fetches (`/legal/…`, `/sebi_data/attachdocs/…`) are not disallowed.** |
| `www.rbi.org.in/robots.txt` | **418** | A WAF "Unauthorised Access" interstitial, not a robots file | **RBI's crawl directives are UNDETERMINED from this environment.** No permission may be inferred in either direction. |

This partially closes K-16: the SEBI side now has an affirmative, evidenced answer. The RBI side and
the legal/terms review remain open.

| ID | Rule | Tag |
|---|---|---|
| C-15 | Fetch politely: low volume, rate-limited, descriptive User-Agent, no authentication bypass, nothing behind a login | SPECIFIED (and the Phase 0 posture, VERIFIED) |
| C-16 | Documents are treated as **reference material, quoted with attribution and a link to the source URL**. DocScout cites the originating circular; it does not republish the corpus | SPECIFIED |
| C-17 | Determine RBI's crawl directives by a means that is not blocked by the WAF, and complete a terms-of-use review for both sites, before any public deployment | UNRESOLVED (U-5, owner unassigned) — gates M6 |
| C-18 | The fetched corpus **bytes** are gitignored; **`corpus/raw/manifest.json` is tracked**. The corpus is re-derivable from the manifest | VERIFIED in `.gitignore` (corrected 2026-10-01, see below) |

**C-18 was broken until 2026-10-01 and is worth recording.** `.gitignore` carried an unanchored
`corpus/` pattern, which git matches at *any* depth. Two consequences, both silent: the manifest
itself was untracked — so "the corpus is re-derivable from the manifest" was hollow, since the
manifest would vanish with the corpus — and `docs/corpus/`, the directory holding *this document*,
was excluded from version control entirely. The pattern is now anchored to `/corpus/` with an
explicit negation for the manifest. See ADR-0001.

**The consequence that remains:** because the raw bytes are untracked and the sources mutate
upstream (C-8), a corpus snapshot is reproducible only to the extent the manifest's URLs still
serve the same bytes. The tracked manifest makes that **detectable** — a re-fetch whose SHA-256 no
longer matches is a recorded version change rather than an invisible one. `EVAL_PROTOCOL.md` §7
specifies how evaluation runs stay reproducible despite it.

---

## 7. Injection posture

All corpus text is **untrusted data, never instructions** (skill `corpus-injection-defense`;
`SECURITY.md` S-7).

| ID | Rule | Tag |
|---|---|---|
| C-19 | At least one synthetic injection canary ships with the corpus sample and in the evaluation gold set as a **graded negative test** | SPECIFIED; the canary document itself is VERIFIED to exist |
| C-20 | Canary documents MUST be marked `is_injection_canary: true` in the manifest and MUST never be counted in corpus coverage statistics | VERIFIED — the flag exists and the Phase 0 counts exclude it |
| C-21 | Every ingested document is scanned for assistant-directed instruction patterns; matches are logged, not silently dropped | SPECIFIED. Phase 0 result: the canary matched **11/11** patterns, the 20 real documents matched **0/20** (evidence: `docs/setup/verify/step8-injection-scan.txt`, `docs/security/injection-canary-log.md`) |

The 0/20 result says the real sample was clean; it is **not** evidence that the corpus is safe. The
control is the delimiter discipline in `app/generate/`, not the scan.

---

## 8. Manifest contract — VERIFIED schema, SPECIFIED guarantees

Top-level keys observed in `corpus/raw/manifest.json`: `generated_at`, `attempted`,
`extracted_over_500_chars`, `pass_criterion`, `passed`, `sources`, `documents`.

Per-document keys: `n`, `url`, `source`, `detail_page`, `fetch_ts`, `http_status`, `bytes`,
`sha256`, `pages`, `extractor`, `char_count`, `ok`, `local_path` (+ `is_injection_canary` on
canaries).

| ID | Rule | Tag |
|---|---|---|
| C-22 | The manifest MUST record **every attempt**, including failures, with its `http_status` and `ok: false`. Silent skips are forbidden | SPECIFIED (`ok` field VERIFIED present) |
| C-23 | The manifest is the ingestion pipeline's contract with the rest of the system; its schema is validated by a test that fails on a missing or renamed key | SPECIFIED |

---

## 9. Open items owned by this document

U-5 (terms review owner, and RBI crawl directives per C-17), U-11 (tables), U-12 (supersession),
U-16 (scanned PDFs), plus C-3 and C-5 above (date window and target size).
All are listed with their resolution evidence in `SPEC.md` §9.

**U-8 (chunking) closed on 2026-10-01 via ADR-0003** and leaves this document two obligations.
Ingest cleaning MUST be offset-preserving — noise is blanked with equal-length spaces, never
deleted — so chunk offsets stay valid against the original extracted text. And extractor quality
is now a lever on citation quality rather than a convenience: clause-aware chunking produced the
tightest citations in the sweep but lost span integrity because pypdf preserved no layout (every
real document extracts to zero newlines), which raises the value of resolving U-16.
