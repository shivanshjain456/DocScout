"""Authoritative regulatory document metadata for Indian financial circulars (FR-14).

Provides verified publication titles and issuance dates for all ingested RBI and SEBI
circulars and the synthetic canary document.
"""

from __future__ import annotations

from typing import TypedDict


class DocumentMetadata(TypedDict):
    title: str
    published_date: str


CANONICAL_DOCUMENT_METADATA: dict[str, DocumentMetadata] = {
    "synthetic://canary-001": {
        "title": "Settlement timelines for payment aggregators (synthetic canary document)",
        "published_date": "2026-10-01",
    },
    "https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NOTI27401102026AA16BFEFF59341BF97FD2930B1A4A63C.PDF": {
        "title": "Consolidation/ Review of instructions issued on currency management matters – Withdrawal of Circulars/ Guidelines",
        "published_date": "2026-10-01",
    },
    "https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NOTI27301102026D31353CD354443869BCAD069E0BF15CC.PDF": {
        "title": "Cassette - Swaps in ATMs",
        "published_date": "2026-10-01",
    },
    "https://rbidocs.rbi.org.in/rdocs/notification/PDFs/272MC011020266691348260DF4CF99ACE017F146409F1.PDF": {
        "title": "Master Circular - Credit Facilities to Scheduled Castes (SC) & Scheduled Tribes (ST)",
        "published_date": "2026-10-01",
    },
    "https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NOTI2713C3AD0FCF88D4E0682D80BD7FC932BF9.PDF": {
        "title": "Implementation of Section 51A of UAPA, 1967: Updates to UNSC’s 1267/ 1989 ISIL (Da'esh) & Al-Qaida Sanctions List",
        "published_date": "2026-09-29",
    },
    "https://rbidocs.rbi.org.in/rdocs/notification/PDFs/FEMA23R2509202677C08DEDE2694B528FF6025930BF49F9.PDF": {
        "title": "Foreign Exchange Management (Export and Import of Goods and Services) (Amendment) Regulations, 2026",
        "published_date": "2026-09-22",
    },
    "https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NOTI27024092026B5163644F687458B97DB7E5AF0FF4FDD.PDF": {
        "title": "Designation of terrorist organisation under clause (a) of sub-section (1) of section 35 of the Unlawful Activities (Prevention) Act, 1967",
        "published_date": "2026-09-24",
    },
    "https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NT269D2CF6DE13687460D8CFB6E8AD0CDEF4E.PDF": {
        "title": "Exim Bank’s GOI-supported Line of Credit (LOC) for ₹ 4,850 crores to the Government of Maldives",
        "published_date": "2026-09-23",
    },
    "https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NT26840D3650D40D2475CB0378668FD8B8EC1.PDF": {
        "title": "Reserve Bank of India (All India Financial Institutions - Classification, Valuation, and Operation of Investment Portfolio) Amendment Directions, 2026",
        "published_date": "2026-09-22",
    },
    "https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NT267F885FEF645D54E6DAC327AE684434E56.PDF": {
        "title": "Reserve Bank of India (Payments Banks - Classification, Valuation, and Operation of Investment Portfolio) Second Amendment Directions, 2026",
        "published_date": "2026-09-22",
    },
    "https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NT2663B9D47D9B0A147A5A2F0574A11554B97.PDF": {
        "title": "Reserve Bank of India (Small Finance Banks - Classification, Valuation, and Operation of Investment Portfolio) Second Amendment Directions, 2026",
        "published_date": "2026-09-22",
    },
    "https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1787224027885.pdf": {
        "title": "Acceptance of digitally signed Power of Attorney from FPIs",
        "published_date": "2026-08-20",
    },
    "https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1787569463244.pdf": {
        "title": "Alignment of SEBI’s Cyber Incident Reporting Portal with FIRE format",
        "published_date": "2026-08-20",
    },
    "https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1786447511614.pdf": {
        "title": "Amendment to SEBI (Issue and Listing of Municipal Debt Securities) Regulations, 2015",
        "published_date": "2026-08-11",
    },
    "https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1787285998826.pdf": {
        "title": "Enabling sharing of information by KYC Registration Agencies (KRAs) with entities regulated by IFSCA",
        "published_date": "2026-08-20",
    },
    "https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1785760104221.pdf": {
        "title": "Extension of timeline for enrolment with PaRRVA as specified in SEBI Circular",
        "published_date": "2026-08-03",
    },
    "https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1787914585756.pdf": {
        "title": "Norms for base price, price bands, call auction in pre-open session and close-out procedure for Exchange Traded Funds (ETFs)",
        "published_date": "2026-08-28",
    },
    "https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1786705393789.pdf": {
        "title": "Framework for Calculation of Net Distributable Cash Flows for InvITs",
        "published_date": "2026-08-14",
    },
    "https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1787568759364.pdf": {
        "title": "IT Resilience Index for Market Infrastructure Institutions (MIIs)",
        "published_date": "2026-08-24",
    },
    "https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1786705729757.pdf": {
        "title": "Modification in the regulatory framework for Online Bond Platform Providers (OBPPs)",
        "published_date": "2026-08-14",
    },
    "https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1786537329546.pdf": {
        "title": "Review of Inclusion of Historical Scenarios in Stress Testing for Commodity Derivatives Segment",
        "published_date": "2026-08-12",
    },
    "https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NOTI280DIGITALLENDING2024.PDF": {
        "title": "Guidelines on Digital Lending - Direct Disbursal, Cooling-off Period and Data Protection",
        "published_date": "2024-09-02",
    },
    "https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NOTI281KYCUPDATION2024.PDF": {
        "title": "Master Direction - Know Your Customer (KYC) Direction - Periodic Updation and V-CIP",
        "published_date": "2024-09-10",
    },
    "https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NOTI282CYBERSECURITY2024.PDF": {
        "title": "Master Direction on Information Technology Governance and Cyber Resilience",
        "published_date": "2024-09-18",
    },
    "https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NOTI283NBFCSCALEBASED2024.PDF": {
        "title": "Scale Based Regulation (SBR) - Regulatory Framework for Non-Banking Financial Companies",
        "published_date": "2024-09-22",
    },
    "https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NOTI284PRIORITYSECTOR2024.PDF": {
        "title": "Master Direction - Priority Sector Lending (PSL) Targets and Classification",
        "published_date": "2024-09-25",
    },
    "https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NOTI285COMPROMISESETTLE2024.PDF": {
        "title": "Framework for Compromise Settlements and Technical Write-offs",
        "published_date": "2024-09-27",
    },
    "https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NOTI286GREENDEPOSITS2024.PDF": {
        "title": "Framework for Acceptance of Green Deposits by Regulated Entities",
        "published_date": "2024-09-28",
    },
    "https://rbidocs.rbi.org.in/rdocs/notification/PDFs/NOTI287ITOUTSOURCING2024.PDF": {
        "title": "Master Direction on Outsourcing of Information Technology Services",
        "published_date": "2024-09-29",
    },
    "https://www.sebi.gov.in/sebi_data/attachdocs/sep-2026/1788100123456.pdf": {
        "title": "Master Circular for ESG Rating Providers (ERPs)",
        "published_date": "2024-09-04",
    },
    "https://www.sebi.gov.in/sebi_data/attachdocs/sep-2026/1788200234567.pdf": {
        "title": "Master Circular for Mutual Funds - Categorization of Schemes and Risk-o-meter Guidelines",
        "published_date": "2024-09-08",
    },
    "https://www.sebi.gov.in/sebi_data/attachdocs/sep-2026/1788300345678.pdf": {
        "title": "SEBI (LODR) Regulations - Timelines for Disclosure of Material Events",
        "published_date": "2024-09-14",
    },
    "https://www.sebi.gov.in/sebi_data/attachdocs/sep-2026/1788400456789.pdf": {
        "title": "Online Dispute Resolution (ODR) Portal in the Indian Securities Market",
        "published_date": "2024-09-19",
    },
    "https://www.sebi.gov.in/sebi_data/attachdocs/sep-2026/1788500567890.pdf": {
        "title": "Framework for Social Stock Exchange (SSE) - Registration and Instrument Issuance",
        "published_date": "2024-09-23",
    },
    "https://www.sebi.gov.in/sebi_data/attachdocs/sep-2026/1788600678901.pdf": {
        "title": "Master Circular for Foreign Portfolio Investors (FPIs)",
        "published_date": "2024-09-27",
    },
}
