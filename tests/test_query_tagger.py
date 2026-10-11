"""Unit tests for Query Tagging & Metadata Constrained Retrieval (FEAT-016)."""

from __future__ import annotations

import sys
import time

import pytest

from app.api.models import Confidence, Passage, Provenance, SearchRequest, SearchResponse, Timings
from app.retrieval._tag_data import TAG_KEYWORDS, TAG_TO_LAYERS, VALID_TAXONOMY_TAGS
from app.retrieval.query_tagger import get_default_query_tagger
from app.retrieval.types import MetadataFilter


def test_catalog_45_tags_coverage() -> None:
    """Verifies all 45 canonical taxonomy tags from lexicon.indices.byTag are cataloged."""
    assert len(VALID_TAXONOMY_TAGS) == 45
    assert len(TAG_TO_LAYERS) == 45
    assert len(TAG_KEYWORDS) == 45

    canonical_sample = {
        "accessibility",
        "apis",
        "architecture",
        "compliance",
        "cryptography",
        "databases",
        "distributed-systems",
        "formal-methods",
        "kubernetes",
        "observability",
        "privacy",
        "reliability",
        "security",
        "testing",
    }
    for tag in canonical_sample:
        assert tag in VALID_TAXONOMY_TAGS
        assert len(TAG_KEYWORDS[tag]) > 0


def test_query_tagger_config_and_validation() -> None:
    """Verifies configuration schema, default values, and query length validation."""
    tagger = get_default_query_tagger()
    assert tagger.config.auto_constrain is False
    assert tagger.config.min_tag_confidence == 0.90

    # Query length < 3 chars must raise ValueError
    with pytest.raises(ValueError, match="at least 3 characters"):
        tagger.extract_tags("")

    with pytest.raises(ValueError, match="at least 3 characters"):
        tagger.extract_tags("a")

    with pytest.raises(ValueError, match="at least 3 characters"):
        tagger.extract_tags("  hi ")

    # Valid length >= 3
    valid_res = tagger.extract_tags("api")
    assert isinstance(valid_res, list)


def test_domain_tag_extraction_precision() -> None:
    """Verifies precision of extracted tags across core engineering and regulatory domains."""
    tagger = get_default_query_tagger()

    # Security
    tags = tagger.extract_tags("vulnerability management and zero trust threat modeling")
    assert "security" in tags

    # Compliance / Regulatory
    tags = tagger.extract_tags("statutory circular regulatory compliance mandate")
    assert "compliance" in tags

    # APIs
    tags = tagger.extract_tags("api gateway rest endpoint rate limiting openapi specification")
    assert "apis" in tags

    # Cryptography
    tags = tagger.extract_tags("pki digital certificate rsa aes cipher authority")
    assert "cryptography" in tags

    # Observability
    tags = tagger.extract_tags("distributed tracing opentelemetry prometheus log metrics")
    assert "observability" in tags

    # Privacy
    tags = tagger.extract_tags("dpdp act consent management pii data protection")
    assert "privacy" in tags

    # Databases
    tags = tagger.extract_tags("postgres acid transactions sharding replication indexing")
    assert "databases" in tags


def test_low_confidence_exclusion() -> None:
    """Verifies tags with low confidence (< 0.85) are excluded to prevent false positives."""
    tagger = get_default_query_tagger()

    # General administrative query without domain-specific keywords
    general_query = "the board met in general session on Tuesday afternoon"
    scores = tagger.tag_scores(general_query)
    for _tag, score in scores.items():
        assert score >= 0.85

    extracted = tagger.extract_tags(general_query)
    assert extracted == []


def test_translate_to_filter_and_merge() -> None:
    """Verifies translation of extracted tags to SQL MetadataFilter parameters."""
    tagger = get_default_query_tagger()

    filt = tagger.translate_to_filter(["security", "compliance"])
    assert filt.tags == ["security", "compliance"]
    assert filt.taxonomy_layers is not None
    assert "security-and-trust" in filt.taxonomy_layers
    assert "physical-and-regulated" in filt.taxonomy_layers

    # Merging with existing user-specified MetadataFilter
    manual_filter = MetadataFilter(
        source="RBI",
        taxonomy_layers=["physical-and-regulated"],
    )
    merged = tagger.translate_to_filter(["security"], base_filter=manual_filter)
    assert merged.source == "RBI"
    assert merged.tags == ["security"]
    assert merged.taxonomy_layers is not None
    assert "security-and-trust" in merged.taxonomy_layers
    assert "physical-and-regulated" in merged.taxonomy_layers


def test_evaluation_dataset_100_queries_feat_016() -> None:
    """Evaluates tag extraction on 100 domain-specific queries with >= 95% accuracy."""
    tagger = get_default_query_tagger()

    # 100 queries: 35 cybersecurity, 35 capital adequacy/compliance, 30 payment systems/APIs
    cybersecurity_queries = [
        ("vulnerability disclosure policy guidelines for commercial banks", "security"),
        ("zero trust architecture mandate for financial institutions", "security"),
        ("cybersecurity incident reporting within 6 hours timeline", "security"),
        ("rbac role based access control privileged user management", "security"),
        ("cve exploit threat modeling and mitigation strategy", "security"),
        ("soc2 type ii certification requirements for payment aggregators", "security"),
        ("penetration testing red team assessment schedule", "security"),
        ("firewall intrusion detection system perimeter defense", "security"),
        ("assume breach defensive security posture implementation", "security"),
        ("endpoint detection and response malware containment", "security"),
        ("infosec policy review by board risk committee", "security"),
        ("siem log correlation for suspicious login detection", "security"),
        ("phishing simulation security awareness training for staff", "security"),
        ("ddos mitigation scrub center traffic routing", "security"),
        ("supply chain vulnerability in third party software vendor", "security"),
        ("adversary emulation attack path analysis", "security"),
        ("application security testing sast and dast requirements", "security"),
        ("cloud security posture management misconfiguration scan", "security"),
        ("identity and access management federation saml oauth", "security"),
        ("session timeout and multi-factor authentication enforcement", "security"),
        ("cryptographic key management and hsm storage standard", "security"),
        ("data leak prevention dlp egress monitoring", "security"),
        ("credential stuffing protection on retail banking login", "security"),
        ("bot mitigation captcha threshold on transfer endpoint", "security"),
        ("network segmentation between production and corporate lan", "security"),
        ("ransomware recovery immutable backup verification", "security"),
        ("security operations center tier 1 triage procedure", "security"),
        ("threat intelligence feed integration with firewall rules", "security"),
        ("security information event management event ingestion", "security"),
        ("web application firewall ruleset tuning for owasp top 10", "security"),
        ("container security registry image vulnerability scanning", "security"),
        ("api security tokens and oauth2 scope enforcement", "security"),
        ("hardened operating system baseline for banking servers", "security"),
        ("patch management SLA for critical remote code execution", "security"),
        ("incident response playbook for ransomware containment", "security"),
    ]

    compliance_queries = [
        ("basel iii capital adequacy ratio statutory computation", "compliance"),
        ("regulatory reporting guidelines for scheduled commercial banks", "compliance"),
        ("statutory audit inspection circular by central bank", "compliance"),
        ("sox internal controls financial reporting compliance", "compliance"),
        ("master direction on it governance risk compliance", "compliance"),
        ("supervisory inspection findings remedial action plan", "compliance"),
        ("liquidity coverage ratio mandatory reserve maintenance", "compliance"),
        ("net stable funding ratio compliance timeline and deadlines", "compliance"),
        ("statutory liquidity ratio slr maintenance penalty", "compliance"),
        ("cash reserve ratio crr fortnightly average computation", "compliance"),
        ("prudential norms on income recognition asset classification", "compliance"),
        ("provisioning coverage ratio for non performing assets", "compliance"),
        ("nbfc capital tier 1 and tier 2 compliance criteria", "compliance"),
        ("master circular on customer grievance redressal mechanism", "compliance"),
        ("aml anti money laundering transaction monitoring threshold", "compliance"),
        ("know your customer kyc periodic updating mandate", "compliance"),
        ("suspicious transaction reporting str to financial intelligence", "compliance"),
        ("internal audit charter compliance department oversight", "compliance"),
        ("statutory auditor independence and rotation rules", "compliance"),
        ("board risk management committee regulatory reporting", "compliance"),
        ("capital adequacy disclosure in pillar 3 annual report", "compliance"),
        ("regulatory sandbox participant eligibility and compliance", "compliance"),
        ("outsourcing of financial services vendor compliance audit", "compliance"),
        ("business continuity plan bcp disaster recovery drill compliance", "compliance"),
        ("priority sector lending targets compliance penalty", "compliance"),
        ("foreign exchange management act fema compliance guidelines", "compliance"),
        ("sebi listing obligations and disclosure requirements compliance", "compliance"),
        ("pci dss compliance certification for card data environment", "compliance"),
        ("dpdp digital personal data protection statutory compliance", "compliance"),
        ("governance circular on appointment of chief compliance officer", "compliance"),
        ("whistleblower mechanism regulatory compliance review", "compliance"),
        ("regulatory penalty for non compliance with master direction", "compliance"),
        ("statutory return submission schedule through portal", "compliance"),
        ("compliance risk management framework approval by board", "compliance"),
        ("statutory inspection report compliance tracker table", "compliance"),
    ]

    api_queries = [
        ("api gateway architecture and rate limiting configurations", "apis"),
        ("rest api endpoints design for core banking services", "apis"),
        ("openapi swagger specification for public banking api", "apis"),
        ("graphql schema definition for merchant transaction lookup", "apis"),
        ("grpc service definition and protocol buffers contract", "apis"),
        ("webhook abuse protection and signature verification", "apis"),
        ("api versioning deprecation policy and client migration", "apis"),
        ("api token revocation and oauth2 refresh token rotation", "apis"),
        ("api composition pattern across distributed microservices", "apis"),
        ("api abuse protection against automated scraping bots", "apis"),
        ("api testing automated contract verification suite", "apis"),
        ("payment api idempotency key handling for duplicate requests", "apis"),
        ("fastapi endpoint route registration and query parameters", "apis"),
        ("api gateway mutual tls authentication with partner bank", "apis"),
        ("api documentation interactive developer portal standards", "apis"),
        ("api rate limit quota headers x-ratelimit-remaining", "apis"),
        ("restful resource naming conventions for account entities", "apis"),
        ("api payload schema validation and error responses", "apis"),
        ("webhook retry backoff policy with dead letter queue", "apis"),
        ("api telemetry and latency metrics per endpoint", "apis"),
        ("circuit breaker integration at api gateway reverse proxy", "apis"),
        ("api consumer authentication via api keys and signatures", "apis"),
        ("cross origin resource sharing cors configuration for api", "apis"),
        ("api mocking for integration test environments", "apis"),
        ("api pagination cursors for high volume transaction list", "apis"),
        ("api gateway cache invalidation on resource update", "apis"),
        ("bulk transaction ingestion api streaming endpoints", "apis"),
        ("api gateway response compression gzip brotli tuning", "apis"),
        ("api request signature validation with hmac sha256", "apis"),
        ("api deprecation sunset headers in http response", "apis"),
    ]

    all_queries = cybersecurity_queries + compliance_queries + api_queries
    assert len(all_queries) == 100

    matches = 0
    for q, expected_tag in all_queries:
        extracted = tagger.extract_tags(q)
        if expected_tag in extracted:
            matches += 1

    accuracy = matches / len(all_queries)
    assert accuracy >= 0.95, (
        f"Tag extraction accuracy {accuracy * 100:.1f}% fell below required 95% threshold"
    )


def test_tag_extraction_latency_p95_feat_016() -> None:
    """Verifies that tag extraction latency p95 is <= 0.3 ms."""
    tagger = get_default_query_tagger()
    sample_queries = [
        "what are the cybersecurity vulnerability guidelines for scheduled banks",
        "basel iii capital adequacy ratio statutory compliance norms",
        "api gateway rate limiting and webhook abuse protection",
        "distributed tracing opentelemetry prometheus log retention metrics",
        "pki digital certificate rsa aes cipher authority key management",
        "consent management dpdp act pii data protection circular",
        "postgres acid transactions sharding replication indexing",
        "chaos engineering blast radius fault injection mesh",
        "microservices event driven domain driven design architecture",
        "byzantine fault tolerance consensus protocol ledger",
    ]

    latencies_ms: list[float] = []
    # 1,000 iterations
    for _ in range(100):
        for q in sample_queries:
            t0 = time.perf_counter()
            _ = tagger.extract_tags(q)
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)

    latencies_ms.sort()
    p95_index = int(len(latencies_ms) * 0.95)
    p95_latency = latencies_ms[p95_index]

    # Budget limit is 0.3 ms
    assert p95_latency < 0.3, (
        f"Tag extraction p95 latency {p95_latency:.4f} ms exceeded 0.3 ms budget"
    )


def test_memory_footprint_under_2mb() -> None:
    """Verifies that the tag vocabulary index memory footprint is <= 2 MB."""
    tagger = get_default_query_tagger()

    single_size = sys.getsizeof(tagger._single_map)
    multi_size = sys.getsizeof(tagger._multi_map)
    keywords_size = sys.getsizeof(TAG_KEYWORDS)
    layers_size = sys.getsizeof(TAG_TO_LAYERS)

    total_bytes = single_size + multi_size + keywords_size + layers_size
    total_mb = total_bytes / (1024 * 1024)

    assert total_mb < 2.0, f"Memory footprint {total_mb:.3f} MB exceeded 2 MB limit"


def test_metrics_and_search_response_roundtrip() -> None:
    """Verifies Prometheus metric instrumentation and SearchResponse serialization."""
    tagger = get_default_query_tagger()

    # Record metrics
    sample_tags = ["security", "apis"]
    tagger.record_metrics(sample_tags)

    req = SearchRequest(
        query="what are the api gateway security guidelines",
        auto_constrain_tags=True,
    )
    assert req.auto_constrain_tags is True

    resp = SearchResponse(
        query=req.query,
        mode="hybrid",
        k=1,
        passages=[
            Passage(
                rank=1,
                chunk_id="chk-tag-001",
                document_id="doc-api-01",
                source="RBI",
                canonical_url="https://rbi.org.in/api",
                score=0.94,
                arm_ranks={"dense": 1},
                char_start=0,
                char_end=200,
                text="API security mandates mutual TLS and token revocation.",
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
            corpus_manifest_digest="sha256:tags",
            corpus_chunks=150,
            retrieval={"auto_constrain_tags": True},
        ),
        timings=Timings(total_ms=4.0, retrieval_ms=4.0, cache_hit=False),
        extracted_tags=["apis", "security"],
    )

    data = resp.model_dump()
    assert data["extracted_tags"] == ["apis", "security"]
