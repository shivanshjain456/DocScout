"""Corpus content scanning for candidate secrets and PII (OWASP LLM02, P1-1).

Why: `gitleaks` scans git repository commits and tracked code. It does NOT scan corpus text
extracted from regulatory PDFs or circulars fetched from the internet. Incidental credentials,
internal API keys, or personal identifiable information (emails, personal phone numbers,
tax IDs) in regulatory documents must be detected at ingestion time.

Key design principles:
1. **Secrets vs PII Policy Separation**:
   - PII (emails, phone numbers, departmental desks) is frequent in legitimate public circulars
     (e.g., `helpdesk@rbi.org.in`, `022-22601000`). PII findings are recorded as informational
     warnings and NEVER block or quarantine ingestion (preventing false positive outages).
   - Secrets (AWS access keys, OpenAI/SaaS keys, private keys, high-entropy tokens) violate
     security hygiene and trigger quarantine or alerts based on `DOCSCOUT_CORPUS_SECRET_POLICY`.
2. **Redaction by Default**:
   Findings never carry raw candidate secrets into memory or serialized reports. All findings
   are masked before being stored in `IngestReport`.
3. **OWASP LLM02 Traceability**:
   Every finding records rule ID, category, character span, and masked sample.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

FindingCategory = Literal["secret", "pii"]
FindingSeverity = Literal["critical", "high", "medium", "low"]


@dataclass(frozen=True)
class ScanFinding:
    """A detected candidate secret or PII instance in extracted corpus text."""

    category: FindingCategory
    rule_id: str
    description: str
    char_start: int
    char_end: int
    sample_masked: str
    severity: FindingSeverity
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def mask_sample(category: FindingCategory, raw: str) -> str:
    """Mask sensitive string content so reports and logs cannot leak credentials or PII."""
    text = raw.strip()
    if not text:
        return "[empty]"

    if category == "secret":
        if len(text) <= 8:
            return "[redacted-secret]"
        # Keep first 4 and last 4 chars, mask middle with asterisks
        return f"{text[:4]}{'*' * (len(text) - 8)}{text[-4:]}"

    # PII masking
    if "@" in text:  # Email
        parts = text.split("@", 1)
        user = parts[0]
        domain = parts[1] if len(parts) > 1 else ""
        masked_user = f"{user[0]}***" if user else "***"
        return f"{masked_user}@{domain}"
    if len(text) >= 10 and text.replace("-", "").replace(" ", "").isdigit():  # Phone or Aadhaar
        digits = text.replace("-", "").replace(" ", "")
        return f"***-***-{digits[-4:]}"
    if len(text) == 10 and text[:5].isalpha():  # PAN
        return f"{text[:2]}***{text[-2:]}"

    return f"{text[:2]}***{text[-2:]}" if len(text) > 4 else "[redacted-pii]"


# Detection Regex Patterns
_RULES: list[tuple[str, FindingCategory, FindingSeverity, str, re.Pattern[str]]] = [
    # ------------------ Secrets ------------------
    (
        "SEC001",
        "secret",
        "critical",
        "AWS Access Key ID",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    ),
    (
        "SEC002",
        "secret",
        "critical",
        "RSA / EC / OpenSSH Private Key header",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ),
    (
        "SEC003",
        "secret",
        "critical",
        "GitHub Personal Access Token or App Token",
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,255}\b"),
    ),
    (
        "SEC004",
        "secret",
        "critical",
        "GitHub Fine-grained PAT",
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]{82}\b"),
    ),
    (
        "SEC005",
        "secret",
        "high",
        "SaaS API Key (sk- pattern)",
        re.compile(r"\bsk-[a-zA-Z0-9]{20,}\b"),
    ),
    (
        "SEC006",
        "secret",
        "high",
        "Hardcoded password or secret assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret[_-]?key|auth[_-]?token|access[_-]?token|password)\s*[:=]\s*['\"]([a-zA-Z0-9_\-\.]{16,})['\"]"
        ),
    ),
    (
        "SEC007",
        "secret",
        "high",
        "Synthetic Canary Test Secret",
        re.compile(r"\b(?:SYNTH|CANARY)[_-]SECRET[_-][A-Za-z0-9]{8,}\b"),
    ),
    # ------------------ PII ------------------
    (
        "PII001",
        "pii",
        "low",
        "Email address",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b"),
    ),
    (
        "PII002",
        "pii",
        "low",
        "Indian Mobile or Landline Phone Number",
        re.compile(r"(?:\+91[\s-]?)?[6789]\d{9}\b"),
    ),
    (
        "PII003",
        "pii",
        "medium",
        "Indian Income Tax PAN (Permanent Account Number)",
        re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"),
    ),
    (
        "PII004",
        "pii",
        "medium",
        "Indian Aadhaar Number format",
        re.compile(r"\b\d{4}\s\d{4}\s\d{4}\b"),
    ),
]


def scan_text(text: str) -> list[ScanFinding]:
    """Scan extracted corpus text for candidate secrets and PII patterns.

    Returns a list of `ScanFinding` instances with masked samples and exact character offsets.
    """
    if not text:
        return []

    findings: list[ScanFinding] = []
    for rule_id, category, severity, description, pattern in _RULES:
        for match in pattern.finditer(text):
            raw_match = match.group(0)
            # If pattern has group 1, that's the captured secret value
            if match.lastindex and match.lastindex >= 1:
                secret_val = match.group(1)
                start, end = match.span(1)
                sample = mask_sample(category, secret_val)
            else:
                start, end = match.span(0)
                sample = mask_sample(category, raw_match)

            findings.append(
                ScanFinding(
                    category=category,
                    rule_id=rule_id,
                    description=description,
                    char_start=start,
                    char_end=end,
                    sample_masked=sample,
                    severity=severity,
                )
            )

    findings.sort(key=lambda f: (f.char_start, f.rule_id))
    return findings


class SecretPolicyViolation(RuntimeError):
    """Raised when ingestion encounters a secret under policy='fail'."""


def evaluate_scan_policy(
    findings: list[ScanFinding], policy: str | None = None
) -> tuple[str, bool]:
    """Evaluate scan findings against policy ('warn', 'quarantine', or 'fail').

    Returns (status, is_quarantined).
    Notice that PII findings NEVER quarantine or fail ingestion.
    """
    active_policy = (
        (policy or os.environ.get("DOCSCOUT_CORPUS_SECRET_POLICY", "warn")).strip().lower()
    )

    secret_findings = [f for f in findings if f.category == "secret"]
    if not secret_findings:
        return "ok", False

    if active_policy == "fail":
        raise SecretPolicyViolation(
            f"Ingestion rejected document: {len(secret_findings)} secret finding(s) detected "
            f"under policy 'fail' (rule: {secret_findings[0].rule_id})."
        )
    if active_policy == "quarantine":
        return "quarantined", True

    return "warn", False
