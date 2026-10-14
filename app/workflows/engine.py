"""Interactive Compliance Playbook Runtime (FEAT-051).

Operationalizes the 12 structured playbooks from the taxonomy as active
state-machine compliance workflows with multi-tenant PostgreSQL persistence
and strict stage progression validation.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, cast

from app.observability import get_logger

logger = get_logger("docscout.workflows.engine")

RunStatus = Literal["ACTIVE", "BLOCKED", "COMPLETED"]


class PlaybookError(Exception):
    """Base error for playbook operations."""


class PlaybookNotFoundError(PlaybookError):
    """Raised when a playbook template does not exist."""


class PlaybookRunNotFoundError(PlaybookError):
    """Raised when a playbook execution run is not found."""


class InvalidStateTransitionError(PlaybookError):
    """Raised when a stage transition or status change violates workflow rules."""


@dataclass(frozen=True)
class MilestoneDefinition:
    """Definition of an individual milestone within a playbook stage."""

    id: str
    title: str
    role: str
    mandatory: bool = True
    estimated_hours: int = 8


@dataclass(frozen=True)
class StageDefinition:
    """Definition of a discrete stage within a playbook."""

    stage_number: int
    stage_name: str
    description: str
    milestones: list[MilestoneDefinition]
    exit_criteria: list[str]


@dataclass(frozen=True)
class PlaybookTemplate:
    """Static template definition for a statutory compliance playbook."""

    playbook_id: str
    title: str
    description: str
    domain: str
    total_stages: int = 4
    stages: list[StageDefinition] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "playbook_id": self.playbook_id,
            "title": self.title,
            "description": self.description,
            "domain": self.domain,
            "total_stages": self.total_stages,
            "stages": [
                {
                    "stage_number": s.stage_number,
                    "stage_name": s.stage_name,
                    "description": s.description,
                    "milestones": [asdict(m) for m in s.milestones],
                    "exit_criteria": s.exit_criteria,
                }
                for s in self.stages
            ],
        }


@dataclass
class PlaybookRun:
    """Active instance of a playbook execution for a specific tenant."""

    run_id: str
    tenant_id: str
    playbook_id: str
    title: str
    assigned_lead: str
    current_stage: int
    total_stages: int
    status: RunStatus
    stage_data: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "tenant_id": self.tenant_id,
            "playbook_id": self.playbook_id,
            "title": self.title,
            "assigned_lead": self.assigned_lead,
            "current_stage": self.current_stage,
            "total_stages": self.total_stages,
            "status": self.status,
            "stage_data": self.stage_data,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class PlaybookEngineConfig:
    """Configuration for playbook workflow state machine."""

    allow_stage_skipping: bool = False
    auto_verify_exit_criteria: bool = True


# Pre-seeded catalog of 12 statutory enterprise compliance playbooks
BUILTIN_PLAYBOOKS: list[PlaybookTemplate] = [
    PlaybookTemplate(
        playbook_id="playbook.foundations-30d",
        title="Foundations 30-Day Engineering Decoupling",
        description="Establish decoupled service boundaries, hermetic test fixtures, and modular regulatory controls.",
        domain="core-architecture",
        stages=[
            StageDefinition(
                stage_number=1,
                stage_name="Decouple / Establish",
                description="Catalog existing monorepo boundaries and inventory regulatory dependency edges.",
                milestones=[
                    MilestoneDefinition(
                        "M1-1", "Map database dependencies and domain boundary edges", "sre"
                    ),
                    MilestoneDefinition(
                        "M1-2", "Draft architectural decoupling ADR and API contracts", "developer"
                    ),
                ],
                exit_criteria=[
                    "Domain interfaces documented with zero circular schema references."
                ],
            ),
            StageDefinition(
                stage_number=2,
                stage_name="Bound / Contain",
                description="Implement architectural bulkheads and isolate critical transaction pathways.",
                milestones=[
                    MilestoneDefinition(
                        "M2-1",
                        "Enforce service boundary linting and strict package visibility",
                        "developer",
                    ),
                    MilestoneDefinition(
                        "M2-2", "Deploy bulkhead concurrency limits for tenant workloads", "sre"
                    ),
                ],
                exit_criteria=["Zero uncontained cross-boundary database queries detected in CI."],
            ),
            StageDefinition(
                stage_number=3,
                stage_name="Automate",
                description="Automate CI regression testing and dependency graph validation.",
                milestones=[
                    MilestoneDefinition(
                        "M3-1",
                        "Configure automated boundary regression gates in CI pipeline",
                        "qa-engineer",
                    ),
                    MilestoneDefinition(
                        "M3-2",
                        "Implement automated mock interfaces for external banking services",
                        "developer",
                    ),
                ],
                exit_criteria=["Automated test suite achieves 100% boundary contract pass rate."],
            ),
            StageDefinition(
                stage_number=4,
                stage_name="Self-Govern",
                description="Continuous architectural governance and automated drift alerts.",
                milestones=[
                    MilestoneDefinition(
                        "M4-1", "Activate real-time architecture drift Prometheus alerts", "sre"
                    ),
                    MilestoneDefinition(
                        "M4-2",
                        "Conduct final architecture audit review with compliance lead",
                        "compliance-officer",
                    ),
                ],
                exit_criteria=[
                    "Zero architectural boundary regressions over a 14-day observation window."
                ],
            ),
        ],
    ),
    PlaybookTemplate(
        playbook_id="playbook.deploy-confidence-60d",
        title="Continuous Delivery & Deployment Confidence 60-Day",
        description="Build high-confidence deployment pipeline with Automated Canary Analysis (ACA) and error budgets.",
        domain="devops-delivery",
        stages=[
            StageDefinition(
                stage_number=1,
                stage_name="Decouple / Establish",
                description="Establish deployment telemetry baselines and service level objectives (SLOs).",
                milestones=[
                    MilestoneDefinition(
                        "M1-1", "Define SLI/SLO metrics and calculate initial error budgets", "sre"
                    ),
                    MilestoneDefinition(
                        "M1-2",
                        "Inventory deployment artifacts and cryptographic signing keys",
                        "sre",
                    ),
                ],
                exit_criteria=["SLI/SLO catalog published and signed by engineering management."],
            ),
            StageDefinition(
                stage_number=2,
                stage_name="Bound / Contain",
                description="Deploy canary routing infrastructure and staged blast radius controls.",
                milestones=[
                    MilestoneDefinition(
                        "M2-1", "Configure 1% traffic split canary routing in gateway", "sre"
                    ),
                    MilestoneDefinition(
                        "M2-2", "Implement automated rollback hooks upon error budget burn", "sre"
                    ),
                ],
                exit_criteria=["Synthetic rollback drill verified in staging environment."],
            ),
            StageDefinition(
                stage_number=3,
                stage_name="Automate",
                description="Automate canary analysis gating and metric statistical comparison.",
                milestones=[
                    MilestoneDefinition(
                        "M3-1", "Enable Kayenta/ACA statistical metric comparison in CI/CD", "sre"
                    ),
                    MilestoneDefinition(
                        "M3-2",
                        "Automate progressive rollout (1% -> 5% -> 25% -> 100%)",
                        "developer",
                    ),
                ],
                exit_criteria=["Automated canary analysis successfully halts faulty deployment."],
            ),
            StageDefinition(
                stage_number=4,
                stage_name="Self-Govern",
                description="Continuous release confidence with zero manual intervention for healthy deployments.",
                milestones=[
                    MilestoneDefinition(
                        "M4-1",
                        "Enable autonomous progressive release for all production tiers",
                        "engineering-manager",
                    ),
                    MilestoneDefinition(
                        "M4-2",
                        "Publish monthly error budget and deployment velocity scorecard",
                        "sre",
                    ),
                ],
                exit_criteria=["At least 10 consecutive zero-incident production deployments."],
            ),
        ],
    ),
    PlaybookTemplate(
        playbook_id="playbook.ai-assurance",
        title="AI & LLM Model Assurance & Governance",
        description="Operationalize model explainability, bias auditing, kill switches, and continuous drift monitoring.",
        domain="ai-ml-governance",
        stages=[
            StageDefinition(
                stage_number=1,
                stage_name="Decouple / Establish",
                description="Catalog all production AI/ML models and register model cards with regulatory scope.",
                milestones=[
                    MilestoneDefinition(
                        "M1-1",
                        "Inventory active algorithms and classify SEBI/RBI risk tiers",
                        "compliance-officer",
                    ),
                    MilestoneDefinition(
                        "M1-2",
                        "Publish formal model card documentation and training provenance",
                        "developer",
                    ),
                ],
                exit_criteria=["100% of production models registered in AI Governance catalog."],
            ),
            StageDefinition(
                stage_number=2,
                stage_name="Bound / Contain",
                description="Implement model circuit breakers, kill switches, and prompt injection shields.",
                milestones=[
                    MilestoneDefinition(
                        "M2-1", "Deploy low-latency hardware or software kill switches", "sre"
                    ),
                    MilestoneDefinition(
                        "M2-2",
                        "Integrate input sanitization and prompt injection shields",
                        "developer",
                    ),
                ],
                exit_criteria=[
                    "Automated kill switch halts inference flow within < 50ms upon test trigger."
                ],
            ),
            StageDefinition(
                stage_number=3,
                stage_name="Automate",
                description="Automate explainability pipelines (SHAP/LIME) and recurring bias audits.",
                milestones=[
                    MilestoneDefinition(
                        "M3-1",
                        "Integrate TreeSHAP feature importance pipelines into inference",
                        "developer",
                    ),
                    MilestoneDefinition(
                        "M3-2",
                        "Automate weekly disparate impact and demographic parity tests",
                        "qa-engineer",
                    ),
                ],
                exit_criteria=[
                    "Disparate impact ratio verified >= 0.80 across protected classifications."
                ],
            ),
            StageDefinition(
                stage_number=4,
                stage_name="Self-Govern",
                description="Continuous telemetry monitoring Population Stability Index (PSI) and concept drift.",
                milestones=[
                    MilestoneDefinition(
                        "M4-1", "Configure automated PSI and embedding drift alerts", "sre"
                    ),
                    MilestoneDefinition(
                        "M4-2",
                        "Complete annual independent system audit by CERT-In auditor",
                        "compliance-officer",
                    ),
                ],
                exit_criteria=[
                    "Audit certificate issued confirming zero unresolved critical findings."
                ],
            ),
        ],
    ),
    PlaybookTemplate(
        playbook_id="playbook.incident-readiness",
        title="Regulatory Cyber Incident Response & 6-Hour Reporting",
        description="Operationalize cyber incident response, forensic evidence preservation, and RBI/CERT-In reporting.",
        domain="cyber-security",
        stages=[
            StageDefinition(
                stage_number=1,
                stage_name="Decouple / Establish",
                description="Designate incident command roles and verify communication out-of-band channels.",
                milestones=[
                    MilestoneDefinition(
                        "M1-1",
                        "Appoint Incident Commander and statutory reporting liaison",
                        "compliance-officer",
                    ),
                    MilestoneDefinition(
                        "M1-2", "Establish encrypted out-of-band communication war room", "sre"
                    ),
                ],
                exit_criteria=[
                    "Contact directory and call tree verified with all crisis stakeholders."
                ],
            ),
            StageDefinition(
                stage_number=2,
                stage_name="Bound / Contain",
                description="Establish isolation protocols, network segmentation, and credential revocation.",
                milestones=[
                    MilestoneDefinition(
                        "M2-1", "Configure one-click compromised network segment isolation", "sre"
                    ),
                    MilestoneDefinition(
                        "M2-2",
                        "Prepare automated enterprise token and API key revocation scripts",
                        "sre",
                    ),
                ],
                exit_criteria=[
                    "Isolation mechanism tested with zero impact to unaffected services."
                ],
            ),
            StageDefinition(
                stage_number=3,
                stage_name="Automate",
                description="Automate forensic memory capture and statutory incident dossier generation.",
                milestones=[
                    MilestoneDefinition(
                        "M3-1", "Deploy automated volatile memory and audit log snapshotting", "sre"
                    ),
                    MilestoneDefinition(
                        "M3-2",
                        "Generate standardized CERT-In and RBI 6-hour incident report draft",
                        "compliance-officer",
                    ),
                ],
                exit_criteria=[
                    "Simulated drill verifies end-to-end report generation within < 2 hours."
                ],
            ),
            StageDefinition(
                stage_number=4,
                stage_name="Self-Govern",
                description="Post-incident root cause remediation and regulator audit package closure.",
                milestones=[
                    MilestoneDefinition(
                        "M4-1",
                        "Deliver comprehensive 72-hour root cause analysis (RCA)",
                        "engineering-manager",
                    ),
                    MilestoneDefinition(
                        "M4-2",
                        "Submit formal closure certificate and preventative roadmap to RBI",
                        "compliance-officer",
                    ),
                ],
                exit_criteria=[
                    "Statutory regulator confirms acceptance of incident closure filing."
                ],
            ),
        ],
    ),
    PlaybookTemplate(
        playbook_id="playbook.regulated-release",
        title="Regulated Release Certification & Verification Pipeline",
        description="Establish formal safety cases, verification evidence dossiers, and pre-release compliance gates.",
        domain="release-governance",
        stages=[
            StageDefinition(
                stage_number=1,
                stage_name="Decouple / Establish",
                description="Define release certification policies and mandatory statutory evidence checklists.",
                milestones=[
                    MilestoneDefinition(
                        "M1-1",
                        "Define release gate criteria across security, tests, and compliance",
                        "compliance-officer",
                    ),
                    MilestoneDefinition(
                        "M1-2", "Configure SLSA Level 3 cryptographic provenance attestation", "sre"
                    ),
                ],
                exit_criteria=["Release governance policy ratified by technology risk committee."],
            ),
            StageDefinition(
                stage_number=2,
                stage_name="Bound / Contain",
                description="Enforce automated pre-merge static analysis, SBOM generation, and secret scans.",
                milestones=[
                    MilestoneDefinition(
                        "M2-1",
                        "Mandate automated SBOM generation (SPDX/CycloneDX) on all builds",
                        "developer",
                    ),
                    MilestoneDefinition(
                        "M2-2",
                        "Block builds with high/critical CVEs or unapproved OSS licenses",
                        "qa-engineer",
                    ),
                ],
                exit_criteria=[
                    "Zero critical vulnerabilities or missing licenses in release candidates."
                ],
            ),
            StageDefinition(
                stage_number=3,
                stage_name="Automate",
                description="Automate formal Safety Case generation and digital signature of release bundles.",
                milestones=[
                    MilestoneDefinition(
                        "M3-1",
                        "Automate compilation of test execution and coverage evidence",
                        "qa-engineer",
                    ),
                    MilestoneDefinition(
                        "M3-2",
                        "Cryptographically sign release bundle with hardware-backed key",
                        "sre",
                    ),
                ],
                exit_criteria=[
                    "Automated verification bundle passes cryptographic integrity verification."
                ],
            ),
            StageDefinition(
                stage_number=4,
                stage_name="Self-Govern",
                description="Continuous post-release audit logging and rollback certification.",
                milestones=[
                    MilestoneDefinition(
                        "M4-1",
                        "Enforce 14-day post-release observation window for major releases",
                        "sre",
                    ),
                    MilestoneDefinition(
                        "M4-2",
                        "Archive immutable release compliance dossier in 7-year WORM storage",
                        "compliance-officer",
                    ),
                ],
                exit_criteria=[
                    "Release dossier successfully archived with SHA-256 verification receipt."
                ],
            ),
        ],
    ),
    PlaybookTemplate(
        playbook_id="playbook.crypto-migration",
        title="Post-Quantum Cryptographic Migration Tracker",
        description="Orchestrate inventorying of classical RSA/ECC cryptography, hybrid key exchange, and PQC transition.",
        domain="cryptography",
        stages=[
            StageDefinition(
                stage_number=1,
                stage_name="Decouple / Establish",
                description="Inventory all cryptographic algorithms, TLS certificates, and key stores across infrastructure.",
                milestones=[
                    MilestoneDefinition(
                        "M1-1",
                        "Scan codebase and infrastructure for RSA < 2048 and ECC usage",
                        "sre",
                    ),
                    MilestoneDefinition(
                        "M1-2", "Create Cryptographic Bill of Materials (CBOM)", "developer"
                    ),
                ],
                exit_criteria=[
                    "Comprehensive CBOM generated covering 100% of production services."
                ],
            ),
            StageDefinition(
                stage_number=2,
                stage_name="Bound / Contain",
                description="Isolate cryptographic modules behind quantum-safe abstraction wrappers.",
                milestones=[
                    MilestoneDefinition(
                        "M2-1",
                        "Refactor crypto primitives behind abstract provider interfaces",
                        "developer",
                    ),
                    MilestoneDefinition(
                        "M2-2",
                        "Deploy hybrid post-quantum key exchange (ML-KEM / Kyber) in canary",
                        "sre",
                    ),
                ],
                exit_criteria=[
                    "Hybrid key exchange passes inter-service communication latency tests."
                ],
            ),
            StageDefinition(
                stage_number=3,
                stage_name="Automate",
                description="Automate certificate rotation with post-quantum digital signatures (ML-DSA / Dilithium).",
                milestones=[
                    MilestoneDefinition(
                        "M3-1",
                        "Automate ACME certificate issuance with quantum-resistant keys",
                        "sre",
                    ),
                    MilestoneDefinition(
                        "M3-2",
                        "Benchmark handshake performance under post-quantum payload sizes",
                        "qa-engineer",
                    ),
                ],
                exit_criteria=["PQC certificate rotation automated without handshake timeouts."],
            ),
            StageDefinition(
                stage_number=4,
                stage_name="Self-Govern",
                description="Complete retirement of legacy classical crypto and achieve FIPS 203/204 conformity.",
                milestones=[
                    MilestoneDefinition(
                        "M4-1",
                        "Deprecate non-hybrid classical cipher suites across all endpoints",
                        "sre",
                    ),
                    MilestoneDefinition(
                        "M4-2",
                        "Conduct third-party post-quantum readiness audit certification",
                        "compliance-officer",
                    ),
                ],
                exit_criteria=[
                    "100% of external and internal traffic protected with quantum-safe ciphers."
                ],
            ),
        ],
    ),
    PlaybookTemplate(
        playbook_id="playbook.resilience",
        title="Digital Operational Resilience (DORA / RBI Framework)",
        description="Implement end-to-end ICT operational resilience, threat-led penetration testing, and failover drills.",
        domain="operational-resilience",
        stages=[
            StageDefinition(
                stage_number=1,
                stage_name="Decouple / Establish",
                description="Map critical economic functions and identify single points of ICT failure.",
                milestones=[
                    MilestoneDefinition(
                        "M1-1",
                        "Document critical banking business services and ICT asset map",
                        "sre",
                    ),
                    MilestoneDefinition(
                        "M1-2",
                        "Establish maximum tolerable downtime (MTD) and RTO/RPO targets",
                        "compliance-officer",
                    ),
                ],
                exit_criteria=["Critical service dependency map signed off by Risk Committee."],
            ),
            StageDefinition(
                stage_number=2,
                stage_name="Bound / Contain",
                description="Implement multi-region active-active architectures and automated failovers.",
                milestones=[
                    MilestoneDefinition(
                        "M2-1",
                        "Deploy cross-region database replication with zero data loss",
                        "sre",
                    ),
                    MilestoneDefinition(
                        "M2-2",
                        "Configure automatic DNS and traffic failover between datacenters",
                        "sre",
                    ),
                ],
                exit_criteria=["Automated failover successfully executed in staging within RTO."],
            ),
            StageDefinition(
                stage_number=3,
                stage_name="Automate",
                description="Conduct continuous chaos engineering fault injection and automated DR drills.",
                milestones=[
                    MilestoneDefinition(
                        "M3-1", "Schedule recurring unannounced chaos engineering injections", "sre"
                    ),
                    MilestoneDefinition(
                        "M3-2",
                        "Execute threat-led penetration testing (TLPT) per DORA Article 26",
                        "qa-engineer",
                    ),
                ],
                exit_criteria=["Full simulated datacenter blackout recovered within < 15 minutes."],
            ),
            StageDefinition(
                stage_number=4,
                stage_name="Self-Govern",
                description="Autonomous operational resilience reporting and annual board certification.",
                milestones=[
                    MilestoneDefinition(
                        "M4-1",
                        "Publish automated real-time resilience dashboard for executive board",
                        "engineering-manager",
                    ),
                    MilestoneDefinition(
                        "M4-2",
                        "File annual digital operational resilience report with regulator",
                        "compliance-officer",
                    ),
                ],
                exit_criteria=[
                    "Statutory resilience filing confirmed without supervisory remarks."
                ],
            ),
        ],
    ),
    PlaybookTemplate(
        playbook_id="playbook.data-governance",
        title="Statutory Data Protection, DPDPA 2023 & Localization",
        description="Enforce Indian onshore data localization, consent management, and data principal privacy rights.",
        domain="data-privacy",
        stages=[
            StageDefinition(
                stage_number=1,
                stage_name="Decouple / Establish",
                description="Discover and classify all Customer PII, biometric, and financial transaction records.",
                milestones=[
                    MilestoneDefinition(
                        "M1-1",
                        "Execute automated data discovery scan across all databases and S3 buckets",
                        "developer",
                    ),
                    MilestoneDefinition(
                        "M1-2",
                        "Publish Data Inventory and Record of Processing Activities (RoPA)",
                        "compliance-officer",
                    ),
                ],
                exit_criteria=["100% of data stores mapped with classification labels."],
            ),
            StageDefinition(
                stage_number=2,
                stage_name="Bound / Contain",
                description="Enforce strict onshore data residency and cryptographic data-at-rest encryption.",
                milestones=[
                    MilestoneDefinition(
                        "M2-1",
                        "Verify all customer financial databases are hosted within India datacenters",
                        "sre",
                    ),
                    MilestoneDefinition(
                        "M2-2",
                        "Deploy envelope encryption using KMS keys stored within Indian jurisdiction",
                        "sre",
                    ),
                ],
                exit_criteria=["Zero offshore outbound network flows detected for sensitive data."],
            ),
            StageDefinition(
                stage_number=3,
                stage_name="Automate",
                description="Automate consent capture, verifiable revocation, and Right-to-Erasure workflows.",
                milestones=[
                    MilestoneDefinition(
                        "M3-1",
                        "Implement DPDPA consent management API with cryptographic receipts",
                        "developer",
                    ),
                    MilestoneDefinition(
                        "M3-2",
                        "Automate data erasure pipeline verifying deletion across replica stores",
                        "developer",
                    ),
                ],
                exit_criteria=["Data erasure requests processed within statutory 72-hour window."],
            ),
            StageDefinition(
                stage_number=4,
                stage_name="Self-Govern",
                description="Continuous privacy posture monitoring and Data Protection Board compliance filings.",
                milestones=[
                    MilestoneDefinition(
                        "M4-1",
                        "Deploy continuous telemetry scanning for unencrypted PII in logs",
                        "sre",
                    ),
                    MilestoneDefinition(
                        "M4-2",
                        "Complete annual Data Protection Impact Assessment (DPIA)",
                        "compliance-officer",
                    ),
                ],
                exit_criteria=["Annual DPIA certification signed off by Data Protection Officer."],
            ),
        ],
    ),
    PlaybookTemplate(
        playbook_id="playbook.vendor-risk",
        title="Third-Party Cloud & IT Outsourcing Compliance",
        description="Evaluate vendor master services agreements against RBI outsourcing mandates and SEBI cloud rules.",
        domain="vendor-governance",
        stages=[
            StageDefinition(
                stage_number=1,
                stage_name="Decouple / Establish",
                description="Inventory third-party SaaS and cloud providers and classify outsourcing materiality.",
                milestones=[
                    MilestoneDefinition(
                        "M1-1",
                        "Catalog all third-party vendors and categorize materiality tiers",
                        "compliance-officer",
                    ),
                    MilestoneDefinition(
                        "M1-2",
                        "Assemble existing Master Services Agreements and SLAs",
                        "compliance-officer",
                    ),
                ],
                exit_criteria=["Material vendor register approved by Board Outsourcing Committee."],
            ),
            StageDefinition(
                stage_number=2,
                stage_name="Bound / Contain",
                description="Audit contracts for statutory clauses (unconditional audit access, data sovereignty).",
                milestones=[
                    MilestoneDefinition(
                        "M2-1",
                        "Scan vendor agreements with automated statutory clause engine",
                        "compliance-officer",
                    ),
                    MilestoneDefinition(
                        "M2-2",
                        "Negotiate mandatory compliance addendums for non-conforming clauses",
                        "compliance-officer",
                    ),
                ],
                exit_criteria=[
                    "Zero material vendors lacking unconditional RBI audit inspection rights."
                ],
            ),
            StageDefinition(
                stage_number=3,
                stage_name="Automate",
                description="Automate continuous vendor telemetry monitoring and SOC-2 / ISO certificate verification.",
                milestones=[
                    MilestoneDefinition(
                        "M3-1",
                        "Automate tracking of vendor SOC-2 Type II certificate renewal dates",
                        "compliance-officer",
                    ),
                    MilestoneDefinition(
                        "M3-2",
                        "Integrate automated vendor uptime and security posture feeds",
                        "sre",
                    ),
                ],
                exit_criteria=[
                    "100% of material vendors hold current, valid SOC-2 / ISO certifications."
                ],
            ),
            StageDefinition(
                stage_number=4,
                stage_name="Self-Govern",
                description="Execute annual vendor exit strategy drills and joint business continuity testing.",
                milestones=[
                    MilestoneDefinition(
                        "M4-1",
                        "Conduct simulated cloud vendor exit and workload migration drill",
                        "sre",
                    ),
                    MilestoneDefinition(
                        "M4-2",
                        "Submit annual outsourcing compliance return to RBI supervisory team",
                        "compliance-officer",
                    ),
                ],
                exit_criteria=[
                    "Vendor exit transition verified capable of completion within < 90 days."
                ],
            ),
        ],
    ),
    PlaybookTemplate(
        playbook_id="playbook.audit-prep",
        title="Annual Statutory System & Algorithm Audit Readiness",
        description="Comprehensive readiness workflow for annual CERT-In and CISA accredited system audits.",
        domain="audit-assurance",
        stages=[
            StageDefinition(
                stage_number=1,
                stage_name="Decouple / Establish",
                description="Scope audit perimeter and assign evidence custodians across engineering teams.",
                milestones=[
                    MilestoneDefinition(
                        "M1-1",
                        "Establish audit scope matrix covering all regulated trading and banking nodes",
                        "compliance-officer",
                    ),
                    MilestoneDefinition(
                        "M1-2",
                        "Assign evidence custodians for network, application, and database controls",
                        "engineering-manager",
                    ),
                ],
                exit_criteria=["Audit scope matrix approved by statutory audit liaison."],
            ),
            StageDefinition(
                stage_number=2,
                stage_name="Bound / Contain",
                description="Execute pre-audit gap assessments and remediate known compliance findings.",
                milestones=[
                    MilestoneDefinition(
                        "M2-1",
                        "Run automated antipattern scanner and resolve high/critical issues",
                        "developer",
                    ),
                    MilestoneDefinition(
                        "M2-2",
                        "Verify all user access recertifications and privileged account logs",
                        "sre",
                    ),
                ],
                exit_criteria=["Zero unresolved high or critical pre-audit compliance gaps."],
            ),
            StageDefinition(
                stage_number=3,
                stage_name="Automate",
                description="Generate cryptographically signed audit evidence package with SHA-256 provenance.",
                milestones=[
                    MilestoneDefinition(
                        "M3-1",
                        "Compile complete audit evidence package (PDF/ZIP with manifest)",
                        "compliance-officer",
                    ),
                    MilestoneDefinition(
                        "M3-2",
                        "Verify immutable timestamping and evidence digital signatures",
                        "sre",
                    ),
                ],
                exit_criteria=[
                    "Audit evidence package export completes successfully with 100% verified hashes."
                ],
            ),
            StageDefinition(
                stage_number=4,
                stage_name="Self-Govern",
                description="Audit execution with external auditors and management response sign-off.",
                milestones=[
                    MilestoneDefinition(
                        "M4-1",
                        "Host external auditor walkthroughs and track information requests",
                        "compliance-officer",
                    ),
                    MilestoneDefinition(
                        "M4-2",
                        "File finalized Clean System Audit Report with SEBI and RBI",
                        "compliance-officer",
                    ),
                ],
                exit_criteria=["Clean audit report received with zero material non-conformities."],
            ),
        ],
    ),
    PlaybookTemplate(
        playbook_id="playbook.zero-trust",
        title="Zero-Trust Identity Federation & Micro-Segmentation",
        description="Implement OIDC zero-trust identity, ephemeral mutual TLS, and dynamic role-based access control.",
        domain="identity-security",
        stages=[
            StageDefinition(
                stage_number=1,
                stage_name="Decouple / Establish",
                description="Catalog all human and service identities and eliminate static API keys.",
                milestones=[
                    MilestoneDefinition(
                        "M1-1",
                        "Inventory all service accounts, API keys, and machine credentials",
                        "sre",
                    ),
                    MilestoneDefinition(
                        "M1-2", "Draft Zero-Trust Architecture Migration roadmap and policy", "sre"
                    ),
                ],
                exit_criteria=[
                    "Comprehensive identity inventory published; static root keys revoked."
                ],
            ),
            StageDefinition(
                stage_number=2,
                stage_name="Bound / Contain",
                description="Deploy service mesh mutual TLS and ephemeral short-lived identity tokens.",
                milestones=[
                    MilestoneDefinition(
                        "M2-1", "Enforce strict mTLS across all pod-to-pod communication", "sre"
                    ),
                    MilestoneDefinition(
                        "M2-2",
                        "Configure SPIFFE/SPIRE workload attestation and token issuance",
                        "sre",
                    ),
                ],
                exit_criteria=["100% of inter-service traffic encrypted and verified via mTLS."],
            ),
            StageDefinition(
                stage_number=3,
                stage_name="Automate",
                description="Enforce fine-grained attribute-based access control (ABAC) and step-up auth.",
                milestones=[
                    MilestoneDefinition(
                        "M3-1",
                        "Integrate OPA / Cedar authorization policies into API gateways",
                        "developer",
                    ),
                    MilestoneDefinition(
                        "M3-2",
                        "Automate Just-In-Time (JIT) privileged access elevation workflows",
                        "sre",
                    ),
                ],
                exit_criteria=[
                    "Zero permanent administrative permissions granted across infrastructure."
                ],
            ),
            StageDefinition(
                stage_number=4,
                stage_name="Self-Govern",
                description="Continuous behavioral anomaly detection and automated credential revocation.",
                milestones=[
                    MilestoneDefinition(
                        "M4-1",
                        "Deploy machine identity behavioral telemetry and anomaly alerting",
                        "sre",
                    ),
                    MilestoneDefinition(
                        "M4-2",
                        "Achieve NIST SP 800-207 Zero Trust Architecture conformity",
                        "compliance-officer",
                    ),
                ],
                exit_criteria=[
                    "Continuous automated access recertification running with zero gaps."
                ],
            ),
        ],
    ),
    PlaybookTemplate(
        playbook_id="playbook.continuous-compliance",
        title="Continuous Automated Compliance & Observation Windows",
        description="Transition from point-in-time audits to real-time telemetry observation windows with streak tracking.",
        domain="continuous-assurance",
        stages=[
            StageDefinition(
                stage_number=1,
                stage_name="Decouple / Establish",
                description="Map statutory controls to automated telemetry probes and continuous test runners.",
                milestones=[
                    MilestoneDefinition(
                        "M1-1",
                        "Catalog automated control probes across infrastructure and CI",
                        "sre",
                    ),
                    MilestoneDefinition(
                        "M1-2",
                        "Configure telemetry ingestion API with SHA-256 evidence hashing",
                        "developer",
                    ),
                ],
                exit_criteria=[
                    "Telemetry ingestion pipeline verified capable of >= 1,000 events/sec."
                ],
            ),
            StageDefinition(
                stage_number=2,
                stage_name="Bound / Contain",
                description="Configure 90-day observation windows and threshold alerting for control failures.",
                milestones=[
                    MilestoneDefinition(
                        "M2-1",
                        "Establish 90-day observation window baselines for critical controls",
                        "compliance-officer",
                    ),
                    MilestoneDefinition(
                        "M2-2",
                        "Deploy instantaneous alerting upon any compliance test failure",
                        "sre",
                    ),
                ],
                exit_criteria=["Observation window calculation returns within < 5ms p95."],
            ),
            StageDefinition(
                stage_number=3,
                stage_name="Automate",
                description="Automate unbroken pass streak tracking and autonomous evidence archival.",
                milestones=[
                    MilestoneDefinition(
                        "M3-1",
                        "Enable streak tracking evaluating continuous daily check passes",
                        "developer",
                    ),
                    MilestoneDefinition(
                        "M3-2",
                        "Automate real-time compliance telemetry dashboard in console UI",
                        "qa-engineer",
                    ),
                ],
                exit_criteria=[
                    "Unbroken compliance pass streak reaches target threshold (e.g. 30 days)."
                ],
            ),
            StageDefinition(
                stage_number=4,
                stage_name="Self-Govern",
                description="Achieve continuous supervisory compliance certification with zero manual filings.",
                milestones=[
                    MilestoneDefinition(
                        "M4-1",
                        "Publish continuous assurance live stream for statutory auditors",
                        "compliance-officer",
                    ),
                    MilestoneDefinition(
                        "M4-2",
                        "Certify 90-day unbroken compliance record across all core controls",
                        "compliance-officer",
                    ),
                ],
                exit_criteria=["Continuous 90-day compliance certified with >= 99.5% pass ratio."],
            ),
        ],
    ),
]


class PlaybookEngine:
    """Manages compliance playbook state machines and stage transitions."""

    def __init__(
        self,
        templates: list[PlaybookTemplate] | None = None,
        config: PlaybookEngineConfig | None = None,
    ) -> None:
        self.config = config or PlaybookEngineConfig()
        self._templates: dict[str, PlaybookTemplate] = {
            t.playbook_id: t for t in (templates or BUILTIN_PLAYBOOKS)
        }
        # In-memory store for fallback / testing
        self._runs: dict[str, PlaybookRun] = {}

    def list_templates(self) -> list[PlaybookTemplate]:
        """Return all available statutory playbook templates."""
        return list(self._templates.values())

    def get_template(self, playbook_id: str) -> PlaybookTemplate | None:
        """Lookup a playbook template by ID."""
        return self._templates.get(playbook_id)

    def start_run(
        self,
        playbook_id: str,
        tenant_id: str = "default",
        assigned_lead: str = "Compliance Team",
        conn: Any = None,
    ) -> PlaybookRun:
        """Instantiate a new playbook execution run for a tenant."""
        template = self.get_template(playbook_id)
        if not template:
            raise PlaybookNotFoundError(f"Unknown playbook_id '{playbook_id}'.")

        if not assigned_lead or not assigned_lead.strip():
            raise ValueError("assigned_lead must be non-empty")

        run_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        initial_stage_data: dict[str, Any] = {
            "completed_milestones": [],
            "stage_history": [
                {
                    "stage_number": 1,
                    "entered_at": now.isoformat(),
                    "status": "ACTIVE",
                }
            ],
        }

        run = PlaybookRun(
            run_id=run_id,
            tenant_id=tenant_id,
            playbook_id=playbook_id,
            title=template.title,
            assigned_lead=assigned_lead.strip(),
            current_stage=1,
            total_stages=template.total_stages,
            status="ACTIVE",
            stage_data=initial_stage_data,
            created_at=now,
            updated_at=now,
        )

        # Persist to database if connection provided
        if conn is not None:
            try:
                conn.execute(
                    """
                    INSERT INTO playbook_runs (
                        run_id, tenant_id, playbook_id, assigned_lead,
                        current_stage, status, stage_data, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        run.run_id,
                        run.tenant_id,
                        run.playbook_id,
                        run.assigned_lead,
                        run.current_stage,
                        run.status,
                        json.dumps(run.stage_data),
                        run.created_at,
                        run.updated_at,
                    ),
                )
            except Exception as err:
                logger.debug("playbook.db_sync_error", error=str(err))

        self._runs[run_id] = run
        return run

    start_playbook = start_run

    def get_run(
        self,
        run_id: str,
        tenant_id: str = "default",
        conn: Any = None,
    ) -> PlaybookRun | None:
        """Fetch a playbook run by run_id and tenant_id."""
        if conn is not None:
            try:
                row = conn.execute(
                    """
                    SELECT run_id, tenant_id, playbook_id, assigned_lead,
                           current_stage, status, stage_data, created_at, updated_at
                    FROM playbook_runs
                    WHERE run_id = %s AND tenant_id = %s
                    """,
                    (run_id, tenant_id),
                ).fetchone()
                if row:
                    template = self.get_template(row[2])
                    title = template.title if template else row[2]
                    raw_data = row[6]
                    stage_data = (
                        json.loads(raw_data) if isinstance(raw_data, str) else (raw_data or {})
                    )
                    return PlaybookRun(
                        run_id=str(row[0]),
                        tenant_id=str(row[1]),
                        playbook_id=str(row[2]),
                        title=title,
                        assigned_lead=str(row[3]),
                        current_stage=int(row[4]),
                        total_stages=template.total_stages if template else 4,
                        status=cast(RunStatus, str(row[5])),
                        stage_data=stage_data,
                        created_at=row[7],
                        updated_at=row[8],
                    )
            except Exception as err:
                logger.debug("playbook.db_sync_error", error=str(err))

        run = self._runs.get(run_id)
        if run and run.tenant_id == tenant_id:
            return run
        return None

    def complete_milestone(
        self,
        run_id: str,
        milestone_id: str,
        tenant_id: str = "default",
        stage_number: int | None = None,
        evidence_doc_id: str | None = None,
        notes: str | None = None,
        conn: Any = None,
    ) -> PlaybookRun:
        """Mark a milestone as completed in the active stage of a run."""
        run = self.get_run(run_id, tenant_id, conn)
        if not run:
            raise PlaybookRunNotFoundError(f"Run '{run_id}' not found for tenant '{tenant_id}'.")

        if run.status != "ACTIVE":
            raise InvalidStateTransitionError(
                f"Cannot complete milestone on run with status '{run.status}'."
            )

        effective_stage = stage_number if stage_number is not None else run.current_stage
        if effective_stage != run.current_stage:
            raise InvalidStateTransitionError(
                f"Cannot complete milestone for stage {effective_stage}; current active stage is {run.current_stage}."
            )

        completed: list[dict[str, Any]] = run.stage_data.get("completed_milestones", [])
        # Check if already completed
        if not any(
            m.get("milestone_id") == milestone_id and m.get("stage_number") == effective_stage
            for m in completed
        ):
            completed.append(
                {
                    "milestone_id": milestone_id,
                    "stage_number": effective_stage,
                    "completed_at": datetime.now(UTC).isoformat(),
                    "evidence_doc_id": evidence_doc_id,
                    "notes": notes or "",
                }
            )

        run.stage_data["completed_milestones"] = completed
        run.updated_at = datetime.now(UTC)

        if conn is not None:
            try:
                conn.execute(
                    """
                    UPDATE playbook_runs
                    SET stage_data = %s, updated_at = %s
                    WHERE run_id = %s AND tenant_id = %s
                    """,
                    (json.dumps(run.stage_data), run.updated_at, run.run_id, run.tenant_id),
                )
            except Exception as err:
                logger.debug("playbook.db_sync_error", error=str(err))

        self._runs[run.run_id] = run
        return run

    def advance_stage(
        self,
        run_id: str,
        tenant_id: str = "default",
        target_stage: int | None = None,
        conn: Any = None,
    ) -> PlaybookRun:
        """Advance a playbook run to the next stage or mark as completed."""
        run = self.get_run(run_id, tenant_id, conn)
        if not run:
            raise PlaybookRunNotFoundError(f"Run '{run_id}' not found for tenant '{tenant_id}'.")

        if run.status == "COMPLETED":
            raise InvalidStateTransitionError("Playbook run is already COMPLETED.")
        if run.status == "BLOCKED":
            raise InvalidStateTransitionError(
                "Playbook run is BLOCKED; resolve blockers before advancing."
            )

        next_stage = target_stage if target_stage is not None else run.current_stage + 1

        if not self.config.allow_stage_skipping:
            if next_stage != run.current_stage + 1:
                raise InvalidStateTransitionError(
                    f"Invalid stage skip from {run.current_stage} to {next_stage}. Sequential progression required."
                )

        if self.config.auto_verify_exit_criteria:
            template = self.get_template(run.playbook_id)
            if template:
                current_stage_def = next(
                    (s for s in template.stages if s.stage_number == run.current_stage), None
                )
                if current_stage_def and current_stage_def.milestones:
                    completed_ids = {
                        m.get("milestone_id")
                        for m in run.stage_data.get("completed_milestones", [])
                        if m.get("stage_number") == run.current_stage
                    }
                    required_ids = {m.id for m in current_stage_def.milestones}
                    if not required_ids.issubset(completed_ids):
                        raise InvalidStateTransitionError(
                            f"Exit criteria for Stage {run.current_stage} not yet satisfied."
                        )

        now = datetime.now(UTC)
        stage_history: list[dict[str, Any]] = run.stage_data.get("stage_history", [])

        # Mark current stage as completed in history
        for entry in stage_history:
            if entry.get("stage_number") == run.current_stage and entry.get("status") == "ACTIVE":
                entry["status"] = "COMPLETED"
                entry["exited_at"] = now.isoformat()

        if next_stage > run.total_stages:
            # All stages completed
            run.current_stage = run.total_stages
            run.status = "COMPLETED"
        else:
            run.current_stage = next_stage
            stage_history.append(
                {
                    "stage_number": next_stage,
                    "entered_at": now.isoformat(),
                    "status": "ACTIVE",
                }
            )

        run.stage_data["stage_history"] = stage_history
        run.updated_at = now

        if conn is not None:
            try:
                conn.execute(
                    """
                    UPDATE playbook_runs
                    SET current_stage = %s, status = %s, stage_data = %s, updated_at = %s
                    WHERE run_id = %s AND tenant_id = %s
                    """,
                    (
                        run.current_stage,
                        run.status,
                        json.dumps(run.stage_data),
                        run.updated_at,
                        run.run_id,
                        run.tenant_id,
                    ),
                )
            except Exception as err:
                logger.debug("playbook.db_sync_error", error=str(err))

        self._runs[run.run_id] = run
        return run

    def list_runs(
        self,
        tenant_id: str = "default",
        status: RunStatus | None = None,
        conn: Any = None,
    ) -> list[PlaybookRun]:
        """List all active or past playbook runs for a tenant."""
        if conn is not None:
            try:
                if status:
                    rows = conn.execute(
                        """
                        SELECT run_id, tenant_id, playbook_id, assigned_lead,
                               current_stage, status, stage_data, created_at, updated_at
                        FROM playbook_runs
                        WHERE tenant_id = %s AND status = %s
                        ORDER BY created_at DESC
                        """,
                        (tenant_id, status),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT run_id, tenant_id, playbook_id, assigned_lead,
                               current_stage, status, stage_data, created_at, updated_at
                        FROM playbook_runs
                        WHERE tenant_id = %s
                        ORDER BY created_at DESC
                        """,
                        (tenant_id,),
                    ).fetchall()

                runs: list[PlaybookRun] = []
                for row in rows:
                    template = self.get_template(row[2])
                    title = template.title if template else row[2]
                    raw_data = row[6]
                    stage_data = (
                        json.loads(raw_data) if isinstance(raw_data, str) else (raw_data or {})
                    )
                    runs.append(
                        PlaybookRun(
                            run_id=str(row[0]),
                            tenant_id=str(row[1]),
                            playbook_id=str(row[2]),
                            title=title,
                            assigned_lead=str(row[3]),
                            current_stage=int(row[4]),
                            total_stages=template.total_stages if template else 4,
                            status=cast(RunStatus, str(row[5])),
                            stage_data=stage_data,
                            created_at=row[7],
                            updated_at=row[8],
                        )
                    )
                return runs
            except Exception as err:
                logger.debug("playbook.db_sync_error", error=str(err))

        result = [r for r in self._runs.values() if r.tenant_id == tenant_id]
        if status:
            result = [r for r in result if r.status == status]
        return sorted(result, key=lambda x: x.created_at, reverse=True)


_DEFAULT_PLAYBOOK_ENGINE: PlaybookEngine | None = None


def get_default_playbook_engine() -> PlaybookEngine:
    """Return the singleton instance of PlaybookEngine."""
    global _DEFAULT_PLAYBOOK_ENGINE
    if _DEFAULT_PLAYBOOK_ENGINE is None:
        _DEFAULT_PLAYBOOK_ENGINE = PlaybookEngine()
    return _DEFAULT_PLAYBOOK_ENGINE
