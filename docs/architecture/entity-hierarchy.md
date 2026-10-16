# Statutory Entity Hierarchy & Classification Ontology

*DocScout Enterprise Regulatory Intelligence Engine - Architecture Specification*

---

## 1. Overview
The Statutory Entity Hierarchy defines the formal taxonomy of regulated financial entities across the **Reserve Bank of India (RBI)**, **Securities and Exchange Board of India (SEBI)**, and related statutory frameworks.

Every incoming search query is scanned using a high-throughput prefix Trie ($\le 1.5\text{ ms}$ latency budget) to extract canonical entity mentions, decorate search requests with statutory scope filters, and resolve multi-tiered parent-child relationships.

---

## 2. 35 Statutory Entity Classifications

### Root Tier
1. **Regulated Entity (`regulated_entity`)**: Top-level root covering all statutory financial institutions in India.

### Commercial Banking Subtree
2. **Commercial Bank (`commercial_bank`)**
   - 3. **Public Sector Bank (`public_sector_bank`)** (PSBs, SBI, Nationalised Banks)
   - 4. **Private Sector Bank (`private_sector_bank`)**
   - 5. **Foreign Bank (`foreign_bank`)** (Wholly Owned Subsidiaries / Branch Mode)
   - 6. **Small Finance Bank (`small_finance_bank`)** (SFBs)
   - 7. **Payments Bank (`payments_bank`)** (PBs)
   - 8. **Regional Rural Bank (`regional_rural_bank`)** (RRBs)

### Co-operative Banking Subtree
9. **Co-operative Bank (`cooperative_bank`)**
   - 10. **Urban Co-operative Bank (`urban_cooperative_bank`)** (UCBs)
   - 11. **Rural Co-operative Bank (`rural_cooperative_bank`)** (StCBs, DCCBs)

### Non-Banking Financial Company (NBFC) Subtree
12. **Non-Banking Financial Company (`nbfc`)**
   - 13. **Deposit-Taking NBFC (`nbfc_d`)**
   - 14. **Non-Deposit Taking NBFC (`nbfc_nd`)**
   - 15. **Systemically Important Non-Deposit Taking NBFC (`nbfc_nd_si`)**
   - 16. **Investment and Credit Company (`nbfc_icc`)**
   - 17. **Micro Finance Institution (`nbfc_mfi`)**
   - 18. **Core Investment Company (`cic`)**
   - 19. **NBFC-Factor (`nbfc_factor`)**
   - 20. **Peer-to-Peer Lending Platform (`nbfc_p2p`)**
   - 21. **Account Aggregator (`nbfc_aa`)**
   - 22. **Housing Finance Company (`housing_finance_company`)** (HFCs)

### Statutory Financial Institutions
23. **All-India Financial Institution (`all_india_financial_institution`)** (AIFIs: NABARD, NHB, EXIM Bank, SIDBI, NaBFID)

### Payment System Operators (PSO) Subtree
24. **Payment System Operator (`payment_system_operator`)**
   - 25. **Payment Aggregator (`payment_aggregator`)** (PA, PA-CB)
   - 26. **Payment Gateway (`payment_gateway`)** (PG)
   - 27. **Prepaid Payment Instrument Issuer (`prepaid_payment_instrument_issuer`)** (PPIs)
   - 28. **Trade Receivables Discounting System (`trade_receivables_discounting_system`)** (TReDS)

### Capital Market Intermediaries (SEBI) Subtree
29. **SEBI Regulated Intermediary (`sebi_market_intermediary`)**
   - 30. **Stock Broker (`stock_broker`)**
   - 31. **Depository Participant (`depository_participant`)** (DPs)
   - 32. **Asset Management Company (`asset_management_company`)** (AMCs, Mutual Funds)
   - 33. **Alternative Investment Fund (`alternative_investment_fund`)** (AIFs Category I/II/III)
   - 34. **Portfolio Manager (`portfolio_manager`)** (PMS)
   - 35. **Credit Rating Agency (`credit_rating_agency`)** (CRAs)

---

## 3. Query Scoping and Inheritance Semantics
When a user query specifies or implies an entity scope (e.g. `entity_scope="nbfc"`):
- All circular provisions tagged with `nbfc` or any of its child entity categories (`nbfc_d`, `nbfc_nd_si`, `cic`, `housing_finance_company`, etc.) match.
- Unrelated subtrees (e.g. `commercial_bank`, `sebi_market_intermediary`) are filtered out when strict scoping is enforced.
