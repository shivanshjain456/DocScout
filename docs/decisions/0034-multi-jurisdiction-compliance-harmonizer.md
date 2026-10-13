# ADR-0034: Multi-Jurisdiction Compliance Harmonizer & Statutory Delta Classification

## Status
Accepted (FEAT-043)

## Context
Multinational banks, fintechs, and payment service providers operating in India face overlapping and often divergent regulatory obligations across domestic (RBI, SEBI, CERT-In) and international (EU GDPR, EU DORA, US NIST/FedRAMP, Global ISO) regimes.

Key challenges include:
1. Identifying where domestic regulations impose significantly stricter obligations (e.g., RBI's mandatory 6-hour cyber incident notification vs. GDPR's 72-hour window; strict domestic payment data localization under DPSS.CO.OD No. 2785/06.08.005/2017-18 vs. GDPR adequacy/SCC cross-border transfer mechanisms).
2. Preventing compliance teams from mistakenly assuming international certification (ISO 27001 or SOC 2) suffices for Indian statutory audits.
3. Enabling programmatic query answering: *"How do RBI cybersecurity incident reporting obligations compare to EU DORA or GDPR?"*

## Decision
1. **Jurisdiction Code Catalog**:
   - Establish canonical, normalized jurisdiction identifiers: `IN_RBI`, `IN_SEBI`, `EU_GDPR`, `EU_DORA`, `US_NIST`, `US_FEDRAMP`, `GLOBAL_ISO`, `UK_FCA`.
   - Reject unmapped/invalid jurisdictions with HTTP 422 and return the catalog of supported jurisdictions.
2. **Deterministic Delta Classifier**:
   - Classify comparative statutory deltas into three strict categories:
     - `STRICTER_A`: Jurisdiction A imposes more onerous, granular, or shorter statutory deadlines than Jurisdiction B.
     - `EQUIVALENT`: Both jurisdictions share substantively identical technical thresholds or controls.
     - `STRICTER_B`: Jurisdiction B imposes stricter requirements than Jurisdiction A.
3. **Statutory Span & Carve-Out Grounding**:
   - Every harmonization finding provides verbatim statutory citations (e.g. RBI Master Directions clause numbers, EU Regulation article numbers) and localized mandatory carve-outs.
4. **Sub-Millisecond Indexed Engine**:
   - High-speed in-memory indexing of pre-calibrated compliance topics alongside semantic fallback, delivering query latency $\le 20\text{ ms}$ p95.
5. **Observability**:
   - Prometheus counter `docscout_harmonizations_performed_total{delta_classification, topic}`.

## Consequences
- **Positive**:
  - Deterministic identification of stricter local statutory mandates with zero speculative false equivalence.
  - Sub-millisecond API response times for indexed compliance domains.
  - Defensible compliance audits with exact circular and regulation citations.
- **Negative**:
  - Requires maintaining statutory delta records as new circulars and cross-border regulations take effect.
