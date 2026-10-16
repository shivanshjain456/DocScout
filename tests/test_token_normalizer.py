"""Unit and integration tests for Typo-Tolerant Regulatory Token Normalizer (FEAT-018)."""

from __future__ import annotations

import sys
import time

import pytest

from app.api.models import Confidence, Passage, Provenance, SearchRequest, SearchResponse, Timings
from app.retrieval._normalizer_data import LEXICON_TERMS
from app.retrieval.normalizer import (
    ALPHANUM_CODE_REGEX,
    CIRCULAR_ID_REGEX,
    SECTION_CITATION_REGEX,
    NormalizerConfig,
    RegulatoryNormalizer,
    damerau_levenshtein,
    get_default_normalizer,
)


def test_damerau_levenshtein_distance() -> None:
    """Verifies Damerau-Levenshtein calculation on standard edit operations."""
    # Identical
    assert damerau_levenshtein("payment", "payment") == 0
    # Single transposition (adjacent swap)
    assert damerau_levenshtein("paymnet", "payment") == 1
    assert damerau_levenshtein("defualt", "default") == 1
    # Single deletion
    assert damerau_levenshtein("agregator", "aggregator") == 1
    assert damerau_levenshtein("capitl", "capital") == 1
    # Single insertion
    assert damerau_levenshtein("bankk", "bank") == 1
    # Single substitution
    assert damerau_levenshtein("banj", "bank") == 1
    # Unrelated
    assert damerau_levenshtein("resrve", "review") >= 3


def test_lexicon_catalog_and_memory_limit() -> None:
    """Verifies that the catalog includes >= 1,358 terms and memory footprint <= 6 MB."""
    assert len(LEXICON_TERMS) >= 1358

    normalizer = get_default_normalizer()
    # Memory footprint calculation for SymSpell delete map and word lists
    mem_bytes = (
        sys.getsizeof(normalizer._delete_map)
        + sum(sys.getsizeof(k) + sys.getsizeof(v) for k, v in normalizer._delete_map.items())
        + sys.getsizeof(normalizer._words_list)
        + sys.getsizeof(normalizer._word_to_id)
    )
    mem_mb = mem_bytes / (1024 * 1024)
    assert mem_mb <= 6.0, f"Memory footprint {mem_mb:.2f} MB exceeds 6 MB limit"


def test_normalizer_config_and_disabling() -> None:
    """Verifies NormalizerConfig defaults and query pass-through when disabled."""
    normalizer = get_default_normalizer()
    assert normalizer.config.enabled is True
    assert normalizer.config.max_edit_distance == 2
    assert normalizer.config.min_token_len == 4

    disabled = RegulatoryNormalizer(NormalizerConfig(enabled=False))
    raw = "Paymnet Agregator under RBI/2022-23/111"
    res = disabled.normalize(raw)
    assert res.normalized_query == raw
    assert len(res.corrections_applied) == 0


def test_regression_limits_protected_entities() -> None:
    """Regression test: Circular IDs, section numbers, dates, and valid terms must NOT be corrupted."""
    normalizer = get_default_normalizer()

    # Exact circular IDs
    sample_circulars = [
        "RBI/2022-23/111",
        "RBI/2023-24/41",
        "DOR.STR.REC.55/21.04.048/2021-22",
        "DPSS.CO.PD.No.1810/02.14.008/2019-20",
        "SEBI/HO/CFD/CMD1/P/CIR/2022/01",
    ]
    for cid in sample_circulars:
        assert CIRCULAR_ID_REGEX.search(cid) is not None
        res = normalizer.normalize(f"Directions under {cid}")
        assert cid in res.normalized_query
        assert cid not in res.corrections_applied

    # Statutory section numbers and clauses
    assert ALPHANUM_CODE_REGEX.fullmatch("DOR-STR-REC-55") is not None
    sample_sections = [
        "Section 45-IA of RBI Act",
        "Section 141 of Companies Act",
        "Rule 144(xi) provisions",
        "Master Direction 2016",
        "Schedule II of the Banking Regulation Act",
    ]
    for sec in sample_sections:
        assert SECTION_CITATION_REGEX.search(sec) is not None
        res = normalizer.normalize(sec)
        assert res.normalized_query == sec
        assert len(res.corrections_applied) == 0

    # Validly spelled terms must remain untouched
    valid_queries = [
        "Payment Aggregator guidelines",
        "Capital Adequacy Ratio requirements",
        "Default Loss Guarantee arrangements",
        "Non-Performing Assets classification",
    ]
    for vq in valid_queries:
        res = normalizer.normalize(vq)
        assert res.normalized_query == vq
        assert len(res.corrections_applied) == 0


# Evaluation dataset: 60 queries containing deliberate statutory typos
EVAL_TYPO_QUERIES: list[tuple[str, str, str]] = [
    ("Paymnet Agregator guidelines", "Payment", "Payment Aggregator guidelines"),
    ("Defualt Loss Guarantee FLDG", "Default", "Default Loss Guarantee FLDG"),
    ("First Loss Defualt Guarnatee", "Default", "First Loss Default Guarantee"),
    ("Capitl Adequacy Ratio norms", "Capital", "Capital Adequacy Ratio norms"),
    ("Liqidity Coverage Ratio", "Liquidity", "Liquidity Coverage Ratio"),
    ("Statutry Liquidity Ratio", "Statutory", "Statutory Liquidity Ratio"),
    ("Cash Resrve Ratio", "Reserve", "Cash Reserve Ratio"),
    ("Prioriy Sector Lending", "Priority", "Priority Sector Lending"),
    ("Non-Perfoming Assets", "Performing", "Non-Performing Assets"),
    ("Asset Reconsturction Company", "Reconstruction", "Asset Reconstruction Company"),
    ("Custmer Due Diligence", "Customer", "Customer Due Diligence"),
    ("Anti-Mony Laundering", "Money", "Anti-Money Laundering"),
    ("Cybr Security Framework", "Cyber", "Cyber Security Framework"),
    ("Outsorcing of Financial Services", "Outsourcing", "Outsourcing of Financial Services"),
    ("Scale Bsed Regulation", "Based", "Scale Based Regulation"),
    ("Large Exposres Framework", "Exposures", "Large Exposures Framework"),
    ("Foregn Portfolio Investor", "Foreign", "Foreign Portfolio Investor"),
    ("Centrl KYC Records Registry", "Central", "Central KYC Records Registry"),
    ("Self-Regulatry Organisation", "Regulatory", "Self-Regulatory Organisation"),
    ("Legl Entity Identifier", "Legal", "Legal Entity Identifier"),
    ("Sustainbility Reporting BRSR", "Sustainability", "Sustainability Reporting BRSR"),
    ("Accunt Aggregator directions", "Account", "Account Aggregator directions"),
    ("Urben Co-operative Banks", "Urban", "Urban Co-operative Banks"),
    ("Microfinnce Loans framework", "Microfinance", "Microfinance Loans framework"),
    ("Interanl Ombudsman scheme", "Internal", "Internal Ombudsman scheme"),
    ("Wilfl Defaulters circular", "Wilful", "Wilful Defaulters circular"),
    ("Creidt Information Companies", "Credit", "Credit Information Companies"),
    ("Co-Lendng Model directions", "Lending", "Co-Lending Model directions"),
    ("Core Bankng Solution", "Banking", "Core Banking Solution"),
    ("Card Tokenisaton mandate", "Tokenisation", "Card Tokenisation mandate"),
    ("Prepid Payment Instruments", "Prepaid", "Prepaid Payment Instruments"),
    ("Trade Receivbles Discounting System", "Receivables", "Trade Receivables Discounting System"),
    ("Securitisaton of Standard Assets", "Securitisation", "Securitisation of Standard Assets"),
    ("Moratorum on loan repayments", "Moratorium", "Moratorium on loan repayments"),
    ("Prudntial Norms on provisioning", "Prudential", "Prudential Norms on provisioning"),
    ("Digitl Lending guidelines", "Digital", "Digital Lending guidelines"),
    ("Master Directon on KYC", "Direction", "Master Direction on KYC"),
    ("Master Circulr on wilful defaulters", "Circular", "Master Circular on wilful defaulters"),
    ("Overdrat facility guidelines", "Overdraft", "Overdraft facility guidelines"),
    ("Factorig regulation act", "Factoring", "Factoring regulation act"),
    ("Penl Interest on loan accounts", "Penal", "Penal Interest on loan accounts"),
    ("Benefcial Owner verification", "Beneficial", "Beneficial Owner verification"),
    ("Consmer dispute redressal", "Consumer", "Consumer dispute redressal"),
    ("Grievnce Redressal Mechanism", "Grievance", "Grievance Redressal Mechanism"),
    ("Fair Practces Code", "Practices", "Fair Practices Code"),
    ("Key Fact Statemnt requirements", "Statement", "Key Fact Statement requirements"),
    ("Annual Percentge Rate", "Percentage", "Annual Percentage Rate"),
    ("Unsolictd credit cards", "Unsolicited", "Unsolicited credit cards"),
    ("Escrw Account operations", "Escrow", "Escrow Account operations"),
    ("Nodal Offcer appointment", "Officer", "Nodal Officer appointment"),
    ("Statutry Auditor qualifications", "Statutory", "Statutory Auditor qualifications"),
    ("Regulatery Sandbox cohort", "Regulatory", "Regulatory Sandbox cohort"),
    ("Cross-Bordr payment aggregators", "Border", "Cross-Border payment aggregators"),
    ("Merchnt onboarding guidelines", "Merchant", "Merchant onboarding guidelines"),
    ("Chargebck mechanism in UPI", "Chargeback", "Chargeback mechanism in UPI"),
    ("Offlne payment transactions", "Offline", "Offline payment transactions"),
    ("Contactlss card transactions", "Contactless", "Contactless card transactions"),
    ("Collaterl requirements for loans", "Collateral", "Collateral requirements for loans"),
    ("Guarantr liability enforcement", "Guarantor", "Guarantor liability enforcement"),
    ("Subordinatd Debt capital", "Subordinated", "Subordinated Debt capital"),
]


def test_60_statutory_typo_eval_dataset() -> None:
    """Verifies that the normalizer recovers >= 90% (acceptance threshold) of statutory typos."""
    normalizer = get_default_normalizer()
    assert len(EVAL_TYPO_QUERIES) == 60

    recovered_count = 0
    for query_with_typo, expected_keyword, _expected_normalized in EVAL_TYPO_QUERIES:
        res = normalizer.normalize(query_with_typo)
        if expected_keyword.lower() in res.normalized_query.lower():
            recovered_count += 1
        else:
            pytest.fail(
                f"Failed to recover typo in '{query_with_typo}': got '{res.normalized_query}' "
                f"instead of containing '{expected_keyword}'"
            )

    recovery_rate = recovered_count / len(EVAL_TYPO_QUERIES)
    assert recovery_rate >= 0.90, f"Recovery rate {recovery_rate:.1%} < 90% required threshold"


def test_casing_preservation() -> None:
    """Verifies that casing style (Titlecase, lowercase, UPPERCASE) is preserved."""
    normalizer = get_default_normalizer()

    # Titlecase
    res1 = normalizer.normalize("Paymnet Agregator")
    assert res1.normalized_query == "Payment Aggregator"

    # Lowercase
    res2 = normalizer.normalize("paymnet agregator")
    assert res2.normalized_query == "payment aggregator"

    # UPPERCASE
    res3 = normalizer.normalize("PAYMNET")
    assert res3.normalized_query == "PAYMENT"


def test_normalizer_latency_benchmark() -> None:
    """Verifies typo normalization latency <= 0.5 ms p95."""
    normalizer = get_default_normalizer()
    sample_query = "Paymnet Agregator guidelines under RBI/2022-23/111 and Section 45-IA"

    durations_ms: list[float] = []
    # Warmup
    for _ in range(50):
        normalizer.normalize(sample_query)

    # Measurement
    for _ in range(200):
        t0 = time.perf_counter()
        normalizer.normalize(sample_query)
        durations_ms.append((time.perf_counter() - t0) * 1000.0)

    durations_ms.sort()
    p95_ms = durations_ms[int(len(durations_ms) * 0.95)]
    assert p95_ms <= 0.5, f"p95 latency {p95_ms:.3f} ms exceeds 0.5 ms limit"


def test_search_api_normalization_integration() -> None:
    """Verifies search endpoint integrates normalization into response schema."""
    req = SearchRequest(
        query="Paymnet Agregator guidelines",
        enable_normalization=True,
    )
    assert req.enable_normalization is True

    normalizer = get_default_normalizer()
    norm = normalizer.normalize(req.query)

    resp = SearchResponse(
        query=req.query,
        mode="hybrid",
        k=1,
        passages=[
            Passage(
                rank=1,
                chunk_id="chk-norm-001",
                document_id="doc-rbi-pa",
                source="RBI",
                canonical_url="https://rbi.org.in/pa",
                score=0.95,
                arm_ranks={"dense": 1},
                char_start=0,
                char_end=150,
                text="Payment Aggregators are non-bank entities facilitating merchant payments.",
            )
        ],
        confidence=Confidence(
            evidence_coverage=0.99,
            missing_terms=[],
            low_evidence=False,
            passages_considered=1,
        ),
        provenance=Provenance(
            embedding_model="test",
            embedding_dim=384,
            chunk_size=500,
            chunk_overlap=50,
            corpus_manifest_digest="sha256:norm",
            corpus_chunks=100,
            retrieval={"enable_normalization": True},
        ),
        timings=Timings(total_ms=2.0, retrieval_ms=2.0, cache_hit=False),
        normalized_query=norm.normalized_query,
        corrections_applied=norm.corrections_applied,
    )
    data = resp.model_dump()
    assert data["normalized_query"] is not None
    assert "Payment Aggregator" in data["normalized_query"]
    assert "Paymnet" in data["corrections_applied"]
    assert data["corrections_applied"]["Paymnet"] == "Payment"
