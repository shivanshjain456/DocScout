"""Unit and integration tests for Multi-Turn Conversational Coreference Resolver (FEAT-017)."""

from __future__ import annotations

import os
import time
from typing import cast

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.chat import SessionStore
from app.api.security import load_keys
from app.retrieval.coreference import (
    CIRCULAR_ID_REGEX,
    REGULATORY_CONCEPTS,
    ChatConfig,
    ChatMessage,
    CoreferenceResolver,
    get_default_coreference_resolver,
)
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth


@pytest.fixture
def test_client() -> TestClient:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY},{ROTATION_KEY}"
    app.state.api_keys = load_keys()
    return TestClient(app)


def test_circular_id_regex_and_concepts() -> None:
    """Verifies regex matching for RBI/SEBI publications and concept catalog size."""
    assert len(REGULATORY_CONCEPTS) >= 40

    # Matching RBI circular IDs
    sample_rbi = [
        "RBI/2022-23/111",
        "RBI/2023-24/54",
        "DOR.STR.REC.55/21.04.048/2021-22",
        "DPSS.CO.PD.No.1810/02.14.008/2019-20",
    ]
    for cid in sample_rbi:
        assert CIRCULAR_ID_REGEX.search(cid) is not None, f"Failed to match {cid}"

    # Matching SEBI circular IDs
    sample_sebi = [
        "SEBI/HO/CFD/CMD1/P/CIR/2022/01",
        "SEBI/HO/MIRSD/CRADT/CIR/P/2020/218",
    ]
    for cid in sample_sebi:
        assert CIRCULAR_ID_REGEX.search(cid) is not None, f"Failed to match {cid}"


def test_coreference_resolver_config() -> None:
    """Verifies default ChatConfig parameters and custom overrides."""
    resolver = get_default_coreference_resolver()
    assert resolver.config.max_history_turns == 5
    assert resolver.config.coreference_model == "fast-rule"
    assert resolver.config.max_query_chars == 512

    custom = CoreferenceResolver(ChatConfig(max_history_turns=3, max_query_chars=256))
    assert custom.config.max_history_turns == 3
    assert custom.config.max_query_chars == 256


def test_standalone_query_preservation() -> None:
    """Regression test: Standalone queries must NOT be modified (regression limit)."""
    resolver = get_default_coreference_resolver()
    history = [
        ChatMessage(
            role="user",
            content="Tell me about Digital Lending guidelines RBI/2022-23/111.",
        ),
        ChatMessage(
            role="assistant",
            content="Digital lending guidelines were issued by RBI.",
            circular_ids=["RBI/2022-23/111"],
        ),
    ]

    standalone_queries = [
        "What are the capital adequacy requirements for commercial banks?",
        "Explain the Cash Reserve Ratio mandate.",
        "What is the statutory liquidity ratio requirement?",
        "Define Priority Sector Lending targets for small finance banks.",
        "How do Credit Information Companies handle consumer disputes?",
    ]

    for q in standalone_queries:
        res = resolver.resolve(q, history)
        assert res.was_rewritten is False, f"Standalone query was unexpectedly rewritten: {q}"
        assert res.rewritten_query == q


# 25 multi-turn regulatory dialogues with 3 follow-up turns each (n=75 follow-up turns)
MULTI_TURN_DIALOGUES: list[dict[str, object]] = [
    {
        "initial": "What are the rules in Digital Lending guidelines RBI/2022-23/111?",
        "entity": "Digital Lending",
        "cid": "RBI/2022-23/111",
        "turns": [
            ("What about NBFCs?", "NBFCs"),
            ("What are its exceptions?", "exceptions"),
            ("When does it come into effect?", "come into effect"),
        ],
    },
    {
        "initial": "Details on Default Loss Guarantee arrangements under RBI/2023-24/41.",
        "entity": "Default Loss Guarantee",
        "cid": "RBI/2023-24/41",
        "turns": [
            ("Does that apply to fintech partners?", "fintech partners"),
            ("And penal interest?", "penal interest"),
            ("Who is exempt?", "exempt"),
        ],
    },
    {
        "initial": "Explain the Payment Aggregator framework under DPSS.CO.PD.No.1810/02.14.008/2019-20.",
        "entity": "Payment Aggregator",
        "cid": "DPSS.CO.PD.No.1810/02.14.008/2019-20",
        "turns": [
            ("How about delivery-versus-payment models?", "delivery-versus-payment"),
            ("What are its net worth requirements?", "net worth requirements"),
            ("When does this circular take effect?", "take effect"),
        ],
    },
    {
        "initial": "What does RBI say about First Loss Default Guarantee (FLDG)?",
        "entity": "FLDG",
        "cid": "RBI/2023-24/41",
        "turns": [
            ("What about cooperative banks?", "cooperative banks"),
            ("Any exceptions?", "exceptions"),
            ("Does it apply to unregulated entities?", "unregulated entities"),
        ],
    },
    {
        "initial": "Prudential Norms on Income Recognition and Asset Classification under DOR.STR.REC.55/21.04.048/2021-22.",
        "entity": "Prudential Norms",
        "cid": "DOR.STR.REC.55/21.04.048/2021-22",
        "turns": [
            ("And SMA categorization?", "SMA categorization"),
            ("Does that apply to housing finance companies?", "housing finance companies"),
            ("What are its provisioning percentages?", "provisioning percentages"),
        ],
    },
    {
        "initial": "Cyber Security Framework for Urban Co-operative Banks under RBI/2020-21/11.",
        "entity": "Cyber Security Framework",
        "cid": "RBI/2020-21/11",
        "turns": [
            ("What about tier 1 banks?", "tier 1 banks"),
            ("Who is exempt?", "exempt"),
            ("When does it apply?", "come into effect"),
        ],
    },
    {
        "initial": "Master Direction on Know Your Customer (KYC) norms under RBI/DBR/2015-16/18.",
        "entity": "Know Your Customer",
        "cid": "RBI/DBR/2015-16/18",
        "turns": [
            ("How about video KYC?", "video KYC"),
            ("What are its periodic updation rules?", "periodic updation rules"),
            ("Are there exceptions?", "exceptions"),
        ],
    },
    {
        "initial": "Outsourcing of Financial Services rules under RBI/2023-24/102.",
        "entity": "Outsourcing of Financial Services",
        "cid": "RBI/2023-24/102",
        "turns": [
            ("What about cloud service providers?", "cloud service providers"),
            ("And sub-contracting?", "sub-contracting"),
            ("Does it apply to foreign branches?", "foreign branches"),
        ],
    },
    {
        "initial": "Scale Based Regulation for NBFCs under DOR.CRE.REC.No.60/03.10.001/2021-22.",
        "entity": "Scale Based Regulation",
        "cid": "DOR.CRE.REC.No.60/03.10.001/2021-22",
        "turns": [
            ("What about middle layer NBFCs?", "middle layer NBFCs"),
            ("What are its capital adequacy requirements?", "capital adequacy requirements"),
            ("When does this take effect?", "take effect"),
        ],
    },
    {
        "initial": "Large Exposures Framework limits under RBI/2018-19/83.",
        "entity": "Large Exposures Framework",
        "cid": "RBI/2018-19/83",
        "turns": [
            ("What about connected counterparties?", "connected counterparties"),
            ("Any exceptions?", "exceptions"),
            ("Does it apply to non-banking entities?", "non-banking entities"),
        ],
    },
    {
        "initial": "Central KYC Records Registry (CKYCR) operating procedures under RBI/2016-17/12.",
        "entity": "CKYCR",
        "cid": "RBI/2016-17/12",
        "turns": [
            ("How about legal entities?", "legal entities"),
            ("When does it come into effect?", "come into effect"),
            ("Who is exempt?", "exempt"),
        ],
    },
    {
        "initial": "Self-Regulatory Organisation omnibus framework under RBI/2023-24/133.",
        "entity": "Self-Regulatory Organisation",
        "cid": "RBI/2023-24/133",
        "turns": [
            ("What about fintech associations?", "fintech associations"),
            ("What are its governance criteria?", "governance criteria"),
            ("And dispute resolution?", "dispute resolution"),
        ],
    },
    {
        "initial": "Legal Entity Identifier guidelines under RBI/2020-21/82.",
        "entity": "Legal Entity Identifier",
        "cid": "RBI/2020-21/82",
        "turns": [
            ("What about non-individual borrowers?", "non-individual borrowers"),
            ("What are its thresholds?", "thresholds"),
            ("When does it take effect?", "take effect"),
        ],
    },
    {
        "initial": "SEBI BRSR Core sustainability framework SEBI/HO/CFD/CMD-1/P/CIR/2023/122.",
        "entity": "BRSR",
        "cid": "SEBI/HO/CFD/CMD-1/P/CIR/2023/122",
        "turns": [
            ("What about the top 1000 listed entities?", "top 1000 listed entities"),
            ("And assurance requirements?", "assurance requirements"),
            ("Who is exempt?", "exempt"),
        ],
    },
    {
        "initial": "Account Aggregator framework specifications under RBI/2016-17/70.",
        "entity": "Account Aggregator",
        "cid": "RBI/2016-17/70",
        "turns": [
            ("What about Financial Information Providers?", "Financial Information Providers"),
            ("What are its consent architecture rules?", "consent architecture rules"),
            ("Any exceptions?", "exceptions"),
        ],
    },
    {
        "initial": "Microfinance Loans regulatory directions under DOR.CRE.REC.27/03.10.001/2022-23.",
        "entity": "Microfinance Loans",
        "cid": "DOR.CRE.REC.27/03.10.001/2022-23",
        "turns": [
            ("How about household income caps?", "household income caps"),
            ("What are its prepayment penalty rules?", "prepayment penalty rules"),
            ("Does it apply to commercial banks?", "commercial banks"),
        ],
    },
    {
        "initial": "Internal Ombudsman mechanism under RBI/2021-22/126.",
        "entity": "Internal Ombudsman",
        "cid": "RBI/2021-22/126",
        "turns": [
            ("What about deposit-taking NBFCs?", "deposit-taking NBFCs"),
            ("And tenure of appointment?", "tenure of appointment"),
            ("Who is exempt?", "exempt"),
        ],
    },
    {
        "initial": "Wilful Defaulters master circular under RBI/2015-16/100.",
        "entity": "Wilful Defaulters",
        "cid": "RBI/2015-16/100",
        "turns": [
            ("What about guarantor liabilities?", "guarantor liabilities"),
            ("What are its reporting deadlines?", "reporting deadlines"),
            ("Does that apply to directors?", "directors"),
        ],
    },
    {
        "initial": "Co-Lending Model guidelines under FIDD.CO.Plan.BC.No.8/04.09.01/2020-21.",
        "entity": "Co-Lending Model",
        "cid": "FIDD.CO.Plan.BC.No.8/04.09.01/2020-21",
        "turns": [
            ("How about priority sector classification?", "priority sector classification"),
            ("What are its minimum retention rules?", "minimum retention rules"),
            ("Any exceptions?", "exceptions"),
        ],
    },
    {
        "initial": "Card-on-File Tokenisation mandates under DPSS.CO.PD.No.1021/02.14.003/2021-22.",
        "entity": "Tokenisation",
        "cid": "DPSS.CO.PD.No.1021/02.14.003/2021-22",
        "turns": [
            ("What about guest checkout?", "guest checkout"),
            ("When does it come into effect?", "come into effect"),
            ("Does it apply to international cards?", "international cards"),
        ],
    },
    {
        "initial": "Prepaid Payment Instruments (PPI) master directions under DPSS.CO.PD.No.753/02.14.008/2021-22.",
        "entity": "PPI",
        "cid": "DPSS.CO.PD.No.753/02.14.008/2021-22",
        "turns": [
            ("What about small PPIs?", "small PPIs"),
            ("And interoperability requirements?", "interoperability requirements"),
            ("Who is exempt?", "exempt"),
        ],
    },
    {
        "initial": "Trade Receivables Discounting System (TReDS) guidelines under RBI/2014-15/330.",
        "entity": "TReDS",
        "cid": "RBI/2014-15/330",
        "turns": [
            ("What about buyer onboarding?", "buyer onboarding"),
            ("What are its capital criteria?", "capital criteria"),
            ("Does that apply to PSUs?", "PSUs"),
        ],
    },
    {
        "initial": "Credit Card and Debit Card issuance directions under DOR.AUT.REC.No.27/24.01.041/2022-23.",
        "entity": "Credit Card",
        "cid": "DOR.AUT.REC.No.27/24.01.041/2022-23",
        "turns": [
            ("What about billing cycle options?", "billing cycle options"),
            ("And unsolicited card issuance?", "unsolicited card issuance"),
            ("When does it take effect?", "take effect"),
        ],
    },
    {
        "initial": "Liquidity Coverage Ratio framework under RBI/2013-14/629.",
        "entity": "Liquidity Coverage Ratio",
        "cid": "RBI/2013-14/629",
        "turns": [
            ("What about run-off rates?", "run-off rates"),
            ("What are its high quality liquid asset requirements?", "liquid asset requirements"),
            ("Any exceptions?", "exceptions"),
        ],
    },
    {
        "initial": "Asset Reconstruction Company regulatory framework under DOR.SIG.FIN.REC.75/26.03.001/2022-23.",
        "entity": "Asset Reconstruction Company",
        "cid": "DOR.SIG.FIN.REC.75/26.03.001/2022-23",
        "turns": [
            ("What about minimum net owned funds?", "net owned funds"),
            ("Does it apply to existing ARCs?", "existing ARCs"),
            ("Who is exempt?", "exempt"),
        ],
    },
]


def test_25_multi_turn_dialogues_75_followups() -> None:
    """Verifies coreference resolution across 25 multi-turn dialogues (n=75 follow-ups).

    Acceptance criteria: Successfully resolves >= 90% of coreference ambiguity.
    """
    resolver = get_default_coreference_resolver()
    assert len(MULTI_TURN_DIALOGUES) == 25

    total_followups = 0
    resolved_count = 0

    for dlg in MULTI_TURN_DIALOGUES:
        initial_msg = str(dlg["initial"])
        entity = str(dlg["entity"])
        cid = str(dlg["cid"])
        turns = cast(list[tuple[str, str]], dlg["turns"])

        history: list[ChatMessage] = [
            ChatMessage(role="user", content=initial_msg),
            ChatMessage(
                role="assistant",
                content=f"Directions regarding {entity} in {cid}.",
                circular_ids=[cid],
                entities=[entity],
            ),
        ]

        for follow_up_text, expected_concept in turns:
            total_followups += 1
            res = resolver.resolve(follow_up_text, history)

            assert res.was_rewritten is True, f"Failed to rewrite: '{follow_up_text}'"
            assert (
                entity.lower() in res.rewritten_query.lower()
                or cid.lower() in res.rewritten_query.lower()
            ), f"Rewritten query missing context: {res.rewritten_query}"

            resolved_count += 1

            # Append to history for continuous conversation
            history.append(ChatMessage(role="user", content=follow_up_text))
            history.append(
                ChatMessage(
                    role="assistant",
                    content=f"Explaining {expected_concept} under {entity}.",
                )
            )

    assert total_followups == 75
    resolution_rate = resolved_count / total_followups
    assert resolution_rate >= 0.90, f"Resolution rate {resolution_rate:.2%} < 90%"


def test_coreference_latency_benchmark() -> None:
    """Verifies rule engine coreference rewriting latency <= 2.0 ms (p95)."""
    resolver = get_default_coreference_resolver()
    history = [
        ChatMessage(
            role="user",
            content="Digital Lending guidelines RBI/2022-23/111 details.",
        ),
        ChatMessage(
            role="assistant",
            content="Digital Lending guidelines issued.",
            circular_ids=["RBI/2022-23/111"],
            entities=["Digital Lending"],
        ),
    ]

    durations_ms: list[float] = []
    # Warmup
    for _ in range(50):
        resolver.resolve("What about NBFCs?", history)

    # Timed runs
    for _ in range(200):
        t0 = time.perf_counter()
        resolver.resolve("What about NBFCs?", history)
        durations_ms.append((time.perf_counter() - t0) * 1000.0)

    durations_ms.sort()
    p95_ms = durations_ms[int(len(durations_ms) * 0.95)]
    assert p95_ms <= 2.0, f"p95 latency {p95_ms:.3f} ms exceeds 2.0 ms limit"


def test_session_store_lru_and_memory_limit() -> None:
    """Verifies thread-safe session store LRU eviction and memory bounds <= 10 KB."""
    store = SessionStore(max_sessions=10, max_turns=5)

    # Test LRU eviction
    for i in range(15):
        sid = f"session_{i}"
        store.add_turn(
            sid,
            ChatMessage(
                role="user",
                content=f"Message {i} for Digital Lending RBI/2022-23/111",
            ),
        )

    # Only 10 sessions retained
    assert store.session_count() == 10
    # Sessions 0-4 must have been evicted
    assert len(store.get_history("session_0")) == 0
    assert len(store.get_history("session_14")) == 1

    # Test max turns bounding (max 5 turns)
    active_sid = "bounded_session"
    for turn_idx in range(12):
        store.add_turn(
            active_sid,
            ChatMessage(role="user", content=f"Turn {turn_idx} content"),
        )
    history = store.get_history(active_sid)
    assert len(history) == 5
    assert history[-1].content == "Turn 11 content"

    # Memory limit verification: <= 10 KB (10240 bytes) per session
    mem_bytes = store.estimate_session_bytes(active_sid)
    assert mem_bytes <= 10 * 1024, f"Session bytes {mem_bytes} exceeds 10 KB limit"

    # Test clear_session
    assert store.clear_session(active_sid) is True
    assert len(store.get_history(active_sid)) == 0


def test_chat_api_endpoint(test_client: TestClient) -> None:
    """Verifies /v1/chat endpoint with authentication, input validation, and multi-turn session."""
    # 1. Unauthenticated request rejected
    resp = test_client.post("/v1/chat", json={"message": "What about NBFCs?"})
    assert resp.status_code == 401

    # 2. Input validation: empty message (422)
    resp = test_client.post("/v1/chat", json={"message": ""}, headers=auth())
    assert resp.status_code == 422

    # 3. Message > 512 chars (422)
    long_msg = "x" * 513
    resp = test_client.post("/v1/chat", json={"message": long_msg}, headers=auth())
    assert resp.status_code == 422

    # 4. Multi-turn session roundtrip
    sid = "test_user_session_101"
    # Turn 1: Initial query
    resp1 = test_client.post(
        "/v1/chat",
        json={
            "message": "Explain Digital Lending guidelines RBI/2022-23/111.",
            "session_id": sid,
        },
        headers=auth(),
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["session_id"] == sid
    assert data1["rewritten_query"] == "Explain Digital Lending guidelines RBI/2022-23/111."

    # Turn 2: Follow-up query with coreference
    resp2 = test_client.post(
        "/v1/chat",
        json={
            "message": "What about NBFCs?",
            "session_id": sid,
        },
        headers=auth(),
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["resolution"]["was_rewritten"] is True
    assert "Digital Lending" in data2["rewritten_query"]
    assert "NBFCs" in data2["rewritten_query"]

    # 5. Session termination / clear endpoint
    del_resp = test_client.delete(f"/v1/chat/{sid}", headers=auth())
    assert del_resp.status_code == 200
    assert del_resp.json()["cleared"] is True

    # After clearing, follow-up has no prior session context
    resp3 = test_client.post(
        "/v1/chat",
        json={
            "message": "What about NBFCs?",
            "session_id": sid,
        },
        headers=auth(),
    )
    assert resp3.status_code == 200
    data3 = resp3.json()
    # No prior history in session -> cannot rewrite
    assert data3["resolution"]["was_rewritten"] is False
