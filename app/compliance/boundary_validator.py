"""Statutory Threshold & Boundary Validator (FEAT-023).

Rule engine that checks reported or computed financial and operational ratios
against statutory floors and ceilings (e.g. CRAR >= 15% for NBFC-SI, LCR >= 100%,
Net NPA <= 6.0% under PCA, Leverage Ratio >= 3.5%, SCI <= 50 gCO2eq/kWh).
Generates instant COMPLIANT (Green), WARNING (Amber), and BREACH (Red) findings
with precise circular citations and prescriptive remediation guidance.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

import structlog

from app.api.models import (
    RatioFinding,
    RatioValidationResponse,
    StatutoryBoundaryDefinition,
)

logger = structlog.get_logger("docscout.compliance.boundary_validator")


class BoundaryValidatorError(Exception):
    """Base exception for statutory boundary validation."""


class UnknownRatioError(BoundaryValidatorError):
    """Raised when an uncataloged ratio or metric name is submitted."""

    def __init__(self, ratio_name: str, available: list[str]) -> None:
        self.ratio_name = ratio_name
        self.available = available
        super().__init__(
            f"Unrecognized regulatory ratio or metric '{ratio_name}'. "
            f"Available ratios include: {', '.join(sorted(available)[:10])}..."
        )


@dataclass(frozen=True)
class StatutoryBoundaryRule:
    """Canonical statutory boundary definition."""

    rule_id: str
    ratio_name: str
    description: str
    regulator: str
    statutory_citation: str
    operator: Literal[">=", "<=", ">", "<"]
    threshold_value: float
    unit: str
    default_tolerance_pct: float
    category: str
    applicable_entities: list[str]
    guidance_on_breach: str
    aliases: list[str]


# ---------------------------------------------------------------------------
# Canonical Catalog of 38 Statutory Boundary Rules
# ---------------------------------------------------------------------------

_CANONICAL_RULES: list[StatutoryBoundaryRule] = [
    # --- Capital Adequacy (RBI & Basel III) ---
    StatutoryBoundaryRule(
        rule_id="CRAR_NBFC_SI",
        ratio_name="Capital to Risk-Weighted Assets Ratio (NBFC-SI)",
        description="Minimum statutory capital adequacy ratio for Systemically Important Non-Deposit taking NBFCs",
        regulator="RBI",
        statutory_citation="RBI Master Direction - Non-Banking Financial Company - Systemically Important Non-Deposit taking Company and Deposit taking Company (Reserve Bank) Directions, 2016 (DNBR.PD.008/03.10.119/2016-17)",
        operator=">=",
        threshold_value=15.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="capital_adequacy",
        applicable_entities=["nbfc_si", "nbfc", "nbfc_nd_si", "nbfc_d"],
        guidance_on_breach="Immediate capital augmentation or RWA reduction required. Minimum Tier 1 capital must also remain >= 10.0%.",
        aliases=["crar", "car", "crar_nbfc", "crar_nbfc_si", "capital_adequacy_ratio"],
    ),
    StatutoryBoundaryRule(
        rule_id="TIER1_CAPITAL_NBFC_SI",
        ratio_name="Tier 1 Capital Ratio (NBFC-SI)",
        description="Minimum Tier 1 capital ratio for Systemically Important NBFCs",
        regulator="RBI",
        statutory_citation="RBI Master Direction - NBFC-ND-SI (2016) Section 16",
        operator=">=",
        threshold_value=10.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="capital_adequacy",
        applicable_entities=["nbfc_si", "nbfc", "nbfc_nd_si", "nbfc_d"],
        guidance_on_breach="Tier 1 capital deficit. Prohibit dividend declaration and evaluate rights issue or equity infusion.",
        aliases=["tier1", "tier_1", "tier1_capital", "tier1_capital_nbfc", "tier1_ratio"],
    ),
    StatutoryBoundaryRule(
        rule_id="CRAR_COMMERCIAL_BANK",
        ratio_name="Minimum Total Capital (CRAR) - Commercial Banks",
        description="Minimum regulatory capital ratio for Scheduled Commercial Banks (excluding CCB)",
        regulator="RBI",
        statutory_citation="RBI Master Circular - Basel III Capital Regulations (RBI/2015-16/58)",
        operator=">=",
        threshold_value=9.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="capital_adequacy",
        applicable_entities=["commercial_bank", "scb", "bank", "general"],
        guidance_on_breach="Capital adequacy breach triggers immediate prompt corrective action (PCA) supervision and capital plan submission.",
        aliases=["crar", "car", "crar_bank", "crar_commercial_bank", "capital_adequacy_ratio"],
    ),
    StatutoryBoundaryRule(
        rule_id="CRAR_COMMERCIAL_BANK_WITH_CCB",
        ratio_name="Total Capital with Capital Conservation Buffer (CRAR + CCB)",
        description="Minimum total capital including fully phased-in 2.5% Capital Conservation Buffer for SCBs",
        regulator="RBI",
        statutory_citation="RBI Master Circular - Basel III Capital Regulations Section 4.3",
        operator=">=",
        threshold_value=11.5,
        unit="percent",
        default_tolerance_pct=0.05,
        category="capital_adequacy",
        applicable_entities=["commercial_bank", "scb", "bank"],
        guidance_on_breach="Capital conservation buffer breached. Distribution constraints applied on dividends, share buybacks, and discretionary bonuses.",
        aliases=["crar_ccb", "crar_with_ccb", "total_capital_ccb"],
    ),
    StatutoryBoundaryRule(
        rule_id="CET1_COMMERCIAL_BANK",
        ratio_name="Common Equity Tier 1 (CET1) Ratio",
        description="Minimum core equity capital for Scheduled Commercial Banks",
        regulator="RBI",
        statutory_citation="RBI Master Circular - Basel III Capital Regulations Paragraph 4.2",
        operator=">=",
        threshold_value=5.5,
        unit="percent",
        default_tolerance_pct=0.05,
        category="capital_adequacy",
        applicable_entities=["commercial_bank", "scb", "bank", "general"],
        guidance_on_breach="Severe regulatory breach. Subordinated debt cannot offset CET1 deficit. Immediate common equity infusion mandated.",
        aliases=["cet1", "cet_1", "cet1_ratio", "common_equity_tier_1"],
    ),
    StatutoryBoundaryRule(
        rule_id="CET1_COMMERCIAL_BANK_WITH_CCB",
        ratio_name="CET1 with Capital Conservation Buffer",
        description="Minimum CET1 ratio including 2.5% CCB for Commercial Banks",
        regulator="RBI",
        statutory_citation="RBI Master Circular - Basel III Capital Regulations Paragraph 4.3",
        operator=">=",
        threshold_value=8.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="capital_adequacy",
        applicable_entities=["commercial_bank", "scb", "bank"],
        guidance_on_breach="Earnings retention restrictions triggered under Basel III capital conservation framework.",
        aliases=["cet1_ccb", "cet1_with_ccb"],
    ),
    StatutoryBoundaryRule(
        rule_id="TIER1_COMMERCIAL_BANK",
        ratio_name="Tier 1 Capital Ratio - Commercial Banks",
        description="Minimum Tier 1 capital ratio for Scheduled Commercial Banks",
        regulator="RBI",
        statutory_citation="RBI Master Circular - Basel III Capital Regulations Paragraph 4.2",
        operator=">=",
        threshold_value=7.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="capital_adequacy",
        applicable_entities=["commercial_bank", "scb", "bank", "general"],
        guidance_on_breach="Additional Tier 1 (AT1) coupon cancellation mandatory if capital requirements are not met.",
        aliases=["tier1", "tier_1", "tier1_bank", "tier1_capital"],
    ),
    StatutoryBoundaryRule(
        rule_id="CAPITAL_CONSERVATION_BUFFER",
        ratio_name="Capital Conservation Buffer (CCB)",
        description="Mandatory common equity buffer above minimum capital requirements",
        regulator="RBI",
        statutory_citation="RBI Master Circular - Basel III Capital Regulations Annexure 4",
        operator=">=",
        threshold_value=2.5,
        unit="percent",
        default_tolerance_pct=0.05,
        category="capital_adequacy",
        applicable_entities=["commercial_bank", "scb", "bank"],
        guidance_on_breach="Distribution constraints apply proportionately to the depth of CCB shortfall.",
        aliases=["ccb", "capital_conservation_buffer"],
    ),
    StatutoryBoundaryRule(
        rule_id="CRAR_SMALL_FINANCE_BANK",
        ratio_name="Capital Adequacy Ratio (CRAR) - Small Finance Banks",
        description="Minimum capital adequacy ratio for Small Finance Banks",
        regulator="RBI",
        statutory_citation="RBI Guidelines for Licensing of Small Finance Banks in the Private Sector Section 4(b)",
        operator=">=",
        threshold_value=15.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="capital_adequacy",
        applicable_entities=["small_finance_bank", "sfb"],
        guidance_on_breach="Small Finance Bank capital shortfall. Review unhedged exposure and loan growth velocity.",
        aliases=["crar", "car", "crar_sfb", "capital_adequacy_sfb"],
    ),
    StatutoryBoundaryRule(
        rule_id="TIER1_SMALL_FINANCE_BANK",
        ratio_name="Tier 1 Capital Ratio - Small Finance Banks",
        description="Minimum Tier 1 capital ratio for Small Finance Banks",
        regulator="RBI",
        statutory_citation="RBI Guidelines for Licensing of Small Finance Banks Section 4(b)",
        operator=">=",
        threshold_value=7.5,
        unit="percent",
        default_tolerance_pct=0.05,
        category="capital_adequacy",
        applicable_entities=["small_finance_bank", "sfb"],
        guidance_on_breach="Tier 1 capital deficit in SFB. Capital call to promoter group required.",
        aliases=["tier1", "tier1_sfb"],
    ),
    StatutoryBoundaryRule(
        rule_id="CRAR_PAYMENT_BANK",
        ratio_name="Capital Adequacy Ratio (CRAR) - Payments Banks",
        description="Minimum capital adequacy ratio for Payments Banks",
        regulator="RBI",
        statutory_citation="RBI Guidelines for Licensing of Payments Banks Section 4(b)",
        operator=">=",
        threshold_value=15.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="capital_adequacy",
        applicable_entities=["payment_bank", "payments_bank", "pb"],
        guidance_on_breach="Capital breach in Payments Bank. Rebalance treasury portfolio into zero-risk sovereign G-Secs.",
        aliases=["crar", "car", "crar_pb", "crar_payment_bank"],
    ),
    StatutoryBoundaryRule(
        rule_id="CRAR_UCB_TIER1_2",
        ratio_name="CRAR - Urban Co-operative Banks (Tier 1 & 2)",
        description="Minimum capital ratio for Tier 1 and Tier 2 Urban Co-operative Banks",
        regulator="RBI",
        statutory_citation="RBI Master Circular - Capital Adequacy - Urban Cooperative Banks (RBI/2022-23/149)",
        operator=">=",
        threshold_value=9.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="capital_adequacy",
        applicable_entities=["ucb", "cooperative_bank", "urban_coop_bank"],
        guidance_on_breach="Issue long-term subordinated deposits or redeemable preference shares to restore CRAR.",
        aliases=["crar_ucb", "crar_ucb_tier1_2"],
    ),
    StatutoryBoundaryRule(
        rule_id="CRAR_UCB_TIER3_4",
        ratio_name="CRAR - Urban Co-operative Banks (Tier 3 & 4)",
        description="Minimum capital ratio for Tier 3 and Tier 4 Urban Co-operative Banks under Revised Framework",
        regulator="RBI",
        statutory_citation="RBI Revised Regulatory Framework for UCBs (DOR.CRE.REC.No.87/07.12.001/2022-23)",
        operator=">=",
        threshold_value=12.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="capital_adequacy",
        applicable_entities=["ucb", "cooperative_bank", "urban_coop_bank"],
        guidance_on_breach="Supervisory Action Framework (SAF) triggered if CRAR falls below 12.0%.",
        aliases=["crar_ucb_tier3_4", "crar_ucb_high"],
    ),
    # --- Liquidity & Reserve Requirements ---
    StatutoryBoundaryRule(
        rule_id="LCR_COMMERCIAL_BANK",
        ratio_name="Liquidity Coverage Ratio (LCR) - Commercial Banks",
        description="Minimum ratio of High Quality Liquid Assets (HQLA) to total net cash outflows over 30 days",
        regulator="RBI",
        statutory_citation="RBI Master Direction - Basel III Framework on Liquidity Standards - Liquidity Coverage Ratio (RBI/2014-15/529)",
        operator=">=",
        threshold_value=100.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="liquidity",
        applicable_entities=["commercial_bank", "scb", "bank", "general"],
        guidance_on_breach="Severe short-term liquidity deficit. Utilize Marginal Standing Facility (MSF) or Facility to Avail Liquidity for Liquidity Coverage Ratio (FALLCR).",
        aliases=["lcr", "lcr_bank", "liquidity_coverage_ratio"],
    ),
    StatutoryBoundaryRule(
        rule_id="LCR_NBFC_SI",
        ratio_name="Liquidity Coverage Ratio (LCR) - NBFC-SI",
        description="Minimum LCR for Systemically Important NBFCs with asset size >= INR 5,000 Crore",
        regulator="RBI",
        statutory_citation="RBI Liquidity Risk Management Framework for Non-Banking Financial Companies (RBI/2019-20/88)",
        operator=">=",
        threshold_value=100.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="liquidity",
        applicable_entities=["nbfc_si", "nbfc", "nbfc_nd_si", "nbfc_d"],
        guidance_on_breach="Draw on committed credit lines and liquidate Level 1 HQLA (government securities) immediately.",
        aliases=["lcr", "lcr_nbfc", "lcr_nbfc_si", "liquidity_coverage_ratio"],
    ),
    StatutoryBoundaryRule(
        rule_id="NSFR",
        ratio_name="Net Stable Funding Ratio (NSFR)",
        description="Minimum ratio of Available Stable Funding (ASF) to Required Stable Funding (RSF) over 1 year",
        regulator="RBI",
        statutory_citation="RBI Master Direction - Basel III Framework on Liquidity Standards - Net Stable Funding Ratio (RBI/2018-19/81)",
        operator=">=",
        threshold_value=100.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="liquidity",
        applicable_entities=["commercial_bank", "scb", "bank", "general"],
        guidance_on_breach="Structural asset-liability mismatch. Extend liability maturities and curtail long-tenor illiquid asset underwriting.",
        aliases=["nsfr", "net_stable_funding_ratio"],
    ),
    StatutoryBoundaryRule(
        rule_id="CRR",
        ratio_name="Cash Reserve Ratio (CRR)",
        description="Statutory minimum cash reserves maintained with RBI as percentage of NDTL",
        regulator="RBI",
        statutory_citation="Section 42 of Reserve Bank of India Act, 1934",
        operator=">=",
        threshold_value=4.5,
        unit="percent",
        default_tolerance_pct=0.05,
        category="liquidity",
        applicable_entities=["commercial_bank", "scb", "bank", "general"],
        guidance_on_breach="Penal interest charged by RBI at Bank Rate + 3% (or +5% for recurring default) on CRR shortfall.",
        aliases=["crr", "cash_reserve_ratio"],
    ),
    StatutoryBoundaryRule(
        rule_id="SLR",
        ratio_name="Statutory Liquidity Ratio (SLR)",
        description="Statutory minimum unencumbered approved securities maintained as percentage of NDTL",
        regulator="RBI",
        statutory_citation="Section 24 of Banking Regulation Act, 1949",
        operator=">=",
        threshold_value=18.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="liquidity",
        applicable_entities=["commercial_bank", "scb", "bank", "general"],
        guidance_on_breach="Penal interest charged by RBI on SLR deficit. Prohibit borrowing from call money market until rectified.",
        aliases=["slr", "statutory_liquidity_ratio"],
    ),
    StatutoryBoundaryRule(
        rule_id="CALL_BORROWING_LIMIT_BANK",
        ratio_name="Call/Notice Money Borrowing Ceiling",
        description="Prudential limit on daily borrowing in call/notice money market as percentage of capital funds",
        regulator="RBI",
        statutory_citation="RBI Master Direction - Money Market Instruments: Call/Notice Money Market (RBI/FMD/2016-17/33)",
        operator="<=",
        threshold_value=100.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="liquidity",
        applicable_entities=["commercial_bank", "scb", "bank"],
        guidance_on_breach="Excessive reliance on volatile overnight funding. Diversify into term repos and CD issuances.",
        aliases=["call_borrowing", "call_money_limit"],
    ),
    # --- Leverage & Exposure Limits ---
    StatutoryBoundaryRule(
        rule_id="LEVERAGE_RATIO_COMMERCIAL_BANK",
        ratio_name="Basel III Leverage Ratio - Commercial Banks",
        description="Minimum Tier 1 capital relative to total consolidated exposure",
        regulator="RBI",
        statutory_citation="RBI Basel III Leverage Ratio Framework (RBI/2018-19/84)",
        operator=">=",
        threshold_value=3.5,
        unit="percent",
        default_tolerance_pct=0.05,
        category="leverage",
        applicable_entities=["commercial_bank", "scb", "bank", "general"],
        guidance_on_breach="Non-risk-based backstop breach. De-leverage balance sheet and curtail off-balance sheet exposure.",
        aliases=["leverage", "leverage_ratio", "leverage_ratio_bank"],
    ),
    StatutoryBoundaryRule(
        rule_id="LEVERAGE_RATIO_DSIB",
        ratio_name="Leverage Ratio - Domestic Systemically Important Banks (D-SIBs)",
        description="Enhanced minimum leverage ratio for Domestic Systemically Important Banks",
        regulator="RBI",
        statutory_citation="RBI Basel III Leverage Ratio Framework Paragraph 3.1",
        operator=">=",
        threshold_value=4.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="leverage",
        applicable_entities=["commercial_bank", "scb", "bank", "dsib"],
        guidance_on_breach="D-SIB leverage ratio shortfall. Board-level capital restoration plan required within 30 days.",
        aliases=["leverage_ratio_dsib", "dsib_leverage"],
    ),
    StatutoryBoundaryRule(
        rule_id="LEVERAGE_RATIO_NBFC",
        ratio_name="Leverage Ratio / Gearing Ceiling - NBFC",
        description="Maximum debt-to-equity leverage multiplier for Non-Banking Financial Companies",
        regulator="RBI",
        statutory_citation="RBI Scale Based Regulation (SBR): A Revised Regulatory Framework for NBFCs (DOR.CRE.REC.No.60/03.10.001/2021-22)",
        operator="<=",
        threshold_value=7.0,
        unit="ratio",
        default_tolerance_pct=0.05,
        category="leverage",
        applicable_entities=["nbfc_si", "nbfc", "nbfc_nd_si", "nbfc_d"],
        guidance_on_breach="Excessive balance sheet gearing. Subordinate new debt issuances to equity capital expansion.",
        aliases=["leverage_nbfc", "nbfc_gearing", "debt_equity_nbfc"],
    ),
    StatutoryBoundaryRule(
        rule_id="LARGE_EXPOSURE_SINGLE_COUNTERPARTY",
        ratio_name="Large Exposure Framework - Single Counterparty Limit",
        description="Maximum exposure to a single counterparty as percentage of eligible Tier 1 capital base",
        regulator="RBI",
        statutory_citation="RBI Master Direction - Large Exposures Framework (LEF) (RBI/2018-19/196)",
        operator="<=",
        threshold_value=20.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="leverage",
        applicable_entities=["commercial_bank", "scb", "bank", "general"],
        guidance_on_breach="Concentration risk violation. Down-sell or syndicate loan portion immediately.",
        aliases=["large_exposure_single", "single_borrower_limit", "lef_single"],
    ),
    StatutoryBoundaryRule(
        rule_id="LARGE_EXPOSURE_CONNECTED_GROUP",
        ratio_name="Large Exposure Framework - Connected Group Limit",
        description="Maximum exposure to a group of connected clients as percentage of Tier 1 capital",
        regulator="RBI",
        statutory_citation="RBI Master Direction - Large Exposures Framework Paragraph 7.2",
        operator="<=",
        threshold_value=25.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="leverage",
        applicable_entities=["commercial_bank", "scb", "bank", "general"],
        guidance_on_breach="Group borrower concentration limit breached. Halt additional credit facilities to the corporate group.",
        aliases=["large_exposure_group", "group_borrower_limit", "lef_group"],
    ),
    # --- Asset Quality, Provisions & Prompt Corrective Action (PCA) ---
    StatutoryBoundaryRule(
        rule_id="PROVISION_COVERAGE_RATIO",
        ratio_name="Provision Coverage Ratio (PCR)",
        description="Minimum benchmark ratio of provisioning to gross non-performing assets",
        regulator="RBI",
        statutory_citation="RBI Guidelines on Provisioning Coverage for Scheduled Commercial Banks (RBI/2009-10/240)",
        operator=">=",
        threshold_value=70.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="asset_quality",
        applicable_entities=["commercial_bank", "scb", "bank", "general"],
        guidance_on_breach="Inadequate provisioning cushion against credit losses. Increase specific provisioning allocations.",
        aliases=["pcr", "provision_coverage_ratio", "pcr_ratio"],
    ),
    StatutoryBoundaryRule(
        rule_id="NET_NPA_PCA_THRESHOLD_1",
        ratio_name="Net NPA Ratio - PCA Risk Threshold 1",
        description="First risk threshold for Net Non-Performing Assets under Prompt Corrective Action framework",
        regulator="RBI",
        statutory_citation="RBI Prompt Corrective Action (PCA) Framework for Scheduled Commercial Banks (RBI/2021-22/120)",
        operator="<=",
        threshold_value=6.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="asset_quality",
        applicable_entities=["commercial_bank", "scb", "bank", "general"],
        guidance_on_breach="PCA Threshold 1 triggered: Restrictions on dividend distribution and remittance of profits. Mandatory loan recovery plan.",
        aliases=["net_npa", "nnpa", "net_npa_ratio", "pca_net_npa_1"],
    ),
    StatutoryBoundaryRule(
        rule_id="NET_NPA_PCA_THRESHOLD_2",
        ratio_name="Net NPA Ratio - PCA Risk Threshold 2",
        description="Second risk threshold for Net Non-Performing Assets under PCA framework",
        regulator="RBI",
        statutory_citation="RBI Prompt Corrective Action (PCA) Framework (2021) Table 1",
        operator="<=",
        threshold_value=9.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="asset_quality",
        applicable_entities=["commercial_bank", "scb", "bank"],
        guidance_on_breach="PCA Threshold 2 triggered: Complete restriction on branch expansion and mandatory capital restoration order.",
        aliases=["net_npa_pca_2", "pca_threshold_2"],
    ),
    StatutoryBoundaryRule(
        rule_id="NET_NPA_PCA_THRESHOLD_3",
        ratio_name="Net NPA Ratio - PCA Risk Threshold 3 (Critical)",
        description="Third risk threshold for Net Non-Performing Assets under PCA framework",
        regulator="RBI",
        statutory_citation="RBI Prompt Corrective Action (PCA) Framework (2021) Table 1",
        operator="<=",
        threshold_value=12.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="asset_quality",
        applicable_entities=["commercial_bank", "scb", "bank"],
        guidance_on_breach="Critical PCA Threshold 3: Complete lending restrictions and potential governance supersession by RBI.",
        aliases=["net_npa_pca_3", "pca_threshold_3"],
    ),
    StatutoryBoundaryRule(
        rule_id="SMA2_MAX_OVERDUE_DAYS",
        ratio_name="Special Mention Account (SMA-2) Maximum Overdue Window",
        description="Maximum overdue days before mandatory classification as Non-Performing Asset",
        regulator="RBI",
        statutory_citation="RBI Prudential Framework for Resolution of Stressed Assets (RBI/2018-19/203)",
        operator="<=",
        threshold_value=90.0,
        unit="days",
        default_tolerance_pct=0.05,
        category="asset_quality",
        applicable_entities=["commercial_bank", "scb", "bank", "nbfc_si", "general"],
        guidance_on_breach="Loan past 90 days overdue. Mandatory downgrade to Substandard Asset and 15% minimum provisioning.",
        aliases=["sma2_days", "npa_overdue_days", "overdue_days"],
    ),
    # --- Priority Sector Lending (PSL) ---
    StatutoryBoundaryRule(
        rule_id="PRIORITY_SECTOR_LENDING_DOMESTIC_BANK",
        ratio_name="Priority Sector Lending (PSL) Target - Domestic Banks",
        description="Mandatory priority sector lending target as percentage of Adjusted Net Bank Credit (ANBC)",
        regulator="RBI",
        statutory_citation="RBI Master Directions - Priority Sector Lending (PSL) - Targets and Classification (RBI/FIDD/2020-21/72)",
        operator=">=",
        threshold_value=40.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="priority_sector",
        applicable_entities=["commercial_bank", "scb", "bank", "general"],
        guidance_on_breach="PSL shortfall penal contribution mandated to Rural Infrastructure Development Fund (RIDF) at below-market rates.",
        aliases=["psl", "psl_target", "psl_bank", "priority_sector_lending"],
    ),
    StatutoryBoundaryRule(
        rule_id="PRIORITY_SECTOR_LENDING_SFB",
        ratio_name="Priority Sector Lending Target - Small Finance Banks",
        description="Mandatory priority sector lending target for Small Finance Banks",
        regulator="RBI",
        statutory_citation="RBI Master Directions - Priority Sector Lending for Small Finance Banks Paragraph 6.2",
        operator=">=",
        threshold_value=75.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="priority_sector",
        applicable_entities=["small_finance_bank", "sfb"],
        guidance_on_breach="SFB PSL target shortfall. Mandatory purchase of Priority Sector Lending Certificates (PSLCs).",
        aliases=["psl_sfb", "psl"],
    ),
    StatutoryBoundaryRule(
        rule_id="PSL_AGRICULTURE_SUBTARGET",
        ratio_name="PSL Sub-Target - Agriculture",
        description="Mandatory agriculture credit allocation as percentage of ANBC",
        regulator="RBI",
        statutory_citation="RBI Master Directions - Priority Sector Lending Section 4.1",
        operator=">=",
        threshold_value=18.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="priority_sector",
        applicable_entities=["commercial_bank", "scb", "bank", "general"],
        guidance_on_breach="Agriculture sub-target shortfall. Invest in Small Farmers Agri-Business Consortium or NABARD funds.",
        aliases=["psl_agriculture", "psl_agri"],
    ),
    StatutoryBoundaryRule(
        rule_id="PSL_SMALL_MARGINAL_FARMERS",
        ratio_name="PSL Sub-Target - Small and Marginal Farmers",
        description="Mandatory credit allocation for Small and Marginal Farmers as percentage of ANBC",
        regulator="RBI",
        statutory_citation="RBI Master Directions - Priority Sector Lending Section 4.1(ii)",
        operator=">=",
        threshold_value=10.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="priority_sector",
        applicable_entities=["commercial_bank", "scb", "bank", "general"],
        guidance_on_breach="Sub-target shortfall. Acquire PSLC Small & Marginal Farmer certificates.",
        aliases=["psl_smf", "psl_small_marginal_farmers"],
    ),
    StatutoryBoundaryRule(
        rule_id="PSL_WEAKER_SECTIONS",
        ratio_name="PSL Sub-Target - Advances to Weaker Sections",
        description="Mandatory credit allocation to Weaker Sections as percentage of ANBC",
        regulator="RBI",
        statutory_citation="RBI Master Directions - Priority Sector Lending Section 4.3",
        operator=">=",
        threshold_value=12.0,
        unit="percent",
        default_tolerance_pct=0.05,
        category="priority_sector",
        applicable_entities=["commercial_bank", "scb", "bank", "general"],
        guidance_on_breach="Weaker sections lending shortfall. Targeted disbursement programs required.",
        aliases=["psl_weaker_sections", "psl_weaker"],
    ),
    # --- Operational, SRE & Software Sustainability Standards ---
    StatutoryBoundaryRule(
        rule_id="SOFTWARE_CARBON_INTENSITY",
        ratio_name="Software Carbon Intensity (SCI) Regulatory Cap",
        description="Maximum carbon intensity rate per functional unit under green software standards",
        regulator="GSF",
        statutory_citation="ISO/IEC 21031:2024 Information technology  -  Software Carbon Intensity (SCI) specification",
        operator="<=",
        threshold_value=50.0,
        unit="gCO2eq/functional unit",
        default_tolerance_pct=0.05,
        category="sustainability",
        applicable_entities=["fintech", "cloud_provider", "enterprise", "general"],
        guidance_on_breach="Software carbon budget exceeded. Implement carbon-aware demand shifting and embodied hardware amortization.",
        aliases=["sci", "software_carbon_intensity", "sci_score"],
    ),
    StatutoryBoundaryRule(
        rule_id="ERROR_BUDGET_BURN_RATE_1H",
        ratio_name="SRE 1-Hour Fast Burn Rate Ceiling",
        description="Maximum tolerable error budget consumption velocity over a 1-hour rolling window",
        regulator="ISO",
        statutory_citation="SRE Multiwindow Multi-Burn-Rate 1-Hour Fast Burn Standard (Google SRE Book Ch. 5)",
        operator="<=",
        threshold_value=14.4,
        unit="burn multiplier",
        default_tolerance_pct=0.05,
        category="reliability",
        applicable_entities=["fintech", "core_banking", "api_gateway", "general"],
        guidance_on_breach="Critical reliability emergency: Consuming 2% of monthly budget in 1 hour. Pager alerts triggered and code freezes enforced.",
        aliases=["burn_rate_1h", "fast_burn_rate", "burn_rate"],
    ),
    StatutoryBoundaryRule(
        rule_id="ERROR_BUDGET_BURN_RATE_24H",
        ratio_name="SRE 24-Hour Steady State Burn Rate Ceiling",
        description="Maximum sustainable error budget consumption velocity over 24-hour window",
        regulator="ISO",
        statutory_citation="SRE Operational Reliability Policy (Google SRE Book Ch. 5)",
        operator="<=",
        threshold_value=1.0,
        unit="burn multiplier",
        default_tolerance_pct=0.05,
        category="reliability",
        applicable_entities=["fintech", "core_banking", "api_gateway", "general"],
        guidance_on_breach="Error budget depleted faster than renewal rate. Divert sprint capacity to resilience engineering.",
        aliases=["burn_rate_24h", "slow_burn_rate", "daily_burn_rate"],
    ),
    StatutoryBoundaryRule(
        rule_id="MC_DC_COVERAGE",
        ratio_name="Modified Condition/Decision Coverage (MC/DC)",
        description="Mandatory structural verification coverage for safety-critical aviation and automotive software",
        regulator="FAA",
        statutory_citation="DO-178C Software Considerations in Airborne Systems and Equipment Certification Table A-7 (Level A)",
        operator=">=",
        threshold_value=100.0,
        unit="percent",
        default_tolerance_pct=0.0,
        category="reliability",
        applicable_entities=["safety_critical", "aerospace", "automotive", "general"],
        guidance_on_breach="DO-178C Level A / ISO 26262 ASIL D non-compliance. Incomplete condition independence verification prevents flight/road clearance.",
        aliases=["mcdc", "mc_dc", "mcdc_coverage"],
    ),
]


class StatutoryBoundaryValidator:
    """Evaluation engine for statutory and systems regulatory thresholds."""

    def __init__(self, rules: list[StatutoryBoundaryRule] | None = None) -> None:
        self._rules = rules or _CANONICAL_RULES
        self._rules_by_id: dict[str, StatutoryBoundaryRule] = {
            r.rule_id.upper(): r for r in self._rules
        }

    @property
    def total_rules(self) -> int:
        """Total number of registered statutory rules."""
        return len(self._rules)

    def get_rule_by_id(self, rule_id: str) -> StatutoryBoundaryRule | None:
        """Find a rule by its canonical uppercase ID."""
        return self._rules_by_id.get(rule_id.strip().upper())

    def resolve_rule(
        self,
        ratio_name: str,
        entity_type: str = "commercial_bank",
    ) -> StatutoryBoundaryRule:
        """Resolve a ratio string and entity class into a canonical statutory rule.

        Matches rule ID first, then entity-specific aliases, then general aliases.
        """
        normalized_name = ratio_name.strip().upper()
        if normalized_name in self._rules_by_id:
            return self._rules_by_id[normalized_name]

        norm_clean = ratio_name.strip().lower().replace("-", "_").replace(" ", "_")
        norm_entity = entity_type.strip().lower().replace("-", "_").replace(" ", "_")

        # 1. Exact entity match (excluding generic fallback)
        for rule in self._rules:
            entities = [e.lower() for e in rule.applicable_entities if e.lower() != "general"]
            if norm_entity in entities or any(
                norm_entity.startswith(e) or e.startswith(norm_entity) for e in entities
            ):
                if (
                    norm_clean in [a.lower() for a in rule.aliases]
                    or norm_clean == rule.rule_id.lower()
                ):
                    return rule

        # 2. Rules applicable to 'general'
        for rule in self._rules:
            if "general" in [e.lower() for e in rule.applicable_entities]:
                if (
                    norm_clean in [a.lower() for a in rule.aliases]
                    or norm_clean == rule.rule_id.lower()
                ):
                    return rule

        # 3. Fallback to any rule with matching alias
        for rule in self._rules:
            if (
                norm_clean in [a.lower() for a in rule.aliases]
                or norm_clean == rule.rule_id.lower()
            ):
                return rule

        # Not found - raise UnknownRatioError with suggestions
        available = [r.rule_id for r in self._rules] + [a for r in self._rules for a in r.aliases]
        raise UnknownRatioError(ratio_name=ratio_name, available=available)

    def validate_ratio(
        self,
        ratio_name: str,
        value: float,
        entity_type: str = "commercial_bank",
        tolerance_percentage: float = 0.05,
    ) -> RatioFinding:
        """Validate a single reported ratio value against its statutory threshold.

        Evaluates floors (>=, >) and ceilings (<=, <).
        Computes distance margin and tolerance buffer to identify:
        - BREACH: Violates the threshold
        - WARNING: Compliant, but within tolerance_percentage of the threshold
        - COMPLIANT: Compliant and outside the tolerance buffer
        """
        rule = self.resolve_rule(ratio_name, entity_type=entity_type)
        threshold = rule.threshold_value
        op = rule.operator

        status: Literal["COMPLIANT", "WARNING", "BREACH"]
        margin: float
        margin_pct: float

        if op in (">=", ">"):
            margin = value - threshold
            margin_pct = (margin / threshold) * 100.0 if threshold != 0 else 0.0
            warn_cutoff = round(threshold * (1.0 + tolerance_percentage), 6)

            if (op == ">=" and value < threshold) or (op == ">" and value <= threshold):
                status = "BREACH"
            elif round(value, 6) < warn_cutoff:
                status = "WARNING"
            else:
                status = "COMPLIANT"

        elif op in ("<=", "<"):
            margin = threshold - value
            margin_pct = (margin / threshold) * 100.0 if threshold != 0 else 0.0
            warn_cutoff = round(threshold * (1.0 - tolerance_percentage), 6)

            if (op == "<=" and value > threshold) or (op == "<" and value >= threshold):
                status = "BREACH"
            elif round(value, 6) > warn_cutoff:
                status = "WARNING"
            else:
                status = "COMPLIANT"
        else:
            raise ValueError(f"Unsupported operator '{op}' in rule '{rule.rule_id}'")

        statutory_display = f"{op} {threshold:.2f} {rule.unit}"

        return RatioFinding(
            ratio_name=rule.ratio_name,
            reported_value=round(value, 4),
            statutory_threshold=statutory_display,
            status=status,
            circular_citation=rule.statutory_citation,
            margin=round(margin, 4),
            margin_percentage=round(margin_pct, 2),
            operator=rule.operator,
            threshold_value=threshold,
            unit=rule.unit,
            guidance=rule.guidance_on_breach,
            regulator=rule.regulator,
            category=rule.category,
        )

    def validate_ratios(
        self,
        ratios: dict[str, float],
        entity_type: str = "commercial_bank",
        tolerance_percentage: float = 0.05,
    ) -> RatioValidationResponse:
        """Validate a collection of ratios against statutory boundaries in batch.

        Aggregates individual findings into overall status and summary metrics.
        Latency is recorded in milliseconds.
        """
        start_ts = time.perf_counter()
        findings: list[RatioFinding] = []

        compliant_count = 0
        warning_count = 0
        breach_count = 0

        for name, val in ratios.items():
            finding = self.validate_ratio(
                ratio_name=name,
                value=float(val),
                entity_type=entity_type,
                tolerance_percentage=tolerance_percentage,
            )
            findings.append(finding)

            if finding.status == "BREACH":
                breach_count += 1
            elif finding.status == "WARNING":
                warning_count += 1
            else:
                compliant_count += 1

        if breach_count > 0:
            overall_status: Literal["COMPLIANT", "WARNING", "BREACH"] = "BREACH"
        elif warning_count > 0:
            overall_status = "WARNING"
        else:
            overall_status = "COMPLIANT"

        latency_ms = (time.perf_counter() - start_ts) * 1000.0

        return RatioValidationResponse(
            overall_status=overall_status,
            entity_type=entity_type,
            tolerance_percentage=tolerance_percentage,
            summary={
                "total": len(findings),
                "compliant": compliant_count,
                "warning": warning_count,
                "breach": breach_count,
            },
            findings=findings,
            latency_ms=round(latency_ms, 3),
        )

    def list_boundaries(
        self,
        regulator: str | None = None,
        category: str | None = None,
        entity_type: str | None = None,
    ) -> list[StatutoryBoundaryDefinition]:
        """List all registered statutory boundary definitions with optional filters."""
        results: list[StatutoryBoundaryDefinition] = []

        for r in self._rules:
            if regulator and r.regulator.upper() != regulator.strip().upper():
                continue
            if category and r.category.lower() != category.strip().lower():
                continue
            if entity_type:
                norm_ent = entity_type.strip().lower().replace("-", "_").replace(" ", "_")
                if not (
                    "general" in r.applicable_entities
                    or norm_ent in r.applicable_entities
                    or any(
                        norm_ent.startswith(e) or e.startswith(norm_ent)
                        for e in r.applicable_entities
                    )
                ):
                    continue

            results.append(
                StatutoryBoundaryDefinition(
                    rule_id=r.rule_id,
                    ratio_name=r.ratio_name,
                    description=r.description,
                    regulator=r.regulator,
                    statutory_citation=r.statutory_citation,
                    operator=r.operator,
                    threshold_value=r.threshold_value,
                    unit=r.unit,
                    default_tolerance_pct=r.default_tolerance_pct,
                    category=r.category,
                    applicable_entities=r.applicable_entities,
                    guidance_on_breach=r.guidance_on_breach,
                )
            )
        return results


# Global singleton instance
_DEFAULT_BOUNDARY_VALIDATOR: StatutoryBoundaryValidator | None = None


def get_default_boundary_validator() -> StatutoryBoundaryValidator:
    """Return or lazily initialize the default singleton boundary validator."""
    global _DEFAULT_BOUNDARY_VALIDATOR
    if _DEFAULT_BOUNDARY_VALIDATOR is None:
        _DEFAULT_BOUNDARY_VALIDATOR = StatutoryBoundaryValidator()
    return _DEFAULT_BOUNDARY_VALIDATOR
