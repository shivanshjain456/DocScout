# ADR-0040: Third-Party Vendor Risk Assessment Engine (FEAT-049)

## Status
Accepted

## Context
Regulated financial entities, payment service providers, and capital market intermediaries (supervised by RBI and SEBI) are legally prohibited from entering into IT or cloud outsourcing agreements that restrict regulatory inspection rights, allow unrestricted cross-border data transfer, or lack mandatory business continuity and incident notification commitments. Manual contract review by legal teams creates statutory review bottlenecks and leaves institutions exposed to regulatory sanctions and non-compliance penalties under the RBI Master Direction on Outsourcing of IT Services (2023) and the SEBI Cloud Security Framework (2023).

## Decision
1. **Statutory Clause Rule Engine (`app/compliance/vendor_risk.py`)**:
   - Establishes a deterministic statutory rule catalog covering 8 mandatory contract clauses:
     1. `RBI_AUDIT_ACCESS`: Unconditional access for RBI/SEBI and internal/external auditors to inspect systems, books, and datacenter premises.
     2. `DATA_LOCALIZATION`: Strict onshore storage and processing of financial data and customer PII within the territory of India.
     3. `SUB_CONTRACTING_CONTROL`: Mandatory prior written consent for material sub-contracting and full compliance pass-through.
     4. `BCP_DR_TESTING`: Annual joint business continuity drills, RPO/RTO SLAs, and continuous availability covenants.
     5. `INCIDENT_NOTIFICATION`: Immediate security breach and operational outage reporting (within 1 to 6 hours).
     6. `TERMINATION_ASSISTANCE`: Minimum 90-day transition support, complete data return, and verified cryptographic erasure.
     7. `CONFIDENTIALITY_SECURITY`: Comprehensive DPDPA 2023 and IT Act data protection covenants.
     8. `SOC2_ISO_AUDIT_RIGHTS`: Obligation to provide annual independent SOC-2 Type II and ISO 27001 audit certificates.
   - Inverted detection of negative indicators (e.g. cross-border data transfer disclaimers, liability caps disclaiming regulatory fines) that invalidate compliance.

2. **Performance and Security Isolation**:
   - In-memory contract parsing and stateless evaluation with zero disk retention of vendor contract agreements.
   - High-throughput execution ($\le 60\text{ ms}$ for 30-page agreements) with memory footprint below 32 MB.

3. **REST API Endpoint (`app/api/app.py`)**:
   - `POST /v1/compliance/vendor-audit`: accepts vendor category (`CLOUD`, `SAAS`, `PAYMENT_SWITCH`, `DATACENTER`) and contract text (100 to 150,000 characters).
   - Outputs compliance score (0.0 to 100.0), categorical risk rating (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`), list of present mandatory clauses, and missing clauses with statutory citations and remediation guidance.

4. **Observability (`app/api/metrics.py`)**:
   - Prometheus counter `docscout_vendor_contracts_audited_total{risk_level}`.
   - Prometheus histogram `docscout_vendor_audit_duration_seconds`.

5. **Console UI Component (`ui/src/components/VendorRiskAuditView.tsx`)**:
   - Interactive vendor audit view with file dropzone, compliance score gauge, missing statutory clause checklist, and prescriptive contract amendment clauses.

## Consequences
- Automated detection of statutory outsourcing deficiencies with $\ge 95\%$ recall and $\ge 90\%$ precision across 15 benchmark contract configurations.
- Immediate identification of illegal offshore data routing and restrictive audit limitations prior to contract execution.
- Stateless execution guarantees confidentiality and zero persistent storage of sensitive vendor contract documents.
