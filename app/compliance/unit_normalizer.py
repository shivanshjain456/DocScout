"""Indian Financial Unit Normalizer (FEAT-028).

Converts vernacular and statutory quantitative expressions across Indian units
(Lakh, Crore, Thousand) and International units (Million, Billion, Trillion),
basis points (bps), and percentages into canonical ISO numeric floats and
bidirectional representations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger("docscout.compliance.unit_normalizer")

# Multipliers
CRORE_MULTIPLIER = 10_000_000.0
LAKH_MULTIPLIER = 100_000.0
THOUSAND_MULTIPLIER = 1_000.0
MILLION_MULTIPLIER = 1_000_000.0
BILLION_MULTIPLIER = 1_000_000_000.0
TRILLION_MULTIPLIER = 1_000_000_000_000.0
BPS_MULTIPLIER = 0.0001
PERCENT_MULTIPLIER = 0.01


class Currency(StrEnum):
    """Supported currency designations."""

    INR = "INR"
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    PERCENT = "PERCENT"
    BPS = "BPS"
    RATIO = "RATIO"
    UNKNOWN = "UNKNOWN"


@dataclass
class NormalizedFinancialValue:
    """Canonical representation of a parsed and scaled financial quantity."""

    raw_expression: str
    canonical_value: float
    canonical_unit: str
    currency_symbol: str | None
    scale_label: str
    scale_multiplier: float
    indian_words: str
    indian_numeric_formatted: str
    international_words: str
    international_numeric_formatted: str
    bps_equivalent: float | None = None
    percent_equivalent: float | None = None
    synonym_representations: list[str] = field(default_factory=list)
    is_valid: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_expression": self.raw_expression,
            "canonical_value": self.canonical_value,
            "canonical_unit": self.canonical_unit,
            "currency_symbol": self.currency_symbol,
            "scale_label": self.scale_label,
            "scale_multiplier": self.scale_multiplier,
            "indian_words": self.indian_words,
            "indian_numeric_formatted": self.indian_numeric_formatted,
            "international_words": self.international_words,
            "international_numeric_formatted": self.international_numeric_formatted,
            "bps_equivalent": self.bps_equivalent,
            "percent_equivalent": self.percent_equivalent,
            "synonym_representations": self.synonym_representations,
            "is_valid": self.is_valid,
        }


def format_indian_number(n: float | int) -> str:
    """Format numeric float or integer with Indian comma grouping (e.g. 12,34,56,789.00)."""
    is_neg = n < 0
    val = abs(n)
    s = f"{val:.2f}"
    int_part, dec_part = s.split(".")

    if len(int_part) <= 3:
        res = int_part
    else:
        last3 = int_part[-3:]
        remaining = int_part[:-3]
        parts: list[str] = []
        while remaining:
            parts.append(remaining[-2:])
            remaining = remaining[:-2]
        parts.reverse()
        res = ",".join(parts) + "," + last3

    formatted = f"{res}.{dec_part}" if dec_part != "00" else res
    return f"-{formatted}" if is_neg else formatted


def format_international_number(n: float | int) -> str:
    """Format numeric float or integer with Western comma grouping (e.g. 123,456,789.00)."""
    is_neg = n < 0
    val = abs(n)
    s = f"{val:,.2f}"
    if s.endswith(".00"):
        s = s[:-3]
    return f"-{s}" if is_neg else s


class IndianFinancialUnitNormalizer:
    """Parser and bidirectional transformer for Indian and global financial quantities."""

    _CURRENCY_PATTERNS = [
        (re.compile(r"(?:₹|rs\.?|inr|rupees?)", re.IGNORECASE), "INR", "₹"),
        (re.compile(r"(?:\$|usd|dollars?)", re.IGNORECASE), "USD", "$"),
        (re.compile(r"(?:€|eur|euros?)", re.IGNORECASE), "EUR", "€"),
        (re.compile(r"(?:£|gbp|pounds?)", re.IGNORECASE), "GBP", "£"),
    ]

    _SCALE_PATTERNS = [
        (
            re.compile(r"(?:\b(?:crores?|crs?|koti)\b|(?<=\d|\s)cr(?![a-zA-Z]))", re.IGNORECASE),
            "Crore",
            CRORE_MULTIPLIER,
        ),
        (
            re.compile(r"(?:\b(?:lakhs?|lacs?|lk)\b|(?<=\d|\s)l(?![a-zA-Z]))", re.IGNORECASE),
            "Lakh",
            LAKH_MULTIPLIER,
        ),
        (
            re.compile(r"(?:\b(?:trillions?|tn)\b|(?<=\d|\s)t(?![a-zA-Z]))", re.IGNORECASE),
            "Trillion",
            TRILLION_MULTIPLIER,
        ),
        (
            re.compile(r"(?:\b(?:billions?|bn)\b|(?<=\d|\s)b(?![a-zA-Z]))", re.IGNORECASE),
            "Billion",
            BILLION_MULTIPLIER,
        ),
        (
            re.compile(r"(?:\b(?:millions?|mn)\b|(?<=\d|\s)m(?![a-zA-Z]))", re.IGNORECASE),
            "Million",
            MILLION_MULTIPLIER,
        ),
        (
            re.compile(r"(?:\b(?:thousands?)\b|(?<=\d|\s)k(?![a-zA-Z]))", re.IGNORECASE),
            "Thousand",
            THOUSAND_MULTIPLIER,
        ),
        (re.compile(r"\b(?:bps|basis\s+points?|bp)\b", re.IGNORECASE), "bps", BPS_MULTIPLIER),
        (re.compile(r"(?:%|percent(?:age)?)", re.IGNORECASE), "%", PERCENT_MULTIPLIER),
    ]

    _NUMERIC_PATTERN = re.compile(r"[-+]?\d+(?:,\d+)*(?:\.\d+)?")

    def parse(self, text: str) -> NormalizedFinancialValue:
        """Parse arbitrary text containing a quantity, currency, and unit scale."""
        clean_text = text.strip()
        if not clean_text:
            return self._empty_result(clean_text)

        # 1. Identify Currency
        currency = Currency.UNKNOWN
        currency_sym: str | None = None
        for pat, curr_code, sym in self._CURRENCY_PATTERNS:
            if pat.search(clean_text):
                currency = Currency(curr_code)
                currency_sym = sym
                break

        # 2. Identify Scale
        scale_label = "unit"
        scale_mult = 1.0
        is_ratio_type = False

        for pat, label, mult in self._SCALE_PATTERNS:
            if pat.search(clean_text):
                scale_label = label
                scale_mult = mult
                if label in ("bps", "%"):
                    is_ratio_type = True
                break

        if is_ratio_type and currency == Currency.UNKNOWN:
            currency = Currency.BPS if scale_label == "bps" else Currency.PERCENT

        # 3. Extract Numeric Value
        num_match = self._NUMERIC_PATTERN.search(clean_text)
        if not num_match:
            return self._empty_result(clean_text)

        raw_num_str = num_match.group(0).replace(",", "")
        try:
            base_number = float(raw_num_str)
        except ValueError:
            return self._empty_result(clean_text)

        canonical_value = base_number * scale_mult

        # Set default currency symbol for INR if none detected and scale is Lakh/Crore
        if currency == Currency.UNKNOWN and scale_label in ("Crore", "Lakh"):
            currency = Currency.INR
            currency_sym = "₹"

        # 4. Format representations
        curr_prefix = f"{currency_sym} " if currency_sym else ""

        # Indian words
        if is_ratio_type:
            indian_words = (
                f"{canonical_value * 100:.2f}%"
                if scale_label == "%"
                else f"{canonical_value * 10000:.0f} bps"
            )
        elif abs(canonical_value) >= CRORE_MULTIPLIER:
            cr_val = canonical_value / CRORE_MULTIPLIER
            indian_words = (
                f"{curr_prefix}{cr_val:.2f} Crore".rstrip("0").rstrip(".")
                if cr_val % 1 == 0
                else f"{curr_prefix}{cr_val:.2f} Crore"
            )
        elif abs(canonical_value) >= LAKH_MULTIPLIER:
            lk_val = canonical_value / LAKH_MULTIPLIER
            indian_words = (
                f"{curr_prefix}{lk_val:.2f} Lakh".rstrip("0").rstrip(".")
                if lk_val % 1 == 0
                else f"{curr_prefix}{lk_val:.2f} Lakh"
            )
        elif abs(canonical_value) >= THOUSAND_MULTIPLIER:
            th_val = canonical_value / THOUSAND_MULTIPLIER
            indian_words = (
                f"{curr_prefix}{th_val:.2f} Thousand".rstrip("0").rstrip(".")
                if th_val % 1 == 0
                else f"{curr_prefix}{th_val:.2f} Thousand"
            )
        else:
            indian_words = f"{curr_prefix}{canonical_value:.2f}"

        # Indian numeric formatted
        indian_num = f"{curr_prefix}{format_indian_number(canonical_value)}"

        # International words
        if is_ratio_type:
            intl_words = indian_words
        elif abs(canonical_value) >= TRILLION_MULTIPLIER:
            tn_val = canonical_value / TRILLION_MULTIPLIER
            intl_words = f"{curr_prefix}{tn_val:.2f} Trillion"
        elif abs(canonical_value) >= BILLION_MULTIPLIER:
            bn_val = canonical_value / BILLION_MULTIPLIER
            intl_words = f"{curr_prefix}{bn_val:.2f} Billion"
        elif abs(canonical_value) >= MILLION_MULTIPLIER:
            mn_val = canonical_value / MILLION_MULTIPLIER
            intl_words = f"{curr_prefix}{mn_val:.2f} Million"
        elif abs(canonical_value) >= THOUSAND_MULTIPLIER:
            k_val = canonical_value / THOUSAND_MULTIPLIER
            intl_words = f"{curr_prefix}{k_val:.2f} Thousand"
        else:
            intl_words = f"{curr_prefix}{canonical_value:.2f}"

        # International numeric formatted
        intl_num = f"{curr_prefix}{format_international_number(canonical_value)}"

        # Ratio Equivalents
        bps_equiv: float | None = None
        pct_equiv: float | None = None
        if is_ratio_type or scale_label in ("bps", "%"):
            bps_equiv = round(canonical_value * 10000.0, 4)
            pct_equiv = round(canonical_value * 100.0, 4)

        # Synonyms & Search Aliases
        synonyms = self._generate_synonyms(canonical_value, currency, currency_sym, scale_label)

        return NormalizedFinancialValue(
            raw_expression=clean_text,
            canonical_value=canonical_value,
            canonical_unit=currency.value,
            currency_symbol=currency_sym,
            scale_label=scale_label,
            scale_multiplier=scale_mult,
            indian_words=indian_words,
            indian_numeric_formatted=indian_num,
            international_words=intl_words,
            international_numeric_formatted=intl_num,
            bps_equivalent=bps_equiv,
            percent_equivalent=pct_equiv,
            synonym_representations=synonyms,
            is_valid=True,
        )

    def format_to_indian_words(self, value: float, currency_sym: str = "₹") -> str:
        """Convert raw numeric float into idiomatic Indian financial words (Crore/Lakh)."""
        prefix = f"{currency_sym} " if currency_sym else ""
        if abs(value) >= CRORE_MULTIPLIER:
            return f"{prefix}{value / CRORE_MULTIPLIER:.2f} Crore"
        if abs(value) >= LAKH_MULTIPLIER:
            return f"{prefix}{value / LAKH_MULTIPLIER:.2f} Lakh"
        if abs(value) >= THOUSAND_MULTIPLIER:
            return f"{prefix}{value / THOUSAND_MULTIPLIER:.2f} Thousand"
        return f"{prefix}{format_indian_number(value)}"

    def format_to_international_words(self, value: float, currency_sym: str = "$") -> str:
        """Convert raw numeric float into idiomatic Western financial words (Million/Billion)."""
        prefix = f"{currency_sym} " if currency_sym else ""
        if abs(value) >= BILLION_MULTIPLIER:
            return f"{prefix}{value / BILLION_MULTIPLIER:.2f} Billion"
        if abs(value) >= MILLION_MULTIPLIER:
            return f"{prefix}{value / MILLION_MULTIPLIER:.2f} Million"
        if abs(value) >= THOUSAND_MULTIPLIER:
            return f"{prefix}{value / THOUSAND_MULTIPLIER:.2f} Thousand"
        return f"{prefix}{format_international_number(value)}"

    def are_equivalent(
        self,
        expr_a: str,
        expr_b: str,
        tolerance: float = 0.001,
    ) -> bool:
        """Check whether two financial or percentage expressions denote the exact same quantity."""
        norm_a = self.parse(expr_a)
        norm_b = self.parse(expr_b)

        if not norm_a.is_valid or not norm_b.is_valid:
            return False

        # Currency and ratio compatibility
        ratio_units = {
            Currency.BPS.value,
            Currency.PERCENT.value,
            Currency.RATIO.value,
            Currency.UNKNOWN.value,
        }
        is_a_ratio = norm_a.canonical_unit in ratio_units or norm_a.scale_label in ("bps", "%")
        is_b_ratio = norm_b.canonical_unit in ratio_units or norm_b.scale_label in ("bps", "%")

        if is_a_ratio and is_b_ratio:
            pass  # both are ratios / percentages, directly comparable
        elif (
            norm_a.canonical_unit not in (Currency.UNKNOWN.value, Currency.RATIO.value)
            and norm_b.canonical_unit not in (Currency.UNKNOWN.value, Currency.RATIO.value)
            and norm_a.canonical_unit != norm_b.canonical_unit
        ):
            # Different explicit currencies (e.g. USD vs EUR) cannot be strictly equivalent without FX
            return False

        # Value comparison with relative/absolute tolerance
        diff = abs(norm_a.canonical_value - norm_b.canonical_value)
        max_val = max(abs(norm_a.canonical_value), abs(norm_b.canonical_value))

        if max_val == 0.0:
            return diff <= tolerance

        relative_diff = diff / max_val
        return diff <= tolerance or relative_diff <= tolerance

    def expand_query_synonyms(self, query: str) -> list[str]:
        """Generate equivalent search strings with alternate unit denominations."""
        extracted = self.parse(query)
        if not extracted.is_valid:
            return [query]
        return extracted.synonym_representations

    def _generate_synonyms(
        self,
        canonical_val: float,
        currency: Currency,
        currency_sym: str | None,
        scale_label: str,
    ) -> list[str]:
        """Generate synonymous search representations."""
        syns: set[str] = set()
        c_prefix = f"{currency_sym} " if currency_sym else ""

        if scale_label in ("bps", "%") or currency in (Currency.BPS, Currency.PERCENT):
            bps_val = canonical_val * 10000.0
            pct_val = canonical_val * 100.0
            syns.add(f"{bps_val:.0f} bps")
            syns.add(f"{bps_val:.0f} basis points")
            syns.add(f"{pct_val:.2f}%")
            syns.add(f"{pct_val:.2f} percent")
            return sorted(syns)

        # Standard Indian expressions
        if abs(canonical_val) >= CRORE_MULTIPLIER:
            cr = canonical_val / CRORE_MULTIPLIER
            syns.add(f"{c_prefix}{cr:.2f} Crore")
            syns.add(f"{c_prefix}{cr:.2f} Cr")
            syns.add(f"{c_prefix}{cr:.0f} Crore" if cr % 1 == 0 else f"{c_prefix}{cr:.2f} Crore")
            syns.add(f"{c_prefix}{cr:.0f} Cr" if cr % 1 == 0 else f"{c_prefix}{cr:.2f} Cr")

        if abs(canonical_val) >= LAKH_MULTIPLIER:
            lk = canonical_val / LAKH_MULTIPLIER
            syns.add(f"{c_prefix}{lk:.2f} Lakh")
            syns.add(f"{c_prefix}{lk:.0f} Lakh" if lk % 1 == 0 else f"{c_prefix}{lk:.2f} Lakh")
            syns.add(f"{c_prefix}{lk:.2f} Lacs")

        # International expressions
        if abs(canonical_val) >= MILLION_MULTIPLIER:
            mn = canonical_val / MILLION_MULTIPLIER
            syns.add(f"{c_prefix}{mn:.2f} Million")
            syns.add(
                f"{c_prefix}{mn:.0f} Million" if mn % 1 == 0 else f"{c_prefix}{mn:.2f} Million"
            )
            syns.add(f"{c_prefix}{mn:.2f}M")

        if abs(canonical_val) >= BILLION_MULTIPLIER:
            bn = canonical_val / BILLION_MULTIPLIER
            syns.add(f"{c_prefix}{bn:.2f} Billion")
            syns.add(f"{c_prefix}{bn:.2f}B")

        # Comma formatted strings
        syns.add(f"{c_prefix}{format_indian_number(canonical_val)}")
        syns.add(f"{c_prefix}{format_international_number(canonical_val)}")

        return sorted(syns)

    def _empty_result(self, raw: str) -> NormalizedFinancialValue:
        return NormalizedFinancialValue(
            raw_expression=raw,
            canonical_value=0.0,
            canonical_unit=Currency.UNKNOWN.value,
            currency_symbol=None,
            scale_label="unit",
            scale_multiplier=1.0,
            indian_words="0.00",
            indian_numeric_formatted="0.00",
            international_words="0.00",
            international_numeric_formatted="0.00",
            is_valid=False,
        )


_DEFAULT_NORMALIZER: IndianFinancialUnitNormalizer | None = None


def get_default_unit_normalizer() -> IndianFinancialUnitNormalizer:
    """Singleton getter for IndianFinancialUnitNormalizer."""
    global _DEFAULT_NORMALIZER
    if _DEFAULT_NORMALIZER is None:
        _DEFAULT_NORMALIZER = IndianFinancialUnitNormalizer()
    return _DEFAULT_NORMALIZER
