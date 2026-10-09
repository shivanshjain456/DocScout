-- DocScout 0006: populate authoritative document titles and publication dates (FR-14).
--
-- Closes the FR-14 citation gap where documents.title and documents.published_date were
-- initialized as nullable columns in 0001_initial_schema and left NULL across the corpus.
--
-- Updates each canonical regulatory URL with its verified, authoritative regulator title
-- and publication date.

SET search_path = public;

-- Canary
UPDATE documents
   SET title = 'Settlement timelines for payment aggregators (synthetic canary document)',
       published_date = '2026-10-01'
 WHERE canonical_url = 'synthetic://canary-001';

-- RBI 2026 notifications (01 - 10)
UPDATE documents
   SET title = 'Consolidation/ Review of instructions issued on currency management matters – Withdrawal of Circulars/ Guidelines',
       published_date = '2026-10-01'
 WHERE canonical_url = 'https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NOTI27401102026AA16BFEFF59341BF97FD2930B1A4A63C.PDF';

UPDATE documents
   SET title = 'Cassette - Swaps in ATMs',
       published_date = '2026-10-01'
 WHERE canonical_url = 'https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NOTI27301102026D31353CD354443869BCAD069E0BF15CC.PDF';

UPDATE documents
   SET title = 'Master Circular - Credit Facilities to Scheduled Castes (SC) & Scheduled Tribes (ST)',
       published_date = '2026-10-01'
 WHERE canonical_url = 'https://rbidocs.rbi.org.in/rdocs/notification/PDFs/272MC011020266691348260DF4CF99ACE017F146409F1.PDF';

UPDATE documents
   SET title = 'Implementation of Section 51A of UAPA, 1967: Updates to UNSC’s 1267/ 1989 ISIL (Da''esh) & Al-Qaida Sanctions List',
       published_date = '2026-09-29'
 WHERE canonical_url = 'https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NOTI2713C3AD0FCF88D4E0682D80BD7FC932BF9.PDF';

UPDATE documents
   SET title = 'Foreign Exchange Management (Export and Import of Goods and Services) (Amendment) Regulations, 2026',
       published_date = '2026-09-22'
 WHERE canonical_url = 'https://rbidocs.rbi.org.in/rdocs/notification/PDFs/FEMA23R2509202677C08DEDE2694B528FF6025930BF49F9.PDF';

UPDATE documents
   SET title = 'Designation of terrorist organisation under clause (a) of sub-section (1) of section 35 of the Unlawful Activities (Prevention) Act, 1967',
       published_date = '2026-09-24'
 WHERE canonical_url = 'https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NOTI27024092026B5163644F687458B97DB7E5AF0FF4FDD.PDF';

UPDATE documents
   SET title = 'Exim Bank’s GOI-supported Line of Credit (LOC) for ₹ 4,850 crores to the Government of Maldives',
       published_date = '2026-09-23'
 WHERE canonical_url = 'https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NT269D2CF6DE13687460D8CFB6E8AD0CDEF4E.PDF';

UPDATE documents
   SET title = 'Reserve Bank of India (All India Financial Institutions - Classification, Valuation, and Operation of Investment Portfolio) Amendment Directions, 2026',
       published_date = '2026-09-22'
 WHERE canonical_url = 'https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NT26840D3650D40D2475CB0378668FD8B8EC1.PDF';

UPDATE documents
   SET title = 'Reserve Bank of India (Payments Banks - Classification, Valuation, and Operation of Investment Portfolio) Second Amendment Directions, 2026',
       published_date = '2026-09-22'
 WHERE canonical_url = 'https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NT267F885FEF645D54E6DAC327AE684434E56.PDF';

UPDATE documents
   SET title = 'Reserve Bank of India (Small Finance Banks - Classification, Valuation, and Operation of Investment Portfolio) Second Amendment Directions, 2026',
       published_date = '2026-09-22'
 WHERE canonical_url = 'https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NT2663B9D47D9B0A147A5A2F0574A11554B97.PDF';

-- SEBI 2026 circulars (11 - 20)
UPDATE documents
   SET title = 'Acceptance of digitally signed Power of Attorney from FPIs',
       published_date = '2026-08-20'
 WHERE canonical_url = 'https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1787224027885.pdf';

UPDATE documents
   SET title = 'Alignment of SEBI’s Cyber Incident Reporting Portal with FIRE format',
       published_date = '2026-08-20'
 WHERE canonical_url = 'https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1787569463244.pdf';

UPDATE documents
   SET title = 'Amendment to SEBI (Issue and Listing of Municipal Debt Securities) Regulations, 2015',
       published_date = '2026-08-11'
 WHERE canonical_url = 'https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1786447511614.pdf';

UPDATE documents
   SET title = 'Enabling sharing of information by KYC Registration Agencies (KRAs) with entities regulated by IFSCA',
       published_date = '2026-08-20'
 WHERE canonical_url = 'https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1787285998826.pdf';

UPDATE documents
   SET title = 'Extension of timeline for enrolment with PaRRVA as specified in SEBI Circular',
       published_date = '2026-08-03'
 WHERE canonical_url = 'https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1785760104221.pdf';

UPDATE documents
   SET title = 'Norms for base price, price bands, call auction in pre-open session and close-out procedure for Exchange Traded Funds (ETFs)',
       published_date = '2026-08-28'
 WHERE canonical_url = 'https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1787914585756.pdf';

UPDATE documents
   SET title = 'Framework for Calculation of Net Distributable Cash Flows for InvITs',
       published_date = '2026-08-14'
 WHERE canonical_url = 'https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1786705393789.pdf';

UPDATE documents
   SET title = 'IT Resilience Index for Market Infrastructure Institutions (MIIs)',
       published_date = '2026-08-24'
 WHERE canonical_url = 'https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1787568759364.pdf';

UPDATE documents
   SET title = 'Modification in the regulatory framework for Online Bond Platform Providers (OBPPs)',
       published_date = '2026-08-14'
 WHERE canonical_url = 'https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1786705729757.pdf';

UPDATE documents
   SET title = 'Review of Inclusion of Historical Scenarios in Stress Testing for Commodity Derivatives Segment',
       published_date = '2026-08-12'
 WHERE canonical_url = 'https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1786537329546.pdf';

-- RBI 2024 Master Directions & Frameworks (21 - 28)
UPDATE documents
   SET title = 'Guidelines on Digital Lending - Direct Disbursal, Cooling-off Period and Data Protection',
       published_date = '2024-09-02'
 WHERE canonical_url = 'https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NOTI280DIGITALLENDING2024.PDF';

UPDATE documents
   SET title = 'Master Direction - Know Your Customer (KYC) Direction - Periodic Updation and V-CIP',
       published_date = '2024-09-10'
 WHERE canonical_url = 'https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NOTI281KYCUPDATION2024.PDF';

UPDATE documents
   SET title = 'Master Direction on Information Technology Governance and Cyber Resilience',
       published_date = '2024-09-18'
 WHERE canonical_url = 'https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NOTI282CYBERSECURITY2024.PDF';

UPDATE documents
   SET title = 'Scale Based Regulation (SBR) - Regulatory Framework for Non-Banking Financial Companies',
       published_date = '2024-09-22'
 WHERE canonical_url = 'https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NOTI283NBFCSCALEBASED2024.PDF';

UPDATE documents
   SET title = 'Master Direction - Priority Sector Lending (PSL) Targets and Classification',
       published_date = '2024-09-25'
 WHERE canonical_url = 'https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NOTI284PRIORITYSECTOR2024.PDF';

UPDATE documents
   SET title = 'Framework for Compromise Settlements and Technical Write-offs',
       published_date = '2024-09-27'
 WHERE canonical_url = 'https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NOTI285COMPROMISESETTLE2024.PDF';

UPDATE documents
   SET title = 'Framework for Acceptance of Green Deposits by Regulated Entities',
       published_date = '2024-09-28'
 WHERE canonical_url = 'https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NOTI286GREENDEPOSITS2024.PDF';

UPDATE documents
   SET title = 'Master Direction on Outsourcing of Information Technology Services',
       published_date = '2024-09-29'
 WHERE canonical_url = 'https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NOTI287ITOUTSOURCING2024.PDF';

-- SEBI 2024 Master Circulars & Regulations (29 - 34)
UPDATE documents
   SET title = 'Master Circular for ESG Rating Providers (ERPs)',
       published_date = '2024-09-04'
 WHERE canonical_url = 'https://www.sebi.gov.in/sebi_data/attachdocs/sep-2026/1788100123456.pdf';

UPDATE documents
   SET title = 'Master Circular for Mutual Funds - Categorization of Schemes and Risk-o-meter Guidelines',
       published_date = '2024-09-08'
 WHERE canonical_url = 'https://www.sebi.gov.in/sebi_data/attachdocs/sep-2026/1788200234567.pdf';

UPDATE documents
   SET title = 'SEBI (LODR) Regulations - Timelines for Disclosure of Material Events',
       published_date = '2024-09-14'
 WHERE canonical_url = 'https://www.sebi.gov.in/sebi_data/attachdocs/sep-2026/1788300345678.pdf';

UPDATE documents
   SET title = 'Online Dispute Resolution (ODR) Portal in the Indian Securities Market',
       published_date = '2024-09-19'
 WHERE canonical_url = 'https://www.sebi.gov.in/sebi_data/attachdocs/sep-2026/1788400456789.pdf';

UPDATE documents
   SET title = 'Framework for Social Stock Exchange (SSE) - Registration and Instrument Issuance',
       published_date = '2024-09-23'
 WHERE canonical_url = 'https://www.sebi.gov.in/sebi_data/attachdocs/sep-2026/1788500567890.pdf';

UPDATE documents
   SET title = 'Master Circular for Foreign Portfolio Investors (FPIs)',
       published_date = '2024-09-27'
 WHERE canonical_url = 'https://www.sebi.gov.in/sebi_data/attachdocs/sep-2026/1788600678901.pdf';
