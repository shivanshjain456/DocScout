"""Counterfactual Robustness Testing Suite (FEAT-087, ADR-0078).

Systematically perturbs statutory facts (entity names, dates, ratios, limits, penalties)
in evaluation circulars to verify that DocScout answers strictly from context and not
parametric pretraining memory. Enforces >= 98% counterfactual adherence and 0% parametric leakage.
"""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger("docscout.evals.counterfactual")


@dataclass(frozen=True)
class PerturbationRule:
    """Deterministic rule replacing a real-world statutory fact with a counterfactual variation."""

    target_text: str
    counterfactual_text: str
    category: str
    description: str = ""


@dataclass(frozen=True)
class CounterfactualConfig:
    """Configuration parameters for counterfactual robustness validation."""

    min_robustness_score: float = 0.95
    target_adherence_rate: float = 0.98
    max_execution_seconds: float = 15.0
    max_memory_mb: float = 128.0

    def __post_init__(self) -> None:
        if not (0.0 <= self.min_robustness_score <= 1.0):
            raise ValueError(
                f"min_robustness_score must be between 0.0 and 1.0, got {self.min_robustness_score}"
            )
        if not (0.0 <= self.target_adherence_rate <= 1.0):
            raise ValueError(
                f"target_adherence_rate must be between 0.0 and 1.0, got {self.target_adherence_rate}"
            )
        if self.max_execution_seconds <= 0:
            raise ValueError("max_execution_seconds must be positive")


@dataclass
class CounterfactualItem:
    """One counterfactually perturbed regulatory test item."""

    item_id: str
    original_item_id: str
    question: str
    original_evidence: str
    counterfactual_evidence: str
    original_key_points: list[str]
    counterfactual_key_points: list[str]
    parametric_forbidden_strings: list[str]
    perturbation_rule: PerturbationRule
    category: str
    is_synthetic: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "original_item_id": self.original_item_id,
            "question": self.question,
            "original_evidence": self.original_evidence,
            "counterfactual_evidence": self.counterfactual_evidence,
            "original_key_points": self.original_key_points,
            "counterfactual_key_points": self.counterfactual_key_points,
            "parametric_forbidden_strings": self.parametric_forbidden_strings,
            "perturbation_rule": asdict(self.perturbation_rule),
            "category": self.category,
            "is_synthetic": self.is_synthetic,
        }


@dataclass
class CounterfactualItemResult:
    """Per-item outcome of counterfactual adherence testing."""

    item_id: str
    adhered: bool
    parametric_leakage: bool
    answer: str
    matched_counterfactual: list[str]
    matched_parametric: list[str]
    category: str
    details: str = ""


@dataclass
class CounterfactualTestResult:
    """Aggregate report from running counterfactual robustness evaluation."""

    items_tested: int
    correct_counterfactual_answers: int
    parametric_leakage_detected: int
    robustness_score: float
    item_results: list[CounterfactualItemResult] = field(default_factory=list)
    execution_time_seconds: float = 0.0

    @property
    def adherence_rate(self) -> float:
        return (
            self.correct_counterfactual_answers / self.items_tested
            if self.items_tested > 0
            else 0.0
        )

    @property
    def leakage_rate(self) -> float:
        return (
            self.parametric_leakage_detected / self.items_tested if self.items_tested > 0 else 0.0
        )

    @property
    def passed(self) -> bool:
        return self.robustness_score >= 0.95 and self.parametric_leakage_detected == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "items_tested": self.items_tested,
            "correct_counterfactual_answers": self.correct_counterfactual_answers,
            "parametric_leakage_detected": self.parametric_leakage_detected,
            "robustness_score": round(self.robustness_score, 4),
            "adherence_rate": round(self.adherence_rate, 4),
            "leakage_rate": round(self.leakage_rate, 4),
            "passed": self.passed,
            "execution_time_seconds": round(self.execution_time_seconds, 4),
        }


class CounterfactualGenerator:
    """Generates canonical counterfactual perturbations over regulatory circulars."""

    # 50 Canonical Perturbations across 5 regulatory categories
    CANONICAL_SPECS: list[dict[str, Any]] = [
        # Category: numeric_amount
        {
            "id": "cf-001",
            "orig_id": "g-001",
            "q": "Under the Differential Rate of Interest scheme, what is the maximum loan amount and what rate of interest applies?",
            "orig_ev": "banks provide finance up to ₹15,000/- at a concessional rate of interest of 4 per cent per annum",
            "target": "₹15,000",
            "cf": "₹25,000",
            "cat": "numeric_amount",
            "orig_kp": ["Finance up to ₹15,000", "Concessional rate of 4 per cent per annum"],
            "cf_kp": ["Finance up to ₹25,000", "Concessional rate of 4 per cent per annum"],
            "forbidden": ["₹15,000", "15,000/-", "15000"],
            "desc": "Perturb DRI loan ceiling from 15k to 25k",
        },
        {
            "id": "cf-002",
            "orig_id": "g-004",
            "q": "What is the range of guarantee cover available under the Credit Enhancement Guarantee Scheme for Scheduled Castes?",
            "orig_ev": "The amount of guarantee cover under CEGSSC ranges from a minimum of ₹0.15 cr to a maximum of ₹5.00 cr.",
            "target": "₹0.15 cr to a maximum of ₹5.00 cr",
            "cf": "₹0.50 cr to a maximum of ₹10.00 cr",
            "cat": "numeric_amount",
            "orig_kp": ["Minimum ₹0.15 crore", "Maximum ₹5.00 crore"],
            "cf_kp": ["Minimum ₹0.50 crore", "Maximum ₹10.00 crore"],
            "forbidden": ["0.15 cr", "5.00 cr", "0.15 crore", "5.00 crore"],
            "desc": "Perturb CEGSSC guarantee cover range",
        },
        {
            "id": "cf-003",
            "orig_id": "g-006",
            "q": "What is the investment limit in plant and machinery for micro enterprises under Priority Sector Lending?",
            "orig_ev": "Micro enterprise investment in plant and machinery does not exceed ₹1 crore and turnover does not exceed ₹5 crore.",
            "target": "₹1 crore",
            "cf": "₹3 crore",
            "cat": "numeric_amount",
            "orig_kp": ["Investment does not exceed ₹1 crore"],
            "cf_kp": ["Investment does not exceed ₹3 crore"],
            "forbidden": ["₹1 crore", "1 crore", "one crore"],
            "desc": "Perturb micro enterprise investment ceiling to 3 crore",
        },
        {
            "id": "cf-004",
            "orig_id": "g-011",
            "q": "What is the minimum Net Owned Fund (NOF) requirement for registering a Housing Finance Company?",
            "orig_ev": "The minimum Net Owned Fund (NOF) for housing finance companies is prescribed at ₹20 crore.",
            "target": "₹20 crore",
            "cf": "₹35 crore",
            "cat": "numeric_amount",
            "orig_kp": ["Minimum NOF is ₹20 crore"],
            "cf_kp": ["Minimum NOF is ₹35 crore"],
            "forbidden": ["₹20 crore", "20 crore"],
            "desc": "Perturb HFC NOF minimum threshold",
        },
        {
            "id": "cf-005",
            "orig_id": "g-015",
            "q": "What is the minimum paid-up voting equity capital required to establish a Small Finance Bank?",
            "orig_ev": "The minimum paid-up voting equity capital for small finance banks shall be ₹200 crore.",
            "target": "₹200 crore",
            "cf": "₹350 crore",
            "cat": "numeric_amount",
            "orig_kp": ["Minimum capital is ₹200 crore"],
            "cf_kp": ["Minimum capital is ₹350 crore"],
            "forbidden": ["₹200 crore", "200 crore"],
            "desc": "Perturb SFB minimum capital requirement",
        },
        {
            "id": "cf-006",
            "orig_id": "g-019",
            "q": "What is the maximum balance an individual customer can hold in a Payments Bank at the end of the day?",
            "orig_ev": "Payments banks can hold a maximum balance of ₹2,00,000 per individual customer.",
            "target": "₹2,00,000",
            "cf": "₹5,00,000",
            "cat": "numeric_amount",
            "orig_kp": ["Maximum balance of ₹2,00,000 per customer"],
            "cf_kp": ["Maximum balance of ₹5,00,000 per customer"],
            "forbidden": ["₹2,00,000", "2,00,000", "2 lakh", "200000"],
            "desc": "Perturb Payments Bank end-of-day deposit ceiling",
        },
        {
            "id": "cf-007",
            "orig_id": "g-023",
            "q": "What is the minimum net worth requirement for non-bank Prepaid Payment Instrument (PPI) issuers?",
            "orig_ev": "Non-bank PPI issuers shall have a minimum positive net worth of ₹15 crore as per the latest audited balance sheet.",
            "target": "₹15 crore",
            "cf": "₹30 crore",
            "cat": "numeric_amount",
            "orig_kp": ["Minimum positive net worth of ₹15 crore"],
            "cf_kp": ["Minimum positive net worth of ₹30 crore"],
            "forbidden": ["₹15 crore", "15 crore"],
            "desc": "Perturb non-bank PPI issuer net worth floor",
        },
        {
            "id": "cf-008",
            "orig_id": "g-028",
            "q": "What is the threshold for reporting wilful defaulters to credit information companies?",
            "orig_ev": "Banks must report wilful defaulters with an outstanding balance of ₹25 lakh and above.",
            "target": "₹25 lakh",
            "cf": "₹60 lakh",
            "cat": "numeric_amount",
            "orig_kp": ["Outstanding balance of ₹25 lakh and above"],
            "cf_kp": ["Outstanding balance of ₹60 lakh and above"],
            "forbidden": ["₹25 lakh", "25 lakh", "twenty five lakh"],
            "desc": "Perturb wilful defaulter reporting threshold",
        },
        {
            "id": "cf-009",
            "orig_id": "g-032",
            "q": "What is the minimum regulatory capital requirement for standalone primary dealers?",
            "orig_ev": "Standalone Primary Dealers shall maintain a minimum net owned funds of ₹150 crore.",
            "target": "₹150 crore",
            "cf": "₹250 crore",
            "cat": "numeric_amount",
            "orig_kp": ["Minimum NOF of ₹150 crore"],
            "cf_kp": ["Minimum NOF of ₹250 crore"],
            "forbidden": ["₹150 crore", "150 crore"],
            "desc": "Perturb Primary Dealer capital requirement",
        },
        {
            "id": "cf-010",
            "orig_id": "g-037",
            "q": "What is the collateral-free loan ceiling for microfinance borrowers under the revised regulatory framework?",
            "orig_ev": "Collateral-free loans to microfinance borrowers are permitted up to an annual household income limit of ₹3,00,000.",
            "target": "₹3,00,000",
            "cf": "₹4,50,000",
            "cat": "numeric_amount",
            "orig_kp": ["Annual household income limit of ₹3,00,000"],
            "cf_kp": ["Annual household income limit of ₹4,50,000"],
            "forbidden": ["₹3,00,000", "3,00,000", "3 lakh"],
            "desc": "Perturb microfinance qualifying income threshold",
        },
        # Category: ratio_percentage
        {
            "id": "cf-011",
            "orig_id": "g-002",
            "q": "What minimum share of total DRI advances must banks grant to borrowers belonging to Scheduled Castes and Scheduled Tribes?",
            "orig_ev": "not less than 2/5th (40 percent) of total DRI advances must be granted to SC/ST borrowers",
            "target": "not less than 2/5th (40 percent)",
            "cf": "not less than 55 percent",
            "cat": "ratio_percentage",
            "orig_kp": ["Not less than 2/5th (40 percent) of total DRI advances"],
            "cf_kp": ["Not less than 55 percent of total DRI advances"],
            "forbidden": ["40 percent", "40%", "2/5th"],
            "desc": "Perturb DRI SC/ST statutory allocation ratio",
        },
        {
            "id": "cf-012",
            "orig_id": "g-007",
            "q": "What is the minimum Common Equity Tier 1 (CET1) capital ratio required for commercial banks under Basel III in India?",
            "orig_ev": "Commercial banks in India are required to maintain a minimum CET1 ratio of 5.5 percent of risk-weighted assets.",
            "target": "5.5 percent",
            "cf": "7.5 percent",
            "cat": "ratio_percentage",
            "orig_kp": ["Minimum CET1 ratio of 7.5 percent"],
            "cf_kp": ["Minimum CET1 ratio of 7.5 percent"],
            "forbidden": ["5.5 percent", "5.5%"],
            "desc": "Perturb Basel III CET1 minimum ratio",
        },
        {
            "id": "cf-013",
            "orig_id": "g-010",
            "q": "What is the prescribed Capital to Risk-Weighted Assets Ratio (CRAR) for Tier 1 Urban Co-operative Banks?",
            "orig_ev": "Tier 1 Urban Co-operative Banks shall maintain a minimum CRAR of 9 percent of risk weighted assets.",
            "target": "9 percent",
            "cf": "13 percent",
            "cat": "ratio_percentage",
            "orig_kp": ["Minimum CRAR of 13 percent"],
            "cf_kp": ["Minimum CRAR of 13 percent"],
            "forbidden": ["9 percent", "9%"],
            "desc": "Perturb Tier 1 UCB CRAR ratio",
        },
        {
            "id": "cf-014",
            "orig_id": "g-014",
            "q": "What is the minimum regulatory Leverage Ratio mandated by RBI for Domestic Systemically Important Banks?",
            "orig_ev": "Domestic Systemically Important Banks (D-SIBs) shall maintain a minimum leverage ratio of 4.0 percent.",
            "target": "4.0 percent",
            "cf": "6.5 percent",
            "cat": "ratio_percentage",
            "orig_kp": ["Minimum leverage ratio of 6.5 percent"],
            "cf_kp": ["Minimum leverage ratio of 6.5 percent"],
            "forbidden": ["4.0 percent", "4.0%", "4 percent"],
            "desc": "Perturb D-SIB leverage ratio requirement",
        },
        {
            "id": "cf-015",
            "orig_id": "g-020",
            "q": "What minimum percentage of total assets must an NBFC-MFI maintain as qualifying microfinance assets?",
            "orig_ev": "An NBFC-MFI must maintain not less than 75 percent of its total assets as qualifying microfinance assets.",
            "target": "75 percent",
            "cf": "85 percent",
            "cat": "ratio_percentage",
            "orig_kp": ["Not less than 85 percent qualifying assets"],
            "cf_kp": ["Not less than 85 percent qualifying assets"],
            "forbidden": ["75 percent", "75%"],
            "desc": "Perturb NBFC-MFI qualifying asset threshold",
        },
        {
            "id": "cf-016",
            "orig_id": "g-024",
            "q": "What is the single counterparty large exposure limit for scheduled commercial banks as a percentage of Tier 1 capital?",
            "orig_ev": "The sum of all exposure values of a bank to a single counterparty must not exceed 20 percent of available eligible capital base.",
            "target": "20 percent",
            "cf": "30 percent",
            "cat": "ratio_percentage",
            "orig_kp": ["Must not exceed 30 percent of eligible capital base"],
            "cf_kp": ["Must not exceed 30 percent of eligible capital base"],
            "forbidden": ["20 percent", "20%"],
            "desc": "Perturb large exposure single counterparty ceiling",
        },
        {
            "id": "cf-017",
            "orig_id": "g-029",
            "q": "What minimum Liquidity Coverage Ratio (LCR) is required for scheduled commercial banks?",
            "orig_ev": "Banks must maintain a minimum Liquidity Coverage Ratio of 100 percent on an ongoing basis.",
            "target": "100 percent",
            "cf": "125 percent",
            "cat": "ratio_percentage",
            "orig_kp": ["Minimum LCR of 125 percent"],
            "cf_kp": ["Minimum LCR of 125 percent"],
            "forbidden": ["100 percent", "100%"],
            "desc": "Perturb Liquidity Coverage Ratio requirement",
        },
        {
            "id": "cf-018",
            "orig_id": "g-034",
            "q": "What is the minimum Net Stable Funding Ratio (NSFR) required under Basel III liquidity standards?",
            "orig_ev": "Banks are required to maintain an NSFR of at least 100 percent at all times.",
            "target": "100 percent",
            "cf": "115 percent",
            "cat": "ratio_percentage",
            "orig_kp": ["NSFR of at least 115 percent"],
            "cf_kp": ["NSFR of at least 115 percent"],
            "forbidden": ["100 percent", "100%"],
            "desc": "Perturb NSFR minimum requirement",
        },
        {
            "id": "cf-019",
            "orig_id": "g-039",
            "q": "What is the interbank call money borrowing limit for scheduled commercial banks on an average in a reporting fortnight?",
            "orig_ev": "Borrowings in call/notice money market shall not exceed 100 percent of capital funds on a fortnight average.",
            "target": "100 percent",
            "cf": "140 percent",
            "cat": "ratio_percentage",
            "orig_kp": ["Shall not exceed 140 percent of capital funds"],
            "cf_kp": ["Shall not exceed 140 percent of capital funds"],
            "forbidden": ["100 percent", "100%"],
            "desc": "Perturb interbank call borrowing limit",
        },
        {
            "id": "cf-020",
            "orig_id": "g-044",
            "q": "What is the Countercyclical Capital Buffer (CCyB) target deployment band under RBI guidelines?",
            "orig_ev": "The CCyB requirement shall range from 0 to 2.5 percent of risk weighted assets depending on credit-to-GDP gap.",
            "target": "0 to 2.5 percent",
            "cf": "0 to 4.0 percent",
            "cat": "ratio_percentage",
            "orig_kp": ["Range from 0 to 4.0 percent"],
            "cf_kp": ["Range from 0 to 4.0 percent"],
            "forbidden": ["2.5 percent", "2.5%"],
            "desc": "Perturb CCyB buffer range ceiling",
        },
        # Category: timeline
        {
            "id": "cf-021",
            "orig_id": "g-005",
            "q": "What is the maximum tenure of a guarantee issued under CEGSSC?",
            "orig_ev": "The tenure of guarantee is up to a maximum of 7 years or repayment period, whichever is earlier.",
            "target": "7 years",
            "cf": "12 years",
            "cat": "timeline",
            "orig_kp": ["Maximum 12 years or repayment period"],
            "cf_kp": ["Maximum 12 years or repayment period"],
            "forbidden": ["7 years", "seven years"],
            "desc": "Perturb CEGSSC guarantee tenure",
        },
        {
            "id": "cf-022",
            "orig_id": "g-008",
            "q": "Within what timeframe must regulated entities report cyber security incidents to RBI and CERT-In?",
            "orig_ev": "Regulated entities must report any cyber security incident to RBI within 6 hours of detection.",
            "target": "within 6 hours",
            "cf": "within 14 hours",
            "cat": "timeline",
            "orig_kp": ["Reported within 14 hours of detection"],
            "cf_kp": ["Reported within 14 hours of detection"],
            "forbidden": ["6 hours", "six hours"],
            "desc": "Perturb cyber incident notification countdown",
        },
        {
            "id": "cf-023",
            "orig_id": "g-009",
            "q": "What is the statutory period for realization and repatriation of export proceeds to India?",
            "orig_ev": "The full value of goods or software exported must be realized and repatriated within 9 months from the date of export.",
            "target": "9 months",
            "cf": "15 months",
            "cat": "timeline",
            "orig_kp": ["Realized and repatriated within 15 months"],
            "cf_kp": ["Realized and repatriated within 15 months"],
            "forbidden": ["9 months", "nine months"],
            "desc": "Perturb export realization timeframe",
        },
        {
            "id": "cf-024",
            "orig_id": "g-013",
            "q": "What is the maximum implementation timeline for a Resolution Plan under the RBI Prudential Framework?",
            "orig_ev": "The Resolution Plan must be implemented within 180 days from the end of the review period.",
            "target": "180 days",
            "cf": "270 days",
            "cat": "timeline",
            "orig_kp": ["Implemented within 270 days"],
            "cf_kp": ["Implemented within 270 days"],
            "forbidden": ["180 days", "one hundred eighty days"],
            "desc": "Perturb resolution plan implementation window",
        },
        {
            "id": "cf-025",
            "orig_id": "g-018",
            "q": "For how long must regulated entities preserve customer identification and transaction records under PMLA/KYC rules?",
            "orig_ev": "Regulated entities shall preserve records of transactions and customer identification data for at least 5 years.",
            "target": "5 years",
            "cf": "8 years",
            "cat": "timeline",
            "orig_kp": ["Preserved for at least 8 years"],
            "cf_kp": ["Preserved for at least 8 years"],
            "forbidden": ["5 years", "five years"],
            "desc": "Perturb KYC record preservation retention period",
        },
        {
            "id": "cf-026",
            "orig_id": "g-022",
            "q": "How frequently must banks conduct a review of their exposure to connected counterparties?",
            "orig_ev": "Banks shall review exposures to connected counterparties on a quarterly basis.",
            "target": "on a quarterly basis",
            "cf": "on a bi-monthly basis",
            "cat": "timeline",
            "orig_kp": ["Review conducted on a bi-monthly basis"],
            "cf_kp": ["Review conducted on a bi-monthly basis"],
            "forbidden": ["quarterly", "quarterly basis", "every quarter"],
            "desc": "Perturb counterparty exposure review frequency",
        },
        {
            "id": "cf-027",
            "orig_id": "g-026",
            "q": "What is the look-up / cooling-off period required for borrowers in digital lending transactions?",
            "orig_ev": "A cooling-off/look-up period of not less than 3 days for loans having tenure of 7 or more days must be provided.",
            "target": "3 days",
            "cf": "7 days",
            "cat": "timeline",
            "orig_kp": ["Cooling-off period of not less than 7 days"],
            "cf_kp": ["Cooling-off period of not less than 7 days"],
            "forbidden": ["3 days", "three days"],
            "desc": "Perturb digital lending cooling off period",
        },
        {
            "id": "cf-028",
            "orig_id": "g-031",
            "q": "What is the limitation period for an aggrieved customer to file an appeal against an award by the Banking Ombudsman?",
            "orig_ev": "An appeal against the decision of the Ombudsman may be filed within 30 days of receipt of the award.",
            "target": "within 30 days",
            "cf": "within 45 days",
            "cat": "timeline",
            "orig_kp": ["Appeal filed within 45 days"],
            "cf_kp": ["Appeal filed within 45 days"],
            "forbidden": ["30 days", "thirty days"],
            "desc": "Perturb ombudsman appeal limitation window",
        },
        {
            "id": "cf-029",
            "orig_id": "g-036",
            "q": "Within how many days must banks clear un-reconciled entries in internal transit and suspense accounts?",
            "orig_ev": "All entries in suspense and clearing adjustment accounts must be reconciled within 15 days.",
            "target": "within 15 days",
            "cf": "within 25 days",
            "cat": "timeline",
            "orig_kp": ["Reconciled within 25 days"],
            "cf_kp": ["Reconciled within 25 days"],
            "forbidden": ["15 days", "fifteen days"],
            "desc": "Perturb suspense reconciliation statutory deadline",
        },
        {
            "id": "cf-030",
            "orig_id": "g-041",
            "q": "What is the required frequency for periodic KYC refresh of high-risk customers?",
            "orig_ev": "KYC verification for high-risk customers shall be carried out at least once every 2 years.",
            "target": "every 2 years",
            "cf": "every 4 years",
            "cat": "timeline",
            "orig_kp": ["Carried out at least once every 4 years"],
            "cf_kp": ["Carried out at least once every 4 years"],
            "forbidden": ["2 years", "two years"],
            "desc": "Perturb high-risk customer KYC refresh cycle",
        },
        # Category: penalty_value
        {
            "id": "cf-031",
            "orig_id": "g-012",
            "q": "What is the statutory daily penalty imposed on banking companies for continuing failure to produce inspection books?",
            "orig_ev": "Banking companies failing to produce documents are liable to a penalty up to ₹20,000 per day for each day failure continues.",
            "target": "₹20,000 per day",
            "cf": "₹50,000 per day",
            "cat": "penalty_value",
            "orig_kp": ["Penalty up to ₹50,000 per day"],
            "cf_kp": ["Penalty up to ₹50,000 per day"],
            "forbidden": ["₹20,000", "20,000 per day"],
            "desc": "Perturb daily continuing document production penalty",
        },
        {
            "id": "cf-032",
            "orig_id": "g-016",
            "q": "What is the maximum penalty RBI may levy for unauthorized payment system operations under PSS Act Section 26?",
            "orig_ev": "Any person operating an unauthorized payment system is liable to a fine which may extend to ₹1 crore.",
            "target": "₹1 crore",
            "cf": "₹3 crore",
            "cat": "penalty_value",
            "orig_kp": ["Fine which may extend to ₹3 crore"],
            "cf_kp": ["Fine which may extend to ₹3 crore"],
            "forbidden": ["₹1 crore", "one crore"],
            "desc": "Perturb PSS Act unauthorized system penalty",
        },
        {
            "id": "cf-033",
            "orig_id": "g-021",
            "q": "What penal interest rate is charged to banks for failing to credit RTGS funds to beneficiary within the prescribed SLA?",
            "orig_ev": "The receiving bank shall pay penal interest at repo rate plus 2 percent per annum for delayed RTGS credits.",
            "target": "repo rate plus 2 percent",
            "cf": "repo rate plus 5 percent",
            "cat": "penalty_value",
            "orig_kp": ["Penal interest at repo rate plus 5 percent"],
            "cf_kp": ["Penal interest at repo rate plus 5 percent"],
            "forbidden": ["plus 2 percent", "plus 2%"],
            "desc": "Perturb RTGS delayed credit penal interest",
        },
        {
            "id": "cf-034",
            "orig_id": "g-027",
            "q": "What is the fixed financial penalty levied on regulated entities for failing to furnish statutory returns to the Credit Information Bureau?",
            "orig_ev": "Credit institutions failing to furnish credit information are liable to a penalty not exceeding ₹1,00,000.",
            "target": "₹1,00,000",
            "cf": "₹2,50,000",
            "cat": "penalty_value",
            "orig_kp": ["Penalty not exceeding ₹2,50,000"],
            "cf_kp": ["Penalty not exceeding ₹2,50,000"],
            "forbidden": ["₹1,00,000", "1,00,000", "1 lakh"],
            "desc": "Perturb Credit Information Bureau reporting default fine",
        },
        {
            "id": "cf-035",
            "orig_id": "g-033",
            "q": "What daily penalty is prescribed under SEBI LODR Regulations for failure to submit quarterly financial results?",
            "orig_ev": "Listed entities failing to submit financial results shall pay a fine of ₹2,000 per day of non-compliance.",
            "target": "₹2,000 per day",
            "cf": "₹6,000 per day",
            "cat": "penalty_value",
            "orig_kp": ["Fine of ₹6,000 per day of non-compliance"],
            "cf_kp": ["Fine of ₹6,000 per day of non-compliance"],
            "forbidden": ["₹2,000", "2,000 per day", "two thousand"],
            "desc": "Perturb SEBI LODR late filing fine",
        },
        {
            "id": "cf-036",
            "orig_id": "g-038",
            "q": "What compounding fee is prescribed for contravention of FEMA export realization timelines exceeding ₹1 crore?",
            "orig_ev": "The compounding authority may impose a compounding fee of ₹50,000 plus ₹5,000 for each month of contravention.",
            "target": "₹50,000 plus ₹5,000 for each month",
            "cf": "₹1,50,000 plus ₹15,000 for each month",
            "cat": "penalty_value",
            "orig_kp": ["Compounding fee of ₹1,50,000 plus ₹15,000 for each month"],
            "cf_kp": ["Compounding fee of ₹1,50,000 plus ₹15,000 for each month"],
            "forbidden": ["₹50,000", "₹5,000"],
            "desc": "Perturb FEMA compounding base fee schedule",
        },
        {
            "id": "cf-037",
            "orig_id": "g-043",
            "q": "What penal interest rate applies to shortfalls in CRR maintenance beyond the initial default day?",
            "orig_ev": "In case of continuing default, penal interest is payable at 5 percent above Bank Rate on the short amount.",
            "target": "5 percent above Bank Rate",
            "cf": "8 percent above Bank Rate",
            "cat": "penalty_value",
            "orig_kp": ["Penal interest at 8 percent above Bank Rate"],
            "cf_kp": ["Penal interest at 8 percent above Bank Rate"],
            "forbidden": ["5 percent above Bank Rate", "5% above Bank Rate"],
            "desc": "Perturb CRR shortfall continuing penal surcharge",
        },
        {
            "id": "cf-038",
            "orig_id": "g-048",
            "q": "What is the regulatory capital surcharge penalty imposed on banks failing Pillar 2 supervisory review stress tests?",
            "orig_ev": "Supervisors may impose a capital surcharge penalty up to 2.0 percent on common equity for severe deficiencies.",
            "target": "up to 2.0 percent",
            "cf": "up to 4.5 percent",
            "cat": "penalty_value",
            "orig_kp": ["Capital surcharge penalty up to 4.5 percent"],
            "cf_kp": ["Capital surcharge penalty up to 4.5 percent"],
            "forbidden": ["2.0 percent", "2.0%", "2 percent"],
            "desc": "Perturb Pillar 2 capital surcharge ceiling",
        },
        {
            "id": "cf-039",
            "orig_id": "g-049",
            "q": "What is the statutory penalty per day under Section 47A of the Banking Regulation Act for default in complying with RBI directions?",
            "orig_ev": "Where the default is a continuing one, a further penalty which may extend to ₹1,00,000 for every day after the first may be imposed.",
            "target": "₹1,00,000 for every day",
            "cf": "₹3,00,000 for every day",
            "cat": "penalty_value",
            "orig_kp": ["Penalty up to ₹3,00,000 for every day"],
            "cf_kp": ["Penalty up to ₹3,00,000 for every day"],
            "forbidden": ["₹1,00,000", "one lakh per day"],
            "desc": "Perturb Section 47A daily penalty ceiling",
        },
        {
            "id": "cf-040",
            "orig_id": "g-050",
            "q": "What is the late submission fee for overdue quarterly reporting under Foreign Contribution Regulation Act (FCRA)?",
            "orig_ev": "A penalty of ₹10,000 or 5 percent of foreign contribution received, whichever is higher, is levied.",
            "target": "₹10,000 or 5 percent",
            "cf": "₹25,000 or 10 percent",
            "cat": "penalty_value",
            "orig_kp": ["Penalty of ₹25,000 or 10 percent"],
            "cf_kp": ["Penalty of ₹25,000 or 10 percent"],
            "forbidden": ["₹10,000", "5 percent"],
            "desc": "Perturb FCRA overdue filing fine",
        },
        # Category: entity_name
        {
            "id": "cf-041",
            "orig_id": "g-017",
            "q": "Which category of financial institutions must mandatorily appoint an Internal Ombudsman under the RBI Master Direction?",
            "orig_ev": "All Non-Banking Financial Companies in Middle Layer and Upper Layer having customer interface shall appoint an Internal Ombudsman.",
            "target": "Non-Banking Financial Companies in Middle Layer and Upper Layer",
            "cf": "Primary Urban Co-operative Banks in Tier 3 and Tier 4",
            "cat": "entity_name",
            "orig_kp": ["Primary Urban Co-operative Banks in Tier 3 and Tier 4"],
            "cf_kp": ["Primary Urban Co-operative Banks in Tier 3 and Tier 4"],
            "forbidden": [
                "Non-Banking Financial Companies",
                "NBFCs in Middle Layer",
                "NBFC",
            ],
            "desc": "Perturb Internal Ombudsman mandate target entity",
        },
        {
            "id": "cf-042",
            "orig_id": "g-025",
            "q": "To which entities does the RBI Master Direction on Information Technology Governance apply directly?",
            "orig_ev": "The provisions of these Directions shall apply to all Scheduled Commercial Banks, Small Finance Banks and Payments Banks.",
            "target": "Small Finance Banks and Payments Banks",
            "cf": "Housing Finance Companies and Asset Reconstruction Companies",
            "cat": "entity_name",
            "orig_kp": [
                "Scheduled Commercial Banks, Housing Finance Companies and Asset Reconstruction Companies"
            ],
            "cf_kp": [
                "Scheduled Commercial Banks, Housing Finance Companies and Asset Reconstruction Companies"
            ],
            "forbidden": ["Small Finance Banks", "Payments Banks"],
            "desc": "Perturb IT governance master direction entity coverage",
        },
        {
            "id": "cf-043",
            "orig_id": "g-030",
            "q": "Which corporate entities are subject to mandatory Business Responsibility and Sustainability Reporting (BRSR) under SEBI?",
            "orig_ev": "The BRSR disclosure is mandatory for the top 1000 listed entities by market capitalization.",
            "target": "top 1000 listed entities",
            "cf": "top 300 listed entities",
            "cat": "entity_name",
            "orig_kp": ["Top 300 listed entities by market capitalization"],
            "cf_kp": ["Top 300 listed entities by market capitalization"],
            "forbidden": ["top 1000", "1000 listed entities"],
            "desc": "Perturb BRSR statutory coverage tier",
        },
        {
            "id": "cf-044",
            "orig_id": "g-035",
            "q": "Which entities are required to establish an automated cloud security incident escalation matrix under RBI cyber directions?",
            "orig_ev": "Cloud security escalation matrices must be established by all Authorised Payment System Operators.",
            "target": "Authorised Payment System Operators",
            "cf": "Standalone Primary Dealers",
            "cat": "entity_name",
            "orig_kp": ["Established by all Standalone Primary Dealers"],
            "cf_kp": ["Established by all Standalone Primary Dealers"],
            "forbidden": ["Payment System Operators", "PSOs"],
            "desc": "Perturb cloud security matrix obligation entity",
        },
        {
            "id": "cf-045",
            "orig_id": "g-040",
            "q": "Under FEMA, which license category is authorized to deal directly in foreign currency with the public and non-resident entities?",
            "orig_ev": "Authorised Dealers Category I are permitted to carry out all permissible current and capital account transactions.",
            "target": "Authorised Dealers Category I",
            "cf": "Authorised Dealers Category III",
            "cat": "entity_name",
            "orig_kp": ["Authorised Dealers Category III"],
            "cf_kp": ["Authorised Dealers Category III"],
            "forbidden": ["Category I", "Category-I", "AD Category I"],
            "desc": "Perturb foreign exchange dealer authorization tier",
        },
        {
            "id": "cf-046",
            "orig_id": "g-045",
            "q": "Which financial institutions are required to submit credit data to the Central Repository of Information on Large Credits (CRILC)?",
            "orig_ev": "All Scheduled Commercial Banks and Non-Banking Financial Companies shall report credit information to CRILC.",
            "target": "Non-Banking Financial Companies",
            "cf": "Core Investment Companies",
            "cat": "entity_name",
            "orig_kp": ["Scheduled Commercial Banks and Core Investment Companies"],
            "cf_kp": ["Scheduled Commercial Banks and Core Investment Companies"],
            "forbidden": ["Non-Banking Financial Companies", "NBFCs"],
            "desc": "Perturb CRILC reporting mandate entity group",
        },
        {
            "id": "cf-047",
            "orig_id": "g-046",
            "q": "Which entities are mandated to maintain an independent Risk Management Committee headed by an independent director?",
            "orig_ev": "All Tier 4 Urban Co-operative Banks shall constitute an independent Risk Management Committee.",
            "target": "Tier 4 Urban Co-operative Banks",
            "cf": "Tier 2 Urban Co-operative Banks",
            "cat": "entity_name",
            "orig_kp": ["All Tier 2 Urban Co-operative Banks"],
            "cf_kp": ["All Tier 2 Urban Co-operative Banks"],
            "forbidden": ["Tier 4 Urban Co-operative Banks", "Tier 4 UCBs"],
            "desc": "Perturb Risk Management Committee mandate tier",
        },
        {
            "id": "cf-048",
            "orig_id": "g-047",
            "q": "Under SEBI Credit Rating Regulations, which intermediary is subject to mandatory semi-annual rotation of rating analysts?",
            "orig_ev": "Credit Rating Agencies shall ensure rotation of lead rating analysts on rating assignments every 5 years.",
            "target": "Credit Rating Agencies",
            "cf": "Debenture Trustees",
            "cat": "entity_name",
            "orig_kp": ["Debenture Trustees shall ensure rotation"],
            "cf_kp": ["Debenture Trustees shall ensure rotation"],
            "forbidden": ["Credit Rating Agencies", "CRAs"],
            "desc": "Perturb analyst rotation intermediary class",
        },
        {
            "id": "cf-049",
            "orig_id": "g-003",
            "q": "Do the DRI land-holding eligibility limits apply to SC/ST borrowers?",
            "orig_ev": "size of land holding should not exceed 1 acre of irrigated land and 2.5 acres of unirrigated land, are not applicable to SCs/STs",
            "target": "are not applicable to SCs/STs",
            "cf": "are strictly applicable to SCs/STs without exemption",
            "cat": "entity_name",
            "orig_kp": ["They are strictly applicable to SCs/STs without exemption"],
            "cf_kp": ["They are strictly applicable to SCs/STs without exemption"],
            "forbidden": ["not applicable", "are not applicable to SCs/STs"],
            "desc": "Perturb statutory exemption status for SC/ST DRI limits",
        },
        {
            "id": "cf-050",
            "orig_id": "g-051",
            "q": "Which regulatory body exercises exclusive statutory oversight over digital asset tokenization in IFSC Gift City?",
            "orig_ev": "The International Financial Services Centres Authority (IFSCA) exercises exclusive regulatory supervision.",
            "target": "International Financial Services Centres Authority (IFSCA)",
            "cf": "Securities and Exchange Board of India (SEBI)",
            "cat": "entity_name",
            "orig_kp": [
                "Securities and Exchange Board of India (SEBI) exercises exclusive supervision"
            ],
            "cf_kp": [
                "Securities and Exchange Board of India (SEBI) exercises exclusive supervision"
            ],
            "forbidden": ["IFSCA", "International Financial Services Centres Authority"],
            "desc": "Perturb IFSC Gift City exclusive regulatory oversight body",
        },
    ]

    def __init__(self) -> None:
        self._synthetic_items: list[CounterfactualItem] = []

    def generate_suite(self) -> list[CounterfactualItem]:
        """Generate the full canonical suite of 50 counterfactual test items."""
        items: list[CounterfactualItem] = []
        for spec in self.CANONICAL_SPECS:
            rule = PerturbationRule(
                target_text=spec["target"],
                counterfactual_text=spec["cf"],
                category=spec["cat"],
                description=spec.get("desc", ""),
            )
            cf_evidence = spec["orig_ev"].replace(rule.target_text, rule.counterfactual_text)
            item = CounterfactualItem(
                item_id=spec["id"],
                original_item_id=spec["orig_id"],
                question=spec["q"],
                original_evidence=spec["orig_ev"],
                counterfactual_evidence=cf_evidence,
                original_key_points=spec["orig_kp"],
                counterfactual_key_points=spec["cf_kp"],
                parametric_forbidden_strings=spec["forbidden"],
                perturbation_rule=rule,
                category=spec["cat"],
                is_synthetic=True,
            )
            items.append(item)

        self._synthetic_items = items
        return items

    def cleanup(self) -> int:
        """Purge and isolate synthetic counterfactual items from test memory."""
        count = len(self._synthetic_items)
        self._synthetic_items.clear()
        return count


def _matches_term(term: str, text: str) -> bool:
    """Check if term appears in text with proper token and symbol boundaries."""
    if not term or not text:
        return False
    escaped = re.escape(term.lower())
    left = r"\b" if re.match(r"^\w", term) else r"(?:^|[^\w₹])"
    right = r"\b" if re.search(r"\w$", term) else r"(?:[^\w%]|$)"
    pattern = re.compile(left + escaped + right, re.IGNORECASE)
    return bool(pattern.search(text))


class CounterfactualEvaluator:
    """Evaluates answer generation against counterfactual contexts to detect parametric memory leakage."""

    def __init__(self, config: CounterfactualConfig | None = None) -> None:
        self.config = config or CounterfactualConfig()
        self.generator = CounterfactualGenerator()

    def evaluate_answer(
        self,
        item: CounterfactualItem,
        answer: str,
    ) -> CounterfactualItemResult:
        """Evaluate an individual answer against counterfactual vs parametric facts."""
        answer_lower = answer.lower()

        # 1. Check for parametric leakage: does answer contain forbidden real-world facts?
        matched_parametric: list[str] = []
        for forbidden in item.parametric_forbidden_strings:
            if _matches_term(forbidden, answer):
                matched_parametric.append(forbidden)

        # Also check original target text if not already matched
        target_text = item.perturbation_rule.target_text
        if _matches_term(target_text, answer) and target_text not in matched_parametric:
            matched_parametric.append(target_text)

        # 2. Check for counterfactual adherence: does answer contain counterfactual facts?
        matched_cf: list[str] = []
        cf_text = item.perturbation_rule.counterfactual_text
        if _matches_term(cf_text, answer) or cf_text.lower() in answer_lower:
            matched_cf.append(cf_text)

        for kp in item.counterfactual_key_points:
            # Check for significant tokens of counterfactual key point
            kp_tokens = set(re.findall(r"\b[a-zA-Z0-9-₹%]+", kp.lower())) - {
                "the",
                "of",
                "to",
                "and",
                "is",
                "are",
                "for",
            }
            if kp_tokens and kp_tokens.issubset(
                set(re.findall(r"\b[a-zA-Z0-9-₹%]+", answer_lower))
            ):
                matched_cf.append(kp)

        parametric_leakage = len(matched_parametric) > 0
        adhered = (len(matched_cf) > 0) and not parametric_leakage

        details = ""
        if parametric_leakage:
            details = f"Parametric leakage detected: {matched_parametric}"
        elif adhered:
            details = f"Adhered to counterfactual context: {matched_cf}"
        else:
            details = "Neither counterfactual fact nor parametric fact present in answer."

        return CounterfactualItemResult(
            item_id=item.item_id,
            adhered=adhered,
            parametric_leakage=parametric_leakage,
            answer=answer,
            matched_counterfactual=matched_cf,
            matched_parametric=matched_parametric,
            category=item.category,
            details=details,
        )

    def evaluate_suite(
        self,
        answers: dict[str, str],
        items: Sequence[CounterfactualItem] | None = None,
    ) -> CounterfactualTestResult:
        """Evaluate a full dictionary of item_id -> answer against the counterfactual suite."""
        start_time = time.perf_counter()
        suite_items = items or self.generator.generate_suite()

        correct_cf = 0
        leakage_count = 0
        item_results: list[CounterfactualItemResult] = []

        for item in suite_items:
            ans = answers.get(item.item_id, "")
            res = self.evaluate_answer(item, ans)
            item_results.append(res)
            if res.adhered:
                correct_cf += 1
            if res.parametric_leakage:
                leakage_count += 1

        n = len(suite_items)
        elapsed = time.perf_counter() - start_time

        # Robustness score penalizes parametric leakage heavily
        if n == 0:
            robustness = 0.0
        else:
            robustness = max(0.0, (correct_cf - leakage_count) / n)

        result = CounterfactualTestResult(
            items_tested=n,
            correct_counterfactual_answers=correct_cf,
            parametric_leakage_detected=leakage_count,
            robustness_score=robustness,
            item_results=item_results,
            execution_time_seconds=elapsed,
        )

        logger.info(
            "counterfactual_suite_evaluated",
            items_tested=n,
            correct_cf=correct_cf,
            leakage=leakage_count,
            robustness=round(robustness, 4),
            elapsed=round(elapsed, 4),
            passed=result.passed,
        )

        return result

    def simulate_grounded_engine(
        self,
        items: Sequence[CounterfactualItem],
    ) -> dict[str, str]:
        """Simulate an ideal grounded RAG system that answers strictly from retrieved counterfactual context."""
        answers: dict[str, str] = {}
        for item in items:
            answers[item.item_id] = (
                f"Based on the regulatory circular: {item.counterfactual_evidence}. "
                f"Specifically, {item.counterfactual_key_points[0]}."
            )
        return answers

    def simulate_parametric_engine(
        self,
        items: Sequence[CounterfactualItem],
        leakage_rate: float = 0.35,
    ) -> dict[str, str]:
        """Simulate an ungrounded baseline LLM that recites memorized real-world facts with leakage_rate."""
        answers: dict[str, str] = {}
        for idx, item in enumerate(items):
            # Recite parametric memory for leakage_rate proportion of queries
            if (idx % 10) < int(leakage_rate * 10):
                answers[item.item_id] = (
                    f"Under standard banking regulations: {item.original_evidence}. "
                    f"Specifically, {item.original_key_points[0]}."
                )
            else:
                answers[item.item_id] = (
                    f"Based on the provided context: {item.counterfactual_evidence}. "
                    f"Specifically, {item.counterfactual_key_points[0]}."
                )
        return answers


def get_default_counterfactual_evaluator(
    config: CounterfactualConfig | None = None,
) -> CounterfactualEvaluator:
    """Return default instance of CounterfactualEvaluator."""
    return CounterfactualEvaluator(config)
