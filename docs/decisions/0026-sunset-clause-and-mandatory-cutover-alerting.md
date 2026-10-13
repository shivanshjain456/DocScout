# ADR-0026: Sunset Clause & Mandatory Cutover Alerting Engine (FEAT-035)

- **Status:** accepted
- **Date:** 2026-10-13
- **Deciders:** DocScout Engineering Team
- **Related:** FEAT-035, `pillar-04-regulatory-conflicts.md`, `app/ingest/deadline_extractor.py`, `app/digests/deadline_notifier.py`

## Context

Financial regulations from bodies like RBI and SEBI frequently mandate future transition deadlines, sunset clauses, and phased cutovers (e.g. Card-on-File Tokenization cutover, T+1 settlement migration, Payment Aggregator net worth milestones). Regulated entities routinely incur statutory penalties when compliance teams miss these transition milestones. Ingestion needs to automatically extract cutover deadlines from circular text, store them in PostgreSQL `regulatory_deadlines`, and dispatch automated countdown alerts as deadlines approach.

Key constraints:
- Ingestion extraction latency budget $\le 2.0\text{ ms}$ per document.
- Zero false-positive historical dates tagged as future deadlines.
- Explicit non-guessing rule: text stating "to be notified separately" must be excluded from date guessing.
- Seamless integration with the existing Brevo digest and notification engine.

## Decision

We will implement:
1. `app/ingest/deadline_extractor.py`: A high-throughput, deterministic statutory deadline extractor using specialized regex matchers for normative cutover patterns (`with effect from`, `shall transition by`, `shall come into force on`, `mandatory cutover date`, `extended up to`, `sunset date is`, `on or before`). Extracted dates are parsed using `dateutil.parser` with strict date validity checks.
2. Temporal gating: Dates prior to `reference_date` (or today) are never classified as upcoming active cutovers. Ambiguous markers ("to be notified separately") explicitly return empty cutover dates.
3. Database migration `migrations/0026_regulatory_deadlines.up.sql` and `migrations/0026_regulatory_deadlines.down.sql` with table `regulatory_deadlines` and `deadline_alert_history`.
4. `app/digests/deadline_notifier.py`: Alert dispatcher that checks remaining days against `DeadlineAlertConfig(critical_threshold_days=15, warning_threshold_days=45)` and dispatches Brevo transactional alerts or webhooks.
5. Observability: Prometheus gauge `docscout_upcoming_deadlines_count{urgency}` and counter `docscout_deadline_alerts_sent_total{channel, urgency}` in `app/api/metrics.py`.

## Consequences

- What becomes easier: Automated compliance calendar tracking and early warning cutovers without manual spreadsheet audits.
- What becomes harder: Maintaining regex syntax patterns across novel gazette drafting idioms.
- Cost and performance: Deterministic parsing runs in $<0.5\text{ ms}$ (well under the $2.0\text{ ms}$ SLO), with zero external API call costs during extraction.

## Rejected alternatives

### Unconstrained LLM / Prompt-based Date Extraction
- What it is: Sending parsed document chunks to an LLM prompt ("Extract all transition deadlines and cutover dates from this text").
- Why it was plausible: Natural language models handle unstructured prose variations with zero regex rules.
- Why we rejected it: Non-deterministic latency ($1.2\text{ s}$ vs $<0.5\text{ ms}$), monetary cost ($0.002 per doc on every ingestion pass), and hallucination risk where historical circular citations ("vide circular dated March 2018") are misattributed as cutover deadlines.
- What would change our mind: If circular drafting styles became entirely conversational without normative date phrases, and local zero-cost sub-millisecond SLMs became available.

### Plain Regex Date Matcher without Statutory Trigger Anchoring
- What it is: Extracting every date in the document using a generic date regex.
- Why it was plausible: Extremely simple single-line implementation.
- Why we rejected it: Circulars contain dozens of incidental dates (gazette publication dates, past circular references, committee establishment dates). Generic date extraction produces unacceptable false-positive rates ($>80\%$), violating the requirement of zero false-positive historical dates.
- What would change our mind: Never; statutory anchoring to operative clauses is required by domain design.
