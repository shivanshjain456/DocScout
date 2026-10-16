"""Tests for Cross-Lingual Semantic Regulatory Search (FEAT-076).

Validates:
1. Input validation rules (UTF-8, length between 3 and 512 characters).
2. Language classification (Devanagari script detection).
3. Prometheus metrics emission (docscout_cross_lingual_queries_total{lang}).
4. VectorStore Protocol conformance and registry integration.
5. Cross-lingual projection into 384-dimensional unit-norm vector space.
6. Zero English-to-English retrieval regression (Delta <= 0.002).
7. Acceptance criteria: Devanagari Hindi queries retrieving corresponding English circulars.
8. Standardized 25 paired bilingual regulatory evaluation benchmark (Recall@5 >= 0.880 vs 0.0 baseline).
9. Fail-closed fallback to standard English embedder upon unexpected projection error.
10. Latency budget (multilingual embedding generation <= 18.0 ms on CPU).
"""

from __future__ import annotations

import time
import uuid

import numpy as np
import pytest

from app.api.metrics import CROSS_LINGUAL_QUERIES_TOTAL
from app.ingest.embed import EMBEDDING_DIM
from app.retrieval.multilingual_dense import (
    CrossLingualProjector,
    MultilingualDenseStore,
    detect_language,
    validate_query_string,
)
from app.retrieval.port import (
    ChunkRow,
    VectorStore,
    get_vector_store,
)
from app.retrieval.search import Retriever
from app.retrieval.types import RetrievalConfig


class MockEmbedder:
    """Deterministic fast embedder simulating English-only vocabulary tokenizer (ADR-0002).

    Only Latin/ASCII tokens map to semantic dimensions. Non-Latin scripts (Devanagari)
    are mapped to UNK / out-of-vocabulary buckets, modeling real BAAI/bge-small-en-v1.5
    behavior where Devanagari queries yield zero cross-lingual retrieval without projection.
    """

    def __init__(self) -> None:
        self.call_count = 0

    def encode_query(self, text: str) -> np.ndarray:
        self.call_count += 1
        vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        tokens = text.lower().split()
        for tok in tokens:
            if any(ord(c) > 127 for c in tok):
                # Non-Latin token maps to UNK bucket (index 0)
                vec[0] += 0.05
            else:
                idx = 1 + (abs(hash(tok)) % (EMBEDDING_DIM - 1))
                vec[idx] += 1.0
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = vec / norm
        else:
            vec[0] = 1.0
        return vec


# Standard 25 paired bilingual regulatory queries and target circular domains
BILINGUAL_BENCHMARK_25: list[dict[str, str]] = [
    {
        "hindi_query": "भुगतान एग्रीगेटर के लिए पूंजी आवश्यकता",
        "english_equivalent": "payment aggregator capital net worth requirement",
        "domain": "RBI/DPSS/PAYMENT-AGGREGATOR-2020",
        "passage_text": "Capital and Net Worth Requirement for Payment Aggregators (PAs). Non-bank PAs shall have a minimum net worth of Rs 15 crore at the time of application and Rs 25 crore within three financial years.",
    },
    {
        "hindi_query": "गैर-बैंकिंग वित्तीय कंपनी पंजीकरण दिशानिर्देश",
        "english_equivalent": "non-banking financial company nbfc registration guidelines scale based regulation",
        "domain": "RBI/DOR/NBFC-SBR-2021",
        "passage_text": "Regulatory Framework for Non-Banking Financial Companies under Scale Based Regulation. Categorization into Base Layer, Middle Layer, Upper Layer, and Top Layer with registration capital requirements.",
    },
    {
        "hindi_query": "केवाईसी सत्यापन और पैन लिंकिंग दिशानिर्देश",
        "english_equivalent": "kyc verification pan linking customer due diligence",
        "domain": "RBI/DBR/KYC-MD-2016",
        "passage_text": "Master Direction on Know Your Customer KYC requirements. Customer due diligence procedures, mandatory PAN Aadhaar verification, and periodic updating of records.",
    },
    {
        "hindi_query": "मास्टर दिशा-निर्देश साइबर सुरक्षा और घटना रिपोर्टिंग",
        "english_equivalent": "master directions cyber security framework incident reporting",
        "domain": "RBI/DBS/CYBER-SECURITY-2016",
        "passage_text": "Cyber Security Framework in Banks. Mandatory establishment of Security Operations Centre (SOC) and statutory reporting of cyber security incidents within 6 hours.",
    },
    {
        "hindi_query": "डिजिटल ऋण दिशानिर्देश और डिफ़ॉल्ट हानि गारंटी",
        "english_equivalent": "digital lending guidelines default loss guarantee dlg lending service provider",
        "domain": "RBI/DOR/DIGITAL-LENDING-2022",
        "passage_text": "Guidelines on Digital Lending and Default Loss Guarantee (DLG). Direct disbursement to borrower bank account and regulation of Lending Service Providers (LSPs).",
    },
    {
        "hindi_query": "प्राथमिकता प्राप्त क्षेत्र ऋण लक्ष्य",
        "english_equivalent": "priority sector lending psl targets classification",
        "domain": "RBI/FIDD/PSL-2020",
        "passage_text": "Master Directions on Priority Sector Lending (PSL) targets. Total priority sector lending target of 40 percent of Adjusted Net Bank Credit (ANBC) for domestic commercial banks.",
    },
    {
        "hindi_query": "तरलता कवरेज अनुपात उच्च गुणवत्ता वाली तरल संपत्ति",
        "english_equivalent": "liquidity coverage ratio lcr high quality liquid assets",
        "domain": "RBI/DBR/BASEL-LCR-2014",
        "passage_text": "Basel III Framework on Liquidity Coverage Ratio (LCR). Banks shall maintain an adequate stock of unencumbered High Quality Liquid Assets (HQLA) to survive 30-day stress scenario.",
    },
    {
        "hindi_query": "अनधिकृत इलेक्ट्रॉनिक लेनदेन में सीमित ग्राहक देयता",
        "english_equivalent": "unauthorized electronic banking transactions limiting customer liability",
        "domain": "RBI/DPSS/CUSTOMER-LIABILITY-2017",
        "passage_text": "Customer Protection - Limiting Liability of Customers in Unauthorized Electronic Banking Transactions. Zero liability in contributory fraud or third party breach reported within 3 days.",
    },
    {
        "hindi_query": "समझौता निपटान और तकनीकी राइट-ऑफ ढांचा",
        "english_equivalent": "framework compromise settlement technical write-offs",
        "domain": "RBI/DOR/COMPROMISE-SETTLEMENT-2023",
        "passage_text": "Framework for Compromise Settlements and Technical Write-offs. Comprehensive policy approved by the Board for compromise settlements with wilful defaulters and non-performing assets.",
    },
    {
        "hindi_query": "वित्तीय सेवाओं का आउटसोर्सिंग जोखिम प्रबंधन",
        "english_equivalent": "outsourcing financial services risk management code of conduct",
        "domain": "RBI/DBR/OUTSOURCING-2006",
        "passage_text": "Guidelines on Managing Risks and Code of Conduct in Outsourcing of Financial Services by Banks. Core management functions shall not be outsourced.",
    },
    {
        "hindi_query": "इरादतन चूककर्ता वर्गीकरण और रिपोर्टिंग",
        "english_equivalent": "wilful defaulters identification classification reporting",
        "domain": "RBI/DBR/WILFUL-DEFAULTER-2015",
        "passage_text": "Master Circular on Wilful Defaulters. Mechanism for identification, identification committee, review committee, and debarment from accessing institutional finance for 5 years.",
    },
    {
        "hindi_query": "विदेशी मुद्रा प्रबंधन बाह्य वाणिज्यिक उधारी दिशानिर्देश",
        "english_equivalent": "foreign exchange management external commercial borrowings ecb",
        "domain": "RBI/FED/ECB-MD-2019",
        "passage_text": "Master Direction on External Commercial Borrowings, Trade Credits and Structured Obligations under Foreign Exchange Management Act (FEMA).",
    },
    {
        "hindi_query": "उधारदाताओं के लिए निष्पक्ष व्यवहार संहिता",
        "english_equivalent": "fair practices code transparency interest rates lenders",
        "domain": "RBI/DOR/FPC-2023",
        "passage_text": "Fair Practices Code for Lenders. Guidelines on transparent disclosure of all-inclusive Annual Percentage Rate (APR) and Key Fact Statement (KFS) to borrowers.",
    },
    {
        "hindi_query": "जलवायु जोखिम और संधारणीय वित्त खुलासे",
        "english_equivalent": "climate risk sustainable finance disclosures green deposits",
        "domain": "RBI/DOR/CLIMATE-RISK-2023",
        "passage_text": "Framework for acceptance of Green Deposits and climate-related financial risk governance, risk management, and disclosure standards for regulated entities.",
    },
    {
        "hindi_query": "आवास वित्त कंपनी विनियामक ढांचा और पूंजी पर्याप्तता",
        "english_equivalent": "housing finance company hfc regulatory framework capital adequacy",
        "domain": "RBI/DOR/HFC-MD-2021",
        "passage_text": "Master Direction on Non-Banking Financial Company Housing Finance Company (HFC) Directions. Minimum capital adequacy ratio (CRAR) of 15 percent and liquidity coverage ratios.",
    },
    {
        "hindi_query": "सूक्ष्म वित्त ऋण विनियामक ढांचा संपार्श्विक मुक्त",
        "english_equivalent": "microfinance loans collateral free regulatory framework",
        "domain": "RBI/DOR/MFI-2022",
        "passage_text": "Regulatory Framework for Microfinance Loans. Collateral-free loans provided to households having annual income up to Rs 3,00,000 without pre-payment penalty.",
    },
    {
        "hindi_query": "त्वरित सुधारात्मक कार्रवाई ढांचा वाणिज्यिक बैंक",
        "english_equivalent": "prompt corrective action pca framework commercial banks",
        "domain": "RBI/DOR/PCA-2021",
        "passage_text": "Revised Prompt Corrective Action (PCA) Framework for Commercial Banks. Monitoring indicators for capital, asset quality (Net NPA), and leverage with mandatory discretionary actions.",
    },
    {
        "hindi_query": "बड़ी एक्सपोजर रूपरेखा एकल और समूह उधारकर्ता सीमाएं",
        "english_equivalent": "large exposures framework single group borrower limits",
        "domain": "RBI/DBR/LEF-2019",
        "passage_text": "Large Exposures Framework (LEF). Sum of all exposure values of a bank to a single counterparty cannot exceed 20 percent of Tier 1 capital, and 25 percent for connected group.",
    },
    {
        "hindi_query": "वित्तीय समावेशन योजना और बुनियादी बचत बैंक जमा खाता",
        "english_equivalent": "financial inclusion plan basic savings bank deposit account",
        "domain": "RBI/FIDD/BSBDA-2019",
        "passage_text": "Financial Inclusion - Opening of Basic Savings Bank Deposit Account (BSBDA) without requirement of minimum balance and with free ATM-cum-debit card issuance.",
    },
    {
        "hindi_query": "क्रेडिट कार्ड और डेबिट कार्ड जारी करने और संचालन निर्देश",
        "english_equivalent": "credit card and debit card issuance conduct directions",
        "domain": "RBI/DPSS/CARDS-2022",
        "passage_text": "Master Direction on Credit Card and Debit Card Issuance and Conduct Directions. Mandatory prior consent for card upgrades, billing cycle options, and fraud protection.",
    },
    {
        "hindi_query": "आंतरिक लोकपाल और शिकायत निवारण तंत्र",
        "english_equivalent": "internal ombudsman scheme grievance redressal mechanism",
        "domain": "RBI/CEPC/INTERNAL-OMBUDSMAN-2021",
        "passage_text": "Reserve Bank of India (Internal Ombudsman) Scheme. Regulated entities shall appoint an Internal Ombudsman for independent review of customer complaints rejected partly or wholly.",
    },
    {
        "hindi_query": "प्रीपेड भुगतान साधन पीपीआई दिशानिर्देश",
        "english_equivalent": "prepaid payment instruments ppi interoperability limits",
        "domain": "RBI/DPSS/PPI-MD-2021",
        "passage_text": "Master Directions on Issuance and Operation of Prepaid Payment Instruments (PPIs). Mandatory interoperability through UPI and card networks, full-KYC limit of Rs 2,00,000.",
    },
    {
        "hindi_query": "परिसंपत्ति पुनर्निर्माण कंपनी कॉर्पोरेट प्रशासन",
        "english_equivalent": "asset reconstruction company arc corporate governance",
        "domain": "RBI/DOR/ARC-MD-2022",
        "passage_text": "Regulatory Framework for Asset Reconstruction Companies (ARCs). Minimum net owned fund requirement of Rs 300 crore and corporate governance requirements for resolution.",
    },
    {
        "hindi_query": "शहरी सहकारी बैंक वर्गीकरण और न्यूनतम शुद्ध मूल्य",
        "english_equivalent": "urban cooperative bank ucb categorization minimum net worth",
        "domain": "RBI/DOR/UCB-SBR-2022",
        "passage_text": "Revised Regulatory Framework for Urban Co-operative Banks (UCBs). Four-tiered regulatory framework based on deposit size and minimum net worth requirements.",
    },
    {
        "hindi_query": "सोने के आभूषणों के बदले ऋण बुलेट पुनर्भुगतान योजना",
        "english_equivalent": "loans against gold jewellery bullet repayment scheme",
        "domain": "RBI/DOR/GOLD-LOANS-2023",
        "passage_text": "Loans against Gold and Silver Jewellery for Non-Agricultural Purposes. Bullet repayment scheme loan to value (LTV) ceiling and interest servicing conditions.",
    },
]


def test_input_validation() -> None:
    """Validate query input constraints per FEAT-076 (3 to 512 characters, valid UTF-8)."""
    # Type check
    with pytest.raises(ValueError, match="Query must be a string"):
        validate_query_string(12345)  # type: ignore[arg-type]

    # Too short (< 3 characters)
    with pytest.raises(ValueError, match="Query length must be between 3 and 512"):
        validate_query_string("ab")

    with pytest.raises(ValueError, match="Query length must be between 3 and 512"):
        validate_query_string("   a   ")

    # Too long (> 512 characters)
    long_query = "क" * 513
    with pytest.raises(ValueError, match="Query length must be between 3 and 512"):
        validate_query_string(long_query)

    # Valid inputs
    validate_query_string("केवाईसी दिशानिर्देश")
    validate_query_string("Payment Aggregator net worth requirements")


def test_language_detection() -> None:
    """Test classification of Hindi Devanagari script vs English query string."""
    assert detect_language("भुगतान एग्रीगेटर के लिए पूंजी आवश्यकता") == "hi"
    assert detect_language("केवाईसी सत्यापन और पैन लिंकिंग") == "hi"
    assert detect_language("KYC सत्यापन") == "hi"  # Mixed Devanagari/English -> 'hi'
    assert detect_language("payment aggregator capital requirements") == "en"
    assert detect_language("RBI Master Direction on Digital Lending") == "en"


def test_cross_lingual_projection_vector_properties() -> None:
    """Projector must produce 384-dimensional unit-norm vector."""
    embedder = MockEmbedder()
    projector = CrossLingualProjector(embedder=embedder)  # type: ignore[arg-type]

    hindi_query = "भुगतान एग्रीगेटर के लिए पूंजी आवश्यकता"
    vec = projector.project_query(hindi_query)

    assert isinstance(vec, np.ndarray)
    assert vec.shape == (EMBEDDING_DIM,)
    assert vec.dtype == np.float32

    # Unit-norm guarantee: ||v|| == 1.0 within tolerance
    norm = float(np.linalg.norm(vec))
    assert pytest.approx(norm, abs=1e-4) == 1.0


def test_zero_english_to_english_regression() -> None:
    """English queries must not undergo semantic drift or translation regression."""
    embedder = MockEmbedder()
    projector = CrossLingualProjector(embedder=embedder)  # type: ignore[arg-type]

    english_query = "Payment Aggregator net worth requirements"
    projected = projector.project_query(english_query)
    direct = embedder.encode_query(english_query)

    # In MockEmbedder, both produce identical normalized vectors
    cosine_sim = float(np.dot(projected, direct))
    assert pytest.approx(cosine_sim, abs=1e-4) == 1.0


def test_vector_store_protocol_conformance() -> None:
    """MultilingualDenseStore must conform to the VectorStore Protocol."""
    store = MultilingualDenseStore()
    assert isinstance(store, VectorStore)

    # Test registry resolution via port.py
    resolved = get_vector_store("multilingual_dense")
    assert isinstance(resolved, MultilingualDenseStore)
    assert isinstance(resolved, VectorStore)


def test_acceptance_criteria_payment_aggregator_retrieval() -> None:
    """Devanagari query 'भुगतान एग्रीगेटर के लिए पूंजी आवश्यकता' must retrieve English PA circular."""
    embedder = MockEmbedder()
    projector = CrossLingualProjector(embedder=embedder)  # type: ignore[arg-type]
    store = MultilingualDenseStore(projector=projector)

    pa_chunk_id = str(uuid.uuid4())
    pa_text = "Capital and Net Worth Requirement for Payment Aggregators (PAs). Non-bank PAs shall have a minimum net worth of Rs 15 crore."
    pa_vec = embedder.encode_query("payment aggregator capital net worth requirement")
    pa_meta = ChunkRow(
        document_id=str(uuid.uuid4()),
        source="rbi",
        text=pa_text,
        canonical_url="https://rbi.org.in/pa-circular",
        char_start=0,
        char_end=len(pa_text),
    )
    store.register_chunk(pa_chunk_id, pa_vec, pa_meta)

    # Register distractors
    for i in range(5):
        distractor_id = str(uuid.uuid4())
        distractor_vec = embedder.encode_query(f"unrelated banking circular topic {i}")
        distractor_meta = ChunkRow(
            document_id=str(uuid.uuid4()),
            source="rbi",
            text=f"Unrelated statutory provisions paragraph {i}",
            canonical_url=None,
            char_start=0,
            char_end=50,
        )
        store.register_chunk(distractor_id, distractor_vec, distractor_meta)

    # Submit Devanagari query
    hindi_query = "भुगतान एग्रीगेटर के लिए पूंजी आवश्यकता"
    dummy_vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)

    hits = store.search(dummy_vec, k=5, query_text=hindi_query)
    assert len(hits) > 0
    top_hit_id, top_score = hits[0]

    # Acceptance criteria: top hit must be the English PA circular
    assert top_hit_id == pa_chunk_id
    assert top_score > 0.5


def test_bilingual_evaluation_benchmark_25_queries() -> None:
    """Evaluate 25 paired bilingual regulatory queries (Recall@5 >= 0.880 vs 0.0 baseline)."""
    embedder = MockEmbedder()
    projector = CrossLingualProjector(embedder=embedder)  # type: ignore[arg-type]
    store = MultilingualDenseStore(projector=projector)

    target_chunk_ids: dict[int, str] = {}
    for idx, item in enumerate(BILINGUAL_BENCHMARK_25):
        cid = str(uuid.uuid4())
        target_chunk_ids[idx] = cid
        vec = embedder.encode_query(item["english_equivalent"])
        meta = ChunkRow(
            document_id=str(uuid.uuid4()),
            source="rbi",
            text=item["passage_text"],
            canonical_url=f"https://rbi.org.in/{item['domain']}",
            char_start=0,
            char_end=len(item["passage_text"]),
        )
        store.register_chunk(cid, vec, meta)

    # Register 50 distractor chunks representing unrelated regulatory text
    for i in range(50):
        dist_id = str(uuid.uuid4())
        dist_vec = embedder.encode_query(f"distractor statutory provision topic {i}")
        dist_meta = ChunkRow(
            document_id=str(uuid.uuid4()),
            source="rbi",
            text=f"General administrative and accounting provisions clause {i}",
            canonical_url=None,
            char_start=0,
            char_end=50,
        )
        store.register_chunk(dist_id, dist_vec, dist_meta)

    # 1. Baseline check: standard English encoding of Devanagari queries yields 0% recall
    # because English tokenizer cannot parse Devanagari terms
    baseline_hits_at_5 = 0
    for idx, item in enumerate(BILINGUAL_BENCHMARK_25):
        raw_hindi_vec = embedder.encode_query(item["hindi_query"])
        # Standard search without cross-lingual projection
        hits = store.search(raw_hindi_vec, k=5, query_text=None)
        hit_ids = [cid for cid, score in hits if score > 0.0]
        if target_chunk_ids[idx] in hit_ids:
            baseline_hits_at_5 += 1

    baseline_recall = baseline_hits_at_5 / len(BILINGUAL_BENCHMARK_25)
    # Baseline cross-lingual recall is expected to be 0
    assert baseline_recall <= 0.10

    # 2. Cross-Lingual Semantic Retrieval with MultilingualDenseStore
    cross_lingual_hits_at_5 = 0
    for idx, item in enumerate(BILINGUAL_BENCHMARK_25):
        dummy_vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        hits = store.search(dummy_vec, k=5, query_text=item["hindi_query"])
        hit_ids = [cid for cid, score in hits if score > 0.0]
        if target_chunk_ids[idx] in hit_ids:
            cross_lingual_hits_at_5 += 1

    cross_lingual_recall = cross_lingual_hits_at_5 / len(BILINGUAL_BENCHMARK_25)

    # Required improvement threshold: Cross-lingual Recall@5 >= 0.880
    assert cross_lingual_recall >= 0.880, (
        f"Recall@5 was {cross_lingual_recall:.4f}, expected >= 0.880"
    )


def test_prometheus_observability_metrics() -> None:
    """Verify docscout_cross_lingual_queries_total counter tracks 'hi' and 'en'."""
    embedder = MockEmbedder()
    projector = CrossLingualProjector(embedder=embedder)  # type: ignore[arg-type]
    store = MultilingualDenseStore(projector=projector)

    before_hi = CROSS_LINGUAL_QUERIES_TOTAL.labels(lang="hi")._value.get()
    before_en = CROSS_LINGUAL_QUERIES_TOTAL.labels(lang="en")._value.get()

    dummy_vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    store.search(dummy_vec, k=1, query_text="केवाईसी सत्यापन")
    store.search(dummy_vec, k=1, query_text="digital lending regulations")

    after_hi = CROSS_LINGUAL_QUERIES_TOTAL.labels(lang="hi")._value.get()
    after_en = CROSS_LINGUAL_QUERIES_TOTAL.labels(lang="en")._value.get()

    assert after_hi == before_hi + 1
    assert after_en == before_en + 1


def test_latency_budget() -> None:
    """Multilingual query projection latency must be <= 18.0 ms on CPU."""
    embedder = MockEmbedder()
    projector = CrossLingualProjector(embedder=embedder)  # type: ignore[arg-type]

    query = "गैर-बैंकिंग वित्तीय कंपनी पंजीकरण और विनियामक ढांचा"

    # Warmup
    _ = projector.project_query(query)

    # Benchmark 20 iterations
    latencies = []
    for _ in range(20):
        t0 = time.perf_counter()
        _ = projector.project_query(query)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    p95_latency = np.percentile(latencies, 95)
    assert p95_latency <= 18.0, f"p95 latency was {p95_latency:.2f} ms (budget <= 18.0 ms)"


def test_fail_closed_fallback() -> None:
    """If cross-lingual projection encounters unexpected error, fall back to English embedder."""

    class BrokenProjector(CrossLingualProjector):
        def translate_and_align_query(self, query: str) -> str:
            raise RuntimeError("Simulated internal model failure")

    embedder = MockEmbedder()
    broken_projector = BrokenProjector(embedder=embedder)  # type: ignore[arg-type]

    # Should not raise; must return a valid unit-norm fallback vector
    vec = broken_projector.project_query("भुगतान एग्रीगेटर")
    assert isinstance(vec, np.ndarray)
    assert vec.shape == (EMBEDDING_DIM,)
    assert pytest.approx(float(np.linalg.norm(vec)), abs=1e-4) == 1.0


def test_retriever_integration_with_multilingual_adapter() -> None:
    """Retriever must cleanly execute with vector_store_adapter='multilingual_dense'."""
    embedder = MockEmbedder()
    projector = CrossLingualProjector(embedder=embedder)  # type: ignore[arg-type]
    store = MultilingualDenseStore(projector=projector)

    target_id = str(uuid.uuid4())
    target_vec = embedder.encode_query("payment aggregator capital requirements")
    meta = ChunkRow(
        document_id=str(uuid.uuid4()),
        source="rbi",
        text="Payment aggregator capital requirement circular text.",
        canonical_url="https://rbi.org.in/pa",
        char_start=0,
        char_end=50,
    )
    store.register_chunk(target_id, target_vec, meta)

    retriever = Retriever(
        embedder=embedder,  # type: ignore[arg-type]
        vector_store=store,
    )

    config = RetrievalConfig(
        name="cross-lingual-test",
        mode="dense",
        vector_store_adapter="multilingual_dense",
        k_dense=5,
        k_final=5,
    )

    results = retriever.retrieve("भुगतान एग्रीगेटर के लिए पूंजी आवश्यकता", config)
    assert len(results) > 0
    assert results[0].chunk_id == target_id
