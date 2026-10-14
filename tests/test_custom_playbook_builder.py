"""Unit, integration, and performance test suite for Custom Enterprise Compliance Playbook Builder (FEAT-060).

Validates:
1. 10 custom enterprise playbook template definitions:
   - Third-Party Vendor Risk Auditing Playbook (3 stages)
   - Post-Quantum Cryptographic Migration Playbook (4 stages)
   - Generative AI & Model Risk Governance Playbook (4 stages)
   - DORA Digital Operational Resilience Playbook (5 stages)
   - Cross-Border Data Privacy & Sovereignty Playbook (3 stages)
   - Critical Cyber Incident Recovery Playbook (4 stages)
   - Corporate ESG Sustainability Governance Playbook (2 stages, minimum valid)
   - AML / Financial Crimes Risk Monitoring Playbook (3 stages)
   - Multi-Region Cloud Resilience & Chaos Playbook (6 stages, maximum valid)
   - Regulated Open Banking API Security Playbook (3 stages)
2. Schema & structural validation rules:
   - Minimum 2 stages and maximum 6 stages
   - Strictly sequential stage numbering
   - Milestone ID uniqueness across stages
   - Non-empty stage names and exit criteria
   - Payload size ceiling (<= 256 KB)
3. Tenant quota enforcement (max 25 custom playbooks per tenant).
4. Runtime execution: custom playbooks execute seamlessly in standard PlaybookEngine.
5. Performance SLA: validation and save latency <= 12.0 ms.
6. REST API endpoints:
   - POST /v1/playbooks/custom
   - GET /v1/playbooks/custom
   - GET /v1/playbooks/custom/{playbook_id}
"""

from __future__ import annotations

import os
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.models import (
    CustomMilestoneDefinition,
    CustomPlaybookDefinition,
    CustomStageDefinition,
)
from app.api.security import load_keys
from app.workflows.custom_builder import (
    CustomBuilderConfig,
    CustomPlaybookBuilder,
    CustomPlaybookQuotaExceededError,
    CustomPlaybookValidationError,
    convert_custom_to_runtime_template,
    validate_custom_playbook_schema,
)
from app.workflows.engine import PlaybookEngine
from tests.conftest import PRIMARY_KEY, auth


@pytest.fixture
def client() -> TestClient:
    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY}"
    app.state.api_keys = load_keys()
    return TestClient(app)


@pytest.fixture
def api_headers() -> dict[str, str]:
    return auth(PRIMARY_KEY)


def build_10_custom_enterprise_playbooks() -> list[CustomPlaybookDefinition]:
    """Generate evaluation dataset of 10 distinct enterprise compliance playbooks."""
    return [
        # 1. Third-Party Vendor Risk
        CustomPlaybookDefinition(
            id="playbook.custom-vendor-risk",
            name="Tier-1 Vendor Criticality & SLA Resilience Playbook",
            goal="Establish operational resilience audits and exit strategies for external ICT suppliers.",
            domain="vendor-risk",
            stages=[
                CustomStageDefinition(
                    stage_number=1,
                    stage_name="Vendor Classification & Inventory",
                    description="Inventory all tier-1 ICT providers and assign criticality ratings.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.vr.inv_01",
                            title="Register third-party suppliers in asset inventory",
                            role="compliance-officer",
                            mandatory=True,
                            estimated_hours=16,
                        ),
                        CustomMilestoneDefinition(
                            id="ms.vr.inv_02",
                            title="Conduct contractual SLA and exit strategy review",
                            role="legal",
                            mandatory=True,
                            estimated_hours=24,
                        ),
                    ],
                    exit_criteria=["100% critical suppliers cataloged with assigned risk tiers"],
                ),
                CustomStageDefinition(
                    stage_number=2,
                    stage_name="Operational Stress & Concentration Auditing",
                    description="Audit multi-tenant concentration risk and subcontracting chains.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.vr.audit_01",
                            title="Perform concentration risk assessment across cloud regions",
                            role="risk-lead",
                            mandatory=True,
                            estimated_hours=20,
                        ),
                    ],
                    exit_criteria=["Concentration risk assessment formally reviewed by CRO"],
                ),
                CustomStageDefinition(
                    stage_number=3,
                    stage_name="Contingency & Exit Strategy Rehearsal",
                    description="Rehearse supplier switchover or rapid repatriation.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.vr.rehearsal_01",
                            title="Simulate primary database failover to secondary provider",
                            role="sre",
                            mandatory=True,
                            estimated_hours=40,
                        ),
                    ],
                    exit_criteria=["Target RTO <= 4h demonstrated during failover drill"],
                ),
            ],
            metadata={"version": "1.0", "author": "Vendor Governance Office"},
        ),
        # 2. Post-Quantum Cryptographic Migration
        CustomPlaybookDefinition(
            id="playbook.custom-pqc-migration",
            name="Post-Quantum Cryptographic Migration Roadmap",
            goal="Transition enterprise cryptographic assets to NIST FIPS-203/204 compliant algorithms.",
            domain="cryptography",
            stages=[
                CustomStageDefinition(
                    stage_number=1,
                    stage_name="Cryptographic Discovery & Inventory",
                    description="Scan public-key infrastructure for quantum-vulnerable algorithms.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.pqc.scan_01",
                            title="Run CBOM automated scanner across all production microservices",
                            role="security",
                            mandatory=True,
                            estimated_hours=20,
                        ),
                    ],
                    exit_criteria=[
                        "Complete CBOM registry generated with zero unknown cipher suites"
                    ],
                ),
                CustomStageDefinition(
                    stage_number=2,
                    stage_name="Hybrid Classical-PQC Tunneling",
                    description="Deploy dual-mode key exchange in non-critical inter-service APIs.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.pqc.hybrid_01",
                            title="Configure ML-KEM hybrid TLS 1.3 endpoints",
                            role="developer",
                            mandatory=True,
                            estimated_hours=32,
                        ),
                    ],
                    exit_criteria=[
                        "All inter-cluster TLS connections negotiate hybrid key exchange"
                    ],
                ),
                CustomStageDefinition(
                    stage_number=3,
                    stage_name="Algorithmic Hardening & HSM Upgrades",
                    description="Upgrade enterprise hardware security modules with PQC firmware.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.pqc.hsm_01",
                            title="Flash production HSM clusters with certified firmware",
                            role="sre",
                            mandatory=True,
                            estimated_hours=48,
                        ),
                    ],
                    exit_criteria=["HSM firmware verified against NIST CAVP test suites"],
                ),
                CustomStageDefinition(
                    stage_number=4,
                    stage_name="Pure PQC Certification & Sunset",
                    description="Deprecate classical RSA/ECC cipher suites completely.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.pqc.sunset_01",
                            title="Revoke and replace classical root certificates",
                            role="security",
                            mandatory=True,
                            estimated_hours=16,
                        ),
                    ],
                    exit_criteria=["Zero active RSA/ECC certificates in production trust stores"],
                ),
            ],
        ),
        # 3. AI Risk Governance Playbook
        CustomPlaybookDefinition(
            id="playbook.custom-ai-governance",
            name="EU AI Act & Algorithmic Risk Governance Playbook",
            goal="Ensure foundation models and predictive scoring systems meet statutory conformity.",
            domain="ai-governance",
            stages=[
                CustomStageDefinition(
                    stage_number=1,
                    stage_name="Risk Tier Classification & Model Inventory",
                    description="Catalog all ML models and determine EU AI Act risk classification.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.ai.inv_01",
                            title="Classify algorithms into Unacceptable, High, or Minimal Risk",
                            role="compliance-officer",
                            mandatory=True,
                            estimated_hours=12,
                        ),
                    ],
                    exit_criteria=["All models classified and documented in registry"],
                ),
                CustomStageDefinition(
                    stage_number=2,
                    stage_name="Data Quality & Bias Auditing",
                    description="Audit training corpora for representation, demographic parity, and copyright.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.ai.bias_01",
                            title="Run automated disparity impact and equality-of-odds benchmarks",
                            role="developer",
                            mandatory=True,
                            estimated_hours=28,
                        ),
                    ],
                    exit_criteria=[
                        "Disparate impact ratio within 0.80 - 1.25 across all protected classes"
                    ],
                ),
                CustomStageDefinition(
                    stage_number=3,
                    stage_name="Explainability & Human-in-the-Loop Safeguards",
                    description="Deploy SHAP/LIME explainability tools and manual oversight protocols.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.ai.explain_01",
                            title="Implement per-decision counterfactual explanation generation",
                            role="developer",
                            mandatory=True,
                            estimated_hours=24,
                        ),
                    ],
                    exit_criteria=["Feature attribution latency <= 100ms on adverse decisions"],
                ),
                CustomStageDefinition(
                    stage_number=4,
                    stage_name="Post-Market Surveillance & Audit Sign-Off",
                    description="Establish continuous drift monitoring and notify supervisory authorities.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.ai.surveillance_01",
                            title="Configure Kolmogorov-Smirnov drift alerts on scoring outputs",
                            role="risk-lead",
                            mandatory=True,
                            estimated_hours=16,
                        ),
                    ],
                    exit_criteria=[
                        "Continuous monitoring verified with automated alert thresholds"
                    ],
                ),
            ],
        ),
        # 4. DORA Digital Operational Resilience
        CustomPlaybookDefinition(
            id="playbook.custom-dora-resilience",
            name="DORA Multi-Pillar Enterprise Resilience Program",
            goal="Implement comprehensive operational resilience across EU DORA pillars 1 to 5.",
            domain="dora",
            stages=[
                CustomStageDefinition(
                    stage_number=1,
                    stage_name="ICT Risk Management Framework",
                    description="Formalize enterprise risk tolerance and ICT system classification.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.dora.p1_01",
                            title="Document ICT risk policies and board risk appetite statement",
                            role="risk-lead",
                            mandatory=True,
                            estimated_hours=20,
                        ),
                    ],
                    exit_criteria=["Board approved ICT risk governance policies"],
                ),
                CustomStageDefinition(
                    stage_number=2,
                    stage_name="Incident Classification & Statutory Reporting",
                    description="Establish major incident thresholds and reporting channels to competent authorities.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.dora.p2_01",
                            title="Implement 4-hour initial incident notification workflow",
                            role="compliance-officer",
                            mandatory=True,
                            estimated_hours=18,
                        ),
                    ],
                    exit_criteria=["Dry-run incident notification dispatched in <= 2 hours"],
                ),
                CustomStageDefinition(
                    stage_number=3,
                    stage_name="Digital Operational Testing & TLPT",
                    description="Execute Threat-Led Penetration Testing on live production systems.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.dora.p3_01",
                            title="Commission external accredited red team for TLPT execution",
                            role="security",
                            mandatory=True,
                            estimated_hours=80,
                        ),
                    ],
                    exit_criteria=["TLPT test summary report signed by external test director"],
                ),
                CustomStageDefinition(
                    stage_number=4,
                    stage_name="Third-Party ICT Risk Management",
                    description="Audit critical third-party service providers and establish exit plans.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.dora.p4_01",
                            title="Review contractual terms against DORA Article 30 standards",
                            role="legal",
                            mandatory=True,
                            estimated_hours=24,
                        ),
                    ],
                    exit_criteria=["100% compliant contract amendments negotiated"],
                ),
                CustomStageDefinition(
                    stage_number=5,
                    stage_name="Information & Intelligence Sharing",
                    description="Participate in trusted financial threat intelligence sharing community.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.dora.p5_01",
                            title="Integrate STIX/TAXII automated threat feed ingester",
                            role="sre",
                            mandatory=True,
                            estimated_hours=16,
                        ),
                    ],
                    exit_criteria=["Active automated feed ingesting cyber alerts daily"],
                ),
            ],
        ),
        # 5. Cross-Border Data Privacy
        CustomPlaybookDefinition(
            id="playbook.custom-cross-border-privacy",
            name="Cross-Border Data Sovereignty & Transfer Playbook",
            goal="Enforce regulatory compliance for cross-border personal data transfers under GDPR and DPDP.",
            domain="privacy",
            stages=[
                CustomStageDefinition(
                    stage_number=1,
                    stage_name="Data Flow Mapping & Transfer Impact Assessment",
                    description="Map all international data flows and evaluate destination legal regimes.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.cb.flow_01",
                            title="Conduct Transfer Impact Assessment (TIA) for US-bound data",
                            role="legal",
                            mandatory=True,
                            estimated_hours=24,
                        ),
                    ],
                    exit_criteria=["Signed TIA document for every international data pipeline"],
                ),
                CustomStageDefinition(
                    stage_number=2,
                    stage_name="Technical Safeguards & Field-Level Tokenization",
                    description="Deploy cryptographic pseudonymization before egress.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.cb.token_01",
                            title="Implement zero-knowledge tokenization gateway for PII",
                            role="developer",
                            mandatory=True,
                            estimated_hours=36,
                        ),
                    ],
                    exit_criteria=["Egress traffic validated to contain zero unmasked PII"],
                ),
                CustomStageDefinition(
                    stage_number=3,
                    stage_name="Regulatory Registration & Data Principal Auditing",
                    description="Register international data transfer agreements with data protection boards.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.cb.reg_01",
                            title="File statutory transfer notifications with DPBI / EDPB",
                            role="compliance-officer",
                            mandatory=True,
                            estimated_hours=14,
                        ),
                    ],
                    exit_criteria=[
                        "Official acknowledgment receipt from Data Protection Authority"
                    ],
                ),
            ],
        ),
        # 6. Cyber Incident Response
        CustomPlaybookDefinition(
            id="playbook.custom-cyber-incident",
            name="Critical Cyber Incident Crisis & Recovery Playbook",
            goal="Rapid containment, forensic imaging, regulatory disclosure, and clean-state restoration.",
            domain="incident-response",
            stages=[
                CustomStageDefinition(
                    stage_number=1,
                    stage_name="Triage & Forensic Isolation",
                    description="Identify breach blast radius, isolate infected hosts, and acquire memory dumps.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.ir.triage_01",
                            title="Quarantine impacted subnets and revoke active session tokens",
                            role="security",
                            mandatory=True,
                            estimated_hours=4,
                        ),
                    ],
                    exit_criteria=["Network perimeter isolated with zero active C2 connections"],
                ),
                CustomStageDefinition(
                    stage_number=2,
                    stage_name="Regulatory Disclosure & Stakeholder Notification",
                    description="Draft and dispatch disclosures within statutory 6-hour windows.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.ir.notify_01",
                            title="Generate CERT-In and RBI incident disclosure dossier",
                            role="compliance-officer",
                            mandatory=True,
                            estimated_hours=6,
                        ),
                    ],
                    exit_criteria=["Disclosures transmitted within statutory deadlines"],
                ),
                CustomStageDefinition(
                    stage_number=3,
                    stage_name="Root-Cause Remediation & Image Rebuild",
                    description="Patch zero-day vulnerabilities and rebuild images from verified golden baselines.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.ir.rebuild_01",
                            title="Re-deploy immutable clusters with verified container digests",
                            role="sre",
                            mandatory=True,
                            estimated_hours=16,
                        ),
                    ],
                    exit_criteria=["100% services running verified golden images"],
                ),
                CustomStageDefinition(
                    stage_number=4,
                    stage_name="Post-Incident Review & Evidence Sealing",
                    description="Compile immutable forensic timeline and update risk registers.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.ir.post_01",
                            title="Anchor forensic chain-of-custody digest into immutable log",
                            role="security",
                            mandatory=True,
                            estimated_hours=8,
                        ),
                    ],
                    exit_criteria=["Forensic audit bundle signed by external investigator"],
                ),
            ],
        ),
        # 7. Corporate ESG Sustainability (2 stages, minimum valid)
        CustomPlaybookDefinition(
            id="playbook.custom-esg-reporting",
            name="Enterprise Scope-1/2/3 Carbon Accounting Playbook",
            goal="Standardize statutory corporate sustainability disclosures under BRSR and CSRD.",
            domain="esg",
            stages=[
                CustomStageDefinition(
                    stage_number=1,
                    stage_name="Emissions Data Collection & Normalization",
                    description="Aggregate cloud compute and data center energy consumption metrics.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.esg.data_01",
                            title="Ingest PUE and electricity bills into carbon calculation engine",
                            role="compliance-officer",
                            mandatory=True,
                            estimated_hours=24,
                        ),
                    ],
                    exit_criteria=[
                        "All facility energy metrics validated with zero missing months"
                    ],
                ),
                CustomStageDefinition(
                    stage_number=2,
                    stage_name="Independent Verification & Board Sign-Off",
                    description="Audit carbon ledger and present statutory report to audit committee.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.esg.signoff_01",
                            title="Obtain limited assurance statement from external auditor",
                            role="risk-lead",
                            mandatory=True,
                            estimated_hours=40,
                        ),
                    ],
                    exit_criteria=["Independent assurance certificate attached to BRSR filing"],
                ),
            ],
        ),
        # 8. AML / Financial Crimes
        CustomPlaybookDefinition(
            id="playbook.custom-aml-monitoring",
            name="Anti-Money Laundering & Sanctions Screening Playbook",
            goal="Enforce automated customer due diligence, PEP screening, and transaction surveillance.",
            domain="financial-crime",
            stages=[
                CustomStageDefinition(
                    stage_number=1,
                    stage_name="Customer Risk Scoring & Screening",
                    description="Screen customers against OFAC, UN, and national sanctions lists.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.aml.screen_01",
                            title="Verify automated PEP and sanction list ingestion pipelines",
                            role="compliance-officer",
                            mandatory=True,
                            estimated_hours=10,
                        ),
                    ],
                    exit_criteria=["Sanctions screening latency <= 50ms per transaction"],
                ),
                CustomStageDefinition(
                    stage_number=2,
                    stage_name="Structuring & Velocity Anomaly Detection",
                    description="Deploy behavioral ML rules to flag smurfing and rapid pass-through funds.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.aml.rules_01",
                            title="Backtest velocity rules against historical SAR dataset",
                            role="developer",
                            mandatory=True,
                            estimated_hours=30,
                        ),
                    ],
                    exit_criteria=["False positive alert rate reduced below 12%"],
                ),
                CustomStageDefinition(
                    stage_number=3,
                    stage_name="Suspicious Activity Report (SAR) Filing",
                    description="Draft and file statutory reports with financial intelligence units.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.aml.sar_01",
                            title="Submit verified SAR dossiers to FIU-IND portal",
                            role="compliance-officer",
                            mandatory=True,
                            estimated_hours=12,
                        ),
                    ],
                    exit_criteria=["Filing reference number logged for all high-risk anomalies"],
                ),
            ],
        ),
        # 9. Multi-Region Disaster Recovery (6 stages, maximum valid)
        CustomPlaybookDefinition(
            id="playbook.custom-multi-region-dr",
            name="Active-Active Multi-Region Cloud Resilience Program",
            goal="Architect cross-region continuous data replication and automated disaster recovery failover.",
            domain="disaster-recovery",
            stages=[
                CustomStageDefinition(
                    stage_number=1,
                    stage_name="Architecture Decoupling & Stateless Services",
                    description="Isolate session states into distributed distributed caches.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.dr.stage1_01",
                            title="Migrate session state from local memory to distributed tier",
                            role="developer",
                            mandatory=True,
                            estimated_hours=24,
                        ),
                    ],
                    exit_criteria=["All edge services achieve 100% statelessness"],
                ),
                CustomStageDefinition(
                    stage_number=2,
                    stage_name="Cross-Region Database Streaming Replication",
                    description="Set up asynchronous write replication with bounded lag.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.dr.stage2_01",
                            title="Configure physical wal replication with lag alerting",
                            role="sre",
                            mandatory=True,
                            estimated_hours=18,
                        ),
                    ],
                    exit_criteria=["Replication lag <= 500ms at p99"],
                ),
                CustomStageDefinition(
                    stage_number=3,
                    stage_name="Global Server Load Balancing (GSLB) Routing",
                    description="Configure latency-based Anycast and health check failover.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.dr.stage3_01",
                            title="Deploy geo-DNS routing with health probing every 5 seconds",
                            role="sre",
                            mandatory=True,
                            estimated_hours=14,
                        ),
                    ],
                    exit_criteria=["Automated DNS failover confirmed within 30 seconds"],
                ),
                CustomStageDefinition(
                    stage_number=4,
                    stage_name="Chaos Engineering & Region Isolation Drill",
                    description="Inject artificial partition to simulate entire region collapse.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.dr.stage4_01",
                            title="Execute Chaos Mesh experiment cutting primary region transit",
                            role="security",
                            mandatory=True,
                            estimated_hours=20,
                        ),
                    ],
                    exit_criteria=["Zero lost transactions during simulated regional black hole"],
                ),
                CustomStageDefinition(
                    stage_number=5,
                    stage_name="Automated Split-Brain Prevention",
                    description="Enforce distributed consensus locks to prevent concurrent split writes.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.dr.stage5_01",
                            title="Implement Raft/etcd distributed fencing tokens for failover",
                            role="developer",
                            mandatory=True,
                            estimated_hours=28,
                        ),
                    ],
                    exit_criteria=["Fencing token prevents dual-master divergence under partition"],
                ),
                CustomStageDefinition(
                    stage_number=6,
                    stage_name="Institutional Business Continuity Sign-Off",
                    description="Review failover metrics with internal audit and board risk committee.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.dr.stage6_01",
                            title="Compile disaster recovery evidence dossier with SLA compliance",
                            role="risk-lead",
                            mandatory=True,
                            estimated_hours=12,
                        ),
                    ],
                    exit_criteria=["Board sign-off on demonstrated RTO <= 15m and RPO <= 1m"],
                ),
            ],
        ),
        # 10. Regulated Open Banking API Security
        CustomPlaybookDefinition(
            id="playbook.custom-open-banking",
            name="Open Banking Financial-Grade API (FAPI) Security Playbook",
            goal="Enforce MTLS, DPoP sender-constrained tokens, and fine-grained consent management.",
            domain="open-banking",
            stages=[
                CustomStageDefinition(
                    stage_number=1,
                    stage_name="FAPI 2.0 Security Profile Alignment",
                    description="Configure mutual TLS client authentication and PAR endpoints.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.ob.fapi_01",
                            title="Enable pushed authorization requests (PAR) on gateway",
                            role="security",
                            mandatory=True,
                            estimated_hours=18,
                        ),
                    ],
                    exit_criteria=["Conformant with OpenID Foundation FAPI 2.0 test suite"],
                ),
                CustomStageDefinition(
                    stage_number=2,
                    stage_name="Consent Lifecycle & Revocation Gateway",
                    description="Implement real-time consent revocation hooks across accounts.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.ob.consent_01",
                            title="Deploy sub-second consent revocation event bus",
                            role="developer",
                            mandatory=True,
                            estimated_hours=22,
                        ),
                    ],
                    exit_criteria=[
                        "Revocation takes effect in <= 250ms across all third-party apps"
                    ],
                ),
                CustomStageDefinition(
                    stage_number=3,
                    stage_name="Third-Party Provider (TPP) Certification",
                    description="Verify TPP eIDAS and regulatory directory certificates.",
                    milestones=[
                        CustomMilestoneDefinition(
                            id="ms.ob.tpp_01",
                            title="Validate TPP eIDAS QWAC/QSEAL cert chains on every TLS handshake",
                            role="sre",
                            mandatory=True,
                            estimated_hours=16,
                        ),
                    ],
                    exit_criteria=[
                        "OCSP stapling response verified with zero expired certificates"
                    ],
                ),
            ],
        ),
    ]


# ==============================================================================
# 1. 10 Custom Enterprise Playbooks Evaluation & Schema Verification
# ==============================================================================


def test_10_custom_enterprise_playbooks_pass_schema_and_convert_to_runtime() -> None:
    playbooks = build_10_custom_enterprise_playbooks()
    assert len(playbooks) == 10

    engine = PlaybookEngine()
    initial_count = len(engine.list_templates())

    for pb in playbooks:
        # 1. Structural schema validation
        validate_custom_playbook_schema(pb)

        # 2. Convert to standard runtime PlaybookTemplate
        runtime_template = convert_custom_to_runtime_template(pb)
        assert runtime_template.playbook_id == pb.id
        assert runtime_template.title == pb.name
        assert runtime_template.total_stages == len(pb.stages)

        # 3. Register with engine
        engine.register_template(runtime_template)
        registered = engine.get_template(pb.id)
        assert registered is not None
        assert registered.playbook_id == pb.id
        assert len(registered.stages) == len(pb.stages)

    assert len(engine.list_templates()) == initial_count + 10


# ==============================================================================
# 2. Structural & Invariant Validation Errors
# ==============================================================================


def test_validation_fails_when_stages_under_minimum() -> None:
    # 1 stage (minimum is 2)
    invalid_pb = CustomPlaybookDefinition.model_construct(
        id="playbook.custom-single-stage",
        name="Invalid Single Stage Playbook",
        goal="Demonstrate boundary failure",
        stages=[
            CustomStageDefinition.model_construct(
                stage_number=1,
                stage_name="Only Stage",
                milestones=[
                    CustomMilestoneDefinition.model_construct(
                        id="m1", title="Task 1", role="sre", mandatory=True, estimated_hours=8
                    ),
                ],
                exit_criteria=["Check 1"],
            )
        ],
    )
    with pytest.raises(CustomPlaybookValidationError) as exc_info:
        validate_custom_playbook_schema(invalid_pb)
    assert "minimum 2 stages required" in str(exc_info.value)


def test_validation_fails_when_stages_exceed_maximum() -> None:
    # 7 stages (maximum is 6)
    stages = [
        CustomStageDefinition.model_construct(
            stage_number=i,
            stage_name=f"Stage {i}",
            milestones=[
                CustomMilestoneDefinition.model_construct(
                    id=f"m{i}", title=f"Task {i}", role="sre", mandatory=True, estimated_hours=8
                )
            ],
            exit_criteria=[f"Exit {i}"],
        )
        for i in range(1, 8)
    ]
    invalid_pb = CustomPlaybookDefinition.model_construct(
        id="playbook.custom-seven-stages",
        name="Invalid Seven Stages Playbook",
        goal="Demonstrate boundary failure",
        stages=stages,
    )
    with pytest.raises(CustomPlaybookValidationError) as exc_info:
        validate_custom_playbook_schema(invalid_pb)
    assert "maximum 6 stages allowed" in str(exc_info.value)


def test_validation_fails_on_duplicate_milestone_ids() -> None:
    invalid_pb = CustomPlaybookDefinition(
        id="playbook.custom-dup-milestone",
        name="Duplicate Milestone Playbook",
        goal="Demonstrate duplicate ID error",
        stages=[
            CustomStageDefinition(
                stage_number=1,
                stage_name="Stage 1",
                milestones=[CustomMilestoneDefinition(id="ms.common.id", title="Milestone 1")],
                exit_criteria=["Exit 1"],
            ),
            CustomStageDefinition(
                stage_number=2,
                stage_name="Stage 2",
                milestones=[CustomMilestoneDefinition(id="ms.common.id", title="Milestone 2")],
                exit_criteria=["Exit 2"],
            ),
        ],
    )
    with pytest.raises(CustomPlaybookValidationError) as exc_info:
        validate_custom_playbook_schema(invalid_pb)
    assert "Duplicate milestone ID 'ms.common.id'" in str(exc_info.value)


def test_validation_fails_on_non_sequential_stage_numbers() -> None:
    invalid_pb = CustomPlaybookDefinition(
        id="playbook.custom-bad-sequence",
        name="Bad Sequence Playbook",
        goal="Demonstrate sequence error",
        stages=[
            CustomStageDefinition(
                stage_number=1,
                stage_name="Stage 1",
                milestones=[CustomMilestoneDefinition(id="m1", title="Task 1")],
                exit_criteria=["Exit 1"],
            ),
            CustomStageDefinition(
                stage_number=3,  # Expected 2
                stage_name="Stage 3",
                milestones=[CustomMilestoneDefinition(id="m2", title="Task 2")],
                exit_criteria=["Exit 2"],
            ),
        ],
    )
    with pytest.raises(CustomPlaybookValidationError) as exc_info:
        validate_custom_playbook_schema(invalid_pb)
    assert "strictly sequential" in str(exc_info.value)


def test_validation_fails_on_empty_exit_criteria() -> None:
    invalid_pb = CustomPlaybookDefinition(
        id="playbook.custom-no-exit",
        name="No Exit Playbook",
        goal="Demonstrate missing exit criteria error",
        stages=[
            CustomStageDefinition(
                stage_number=1,
                stage_name="Stage 1",
                milestones=[CustomMilestoneDefinition(id="m1", title="Task 1")],
                exit_criteria=["  "],  # Whitespace only
            ),
            CustomStageDefinition(
                stage_number=2,
                stage_name="Stage 2",
                milestones=[CustomMilestoneDefinition(id="m2", title="Task 2")],
                exit_criteria=["Exit 2"],
            ),
        ],
    )
    with pytest.raises(CustomPlaybookValidationError) as exc_info:
        validate_custom_playbook_schema(invalid_pb)
    assert "empty exit criterion" in str(exc_info.value)


def test_validation_fails_on_payload_exceeding_size_ceiling() -> None:
    cfg = CustomBuilderConfig(max_template_bytes=500)  # Restrict to 500 bytes for test
    pb = build_10_custom_enterprise_playbooks()[0]
    with pytest.raises(CustomPlaybookValidationError) as exc_info:
        validate_custom_playbook_schema(pb, config=cfg)
    assert "exceeds 500 bytes ceiling" in str(exc_info.value)


# ==============================================================================
# 3. Tenant Quota Enforcement Tests
# ==============================================================================


def test_tenant_quota_enforcement_at_25_playbooks() -> None:
    builder = CustomPlaybookBuilder(config=CustomBuilderConfig(max_custom_playbooks_per_tenant=25))
    tenant = f"tenant-{uuid4().hex[:8]}"

    # Add 25 valid custom playbooks
    for i in range(1, 26):
        pb = CustomPlaybookDefinition(
            id=f"playbook.tenant.{i}",
            name=f"Custom Tenant Playbook {i}",
            goal=f"Tenant goal {i}",
            stages=[
                CustomStageDefinition(
                    stage_number=1,
                    stage_name="Phase 1",
                    milestones=[CustomMilestoneDefinition(id=f"m1_{i}", title="Task 1")],
                    exit_criteria=["Exit 1"],
                ),
                CustomStageDefinition(
                    stage_number=2,
                    stage_name="Phase 2",
                    milestones=[CustomMilestoneDefinition(id=f"m2_{i}", title="Task 2")],
                    exit_criteria=["Exit 2"],
                ),
            ],
        )
        res = builder.save_playbook(pb, tenant_id=tenant)
        assert res.template_id == pb.id
        assert res.is_valid is True

    # 26th playbook should raise QuotaExceededError
    pb_overflow = CustomPlaybookDefinition(
        id="playbook.tenant.26",
        name="Overflow Playbook 26",
        goal="Attempt to exceed quota",
        stages=[
            CustomStageDefinition(
                stage_number=1,
                stage_name="Phase 1",
                milestones=[CustomMilestoneDefinition(id="m1_26", title="Task 1")],
                exit_criteria=["Exit 1"],
            ),
            CustomStageDefinition(
                stage_number=2,
                stage_name="Phase 2",
                milestones=[CustomMilestoneDefinition(id="m2_26", title="Task 2")],
                exit_criteria=["Exit 2"],
            ),
        ],
    )
    with pytest.raises(CustomPlaybookQuotaExceededError) as exc_info:
        builder.save_playbook(pb_overflow, tenant_id=tenant)
    assert "limit of 25 custom playbooks" in str(exc_info.value)

    # Different tenant should still be able to create playbooks (isolation)
    other_tenant = f"other-{uuid4().hex[:8]}"
    other_res = builder.save_playbook(pb_overflow, tenant_id=other_tenant)
    assert other_res.template_id == pb_overflow.id


# ==============================================================================
# 4. Runtime Execution of Custom Playbook
# ==============================================================================


def test_runtime_execution_of_custom_playbook_lifecycle() -> None:
    builder = CustomPlaybookBuilder()
    tenant = f"tenant-exec-{uuid4().hex[:8]}"
    pb = build_10_custom_enterprise_playbooks()[0]  # Vendor risk playbook (3 stages)

    builder.save_playbook(pb, tenant_id=tenant)

    engine = PlaybookEngine()
    # Register in active engine
    engine.register_template(convert_custom_to_runtime_template(pb))

    # 1. Start custom playbook run
    run = engine.start_run(
        playbook_id=pb.id,
        tenant_id=tenant,
        assigned_lead="Compliance Team",
    )
    assert run.playbook_id == pb.id
    assert run.tenant_id == tenant
    assert run.current_stage == 1
    assert run.status == "ACTIVE"
    assert run.total_stages == 3

    # 2. Complete Stage 1 milestones
    for m in pb.stages[0].milestones:
        updated_run = engine.complete_milestone(
            run_id=run.run_id,
            milestone_id=m.id,
            tenant_id=tenant,
        )
        assert updated_run.current_stage == 1

    # 3. Promote to Stage 2 with override justification
    promoted_run = engine.promote_stage(
        run_id=run.run_id,
        tenant_id=tenant,
        override_justification="Verified by compliance team",
    )
    assert promoted_run.current_stage == 2

    # 4. Complete Stage 2 milestones and promote to Stage 3
    for m in pb.stages[1].milestones:
        engine.complete_milestone(
            run_id=run.run_id,
            milestone_id=m.id,
            tenant_id=tenant,
        )

    promoted_run_3 = engine.promote_stage(
        run_id=run.run_id,
        tenant_id=tenant,
        override_justification="Verified by risk committee",
    )
    assert promoted_run_3.current_stage == 3

    # 5. Complete Stage 3 and conclude run
    for m in pb.stages[2].milestones:
        engine.complete_milestone(
            run_id=run.run_id,
            milestone_id=m.id,
            tenant_id=tenant,
        )

    final_run = engine.promote_stage(
        run_id=run.run_id,
        tenant_id=tenant,
        override_justification="All exit criteria verified",
    )
    assert final_run.status == "COMPLETED"


# ==============================================================================
# 5. Validation and Persistence Latency SLA (<= 12.0 ms)
# ==============================================================================


def test_validation_and_save_latency_sla() -> None:
    builder = CustomPlaybookBuilder(config=CustomBuilderConfig(max_custom_playbooks_per_tenant=100))
    tenant = f"bench-{uuid4().hex[:8]}"
    sample_pb = build_10_custom_enterprise_playbooks()[1]  # PQC migration playbook

    durations: list[float] = []

    # Run 50 iterations to measure validation and storage latency
    for idx in range(50):
        # Mutate ID to make unique
        test_pb = CustomPlaybookDefinition(
            id=f"{sample_pb.id}-{idx}",
            name=sample_pb.name,
            goal=sample_pb.goal,
            domain=sample_pb.domain,
            stages=sample_pb.stages,
            metadata=sample_pb.metadata,
        )
        t0 = time.perf_counter()
        builder.save_playbook(test_pb, tenant_id=tenant)
        durations.append((time.perf_counter() - t0) * 1000.0)

    mean_latency = sum(durations) / len(durations)
    max_latency = max(durations)

    # SLA threshold: mean <= 12.0 ms
    assert mean_latency <= 12.0, f"Mean latency {mean_latency:.2f}ms exceeds 12.0ms SLA"
    assert max_latency <= 30.0, f"Max latency spike {max_latency:.2f}ms exceeds 30.0ms tolerance"


# ==============================================================================
# 6. REST API Endpoints Verification
# ==============================================================================


def test_api_create_list_get_custom_playbooks(
    client: TestClient,
    api_headers: dict[str, str],
) -> None:
    tenant = f"api-test-{uuid4().hex[:8]}"
    pb = build_10_custom_enterprise_playbooks()[2]  # AI Risk Governance playbook

    # 1. POST /v1/playbooks/custom
    post_res = client.post(
        f"/v1/playbooks/custom?tenant_id={tenant}",
        json=pb.model_dump(),
        headers=api_headers,
    )
    assert post_res.status_code == 200, post_res.text
    data = post_res.json()
    assert data["template_id"] == pb.id
    assert data["is_valid"] is True
    assert data["stages_count"] == len(pb.stages)

    # 2. GET /v1/playbooks/custom
    list_res = client.get(
        f"/v1/playbooks/custom?tenant_id={tenant}",
        headers=api_headers,
    )
    assert list_res.status_code == 200, list_res.text
    list_data = list_res.json()
    assert list_data["tenant_id"] == tenant
    assert list_data["total_count"] >= 1
    found = any(p["id"] == pb.id for p in list_data["playbooks"])
    assert found is True

    # 3. GET /v1/playbooks/custom/{playbook_id}
    get_res = client.get(
        f"/v1/playbooks/custom/{pb.id}?tenant_id={tenant}",
        headers=api_headers,
    )
    assert get_res.status_code == 200, get_res.text
    get_data = get_res.json()
    assert get_data["id"] == pb.id
    assert get_data["name"] == pb.name
    assert len(get_data["stages"]) == len(pb.stages)

    # 4. GET non-existent playbook -> 404
    missing_res = client.get(
        f"/v1/playbooks/custom/non-existent-id?tenant_id={tenant}",
        headers=api_headers,
    )
    assert missing_res.status_code == 404


def test_api_create_custom_playbook_validation_error_422(
    client: TestClient,
    api_headers: dict[str, str],
) -> None:
    tenant = f"api-err-{uuid4().hex[:8]}"
    # Invalid: duplicate milestone IDs across stages (triggers CustomPlaybookValidationError in endpoint)
    invalid_payload = {
        "id": "playbook.custom.invalid",
        "name": "Invalid Duplicate Milestone Playbook",
        "goal": "Test 422 response",
        "stages": [
            {
                "stage_number": 1,
                "stage_name": "Stage 1",
                "milestones": [
                    {
                        "id": "ms.common.dup",
                        "title": "Milestone 1",
                        "role": "sre",
                        "mandatory": True,
                        "estimated_hours": 8,
                    }
                ],
                "exit_criteria": ["Done 1"],
            },
            {
                "stage_number": 2,
                "stage_name": "Stage 2",
                "milestones": [
                    {
                        "id": "ms.common.dup",
                        "title": "Milestone 2",
                        "role": "developer",
                        "mandatory": True,
                        "estimated_hours": 8,
                    }
                ],
                "exit_criteria": ["Done 2"],
            },
        ],
    }

    res = client.post(
        f"/v1/playbooks/custom?tenant_id={tenant}",
        json=invalid_payload,
        headers=api_headers,
    )
    assert res.status_code == 422
    err_body = res.json()
    assert "errors" in err_body["detail"] or "message" in err_body["detail"]
