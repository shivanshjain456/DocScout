"""Adversarial Red-Teaming & Prompt Injection Shield (FEAT-083, ADR-0074).

Pre-retrieval security filter intercepting prompt injection attacks, system prompt leaks,
roleplay jailbreaks, delimiter breakouts, code execution payloads, and SQL injections.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

import structlog

from app.api import metrics

logger = structlog.get_logger("docscout.security.shield")

ThreatCategory = Literal[
    "prompt_injection",
    "system_prompt_leak",
    "roleplay_jailbreak",
    "delimiter_breakout",
    "code_injection",
    "sql_injection",
]

# Threat signatures and compiled automata
INJECTION_PATTERNS: list[tuple[ThreatCategory, re.Pattern[str], float]] = [
    # 1. Prompt Injections
    (
        "prompt_injection",
        re.compile(
            r"\b(?:ignore|disregard|forget|override)\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions|directions|prompts|rules|commands)\b",
            re.IGNORECASE,
        ),
        0.98,
    ),
    (
        "prompt_injection",
        re.compile(
            r"\bnew\s+instruction[:\s]+(?:you\s+are|you\s+must|now\s+act|do\s+not)\b",
            re.IGNORECASE,
        ),
        0.95,
    ),
    (
        "prompt_injection",
        re.compile(
            r"\bfrom\s+now\s+on\s+you\s+(?:are|must|will)\s+(?:unrestricted|ignore|obey|act\s+as\s+an\s+unrestricted)\b",
            re.IGNORECASE,
        ),
        0.96,
    ),
    (
        "prompt_injection",
        re.compile(
            r"\bdo\s+not\s+follow\s+(?:any\s+)?(?:previous|prior|system)\s+instructions\b",
            re.IGNORECASE,
        ),
        0.98,
    ),
    # 2. System Prompt Leaks
    (
        "system_prompt_leak",
        re.compile(
            r"\b(?:print|output|display|show|reveal|leak|repeat|verbatim|extract)\s+(?:your\s+)?(?:system\s+prompt|initial\s+instructions|system\s+instructions|developer\s+prompt|meta\s+prompt|hidden\s+prompt)\b",
            re.IGNORECASE,
        ),
        0.98,
    ),
    (
        "system_prompt_leak",
        re.compile(
            r"\bwhat\s+(?:are|were)\s+your\s+(?:initial\s+instructions|system\s+instructions|system\s+prompt)\b",
            re.IGNORECASE,
        ),
        0.95,
    ),
    (
        "system_prompt_leak",
        re.compile(
            r"\brepeat\s+the\s+(?:text|words|instructions)\s+(?:above|from\s+the\s+beginning)\b",
            re.IGNORECASE,
        ),
        0.92,
    ),
    # 3. Roleplay Jailbreaks
    (
        "roleplay_jailbreak",
        re.compile(
            r"\b(?:DAN|do\s+anything\s+now)\s+(?:mode|jailbreak)?\b",
            re.IGNORECASE,
        ),
        0.99,
    ),
    (
        "roleplay_jailbreak",
        re.compile(
            r"\b(?:developer|admin|maintenance|god|jailbroken|unrestricted)\s+mode\s+(?:enabled|activated|on|enter)\b",
            re.IGNORECASE,
        ),
        0.97,
    ),
    (
        "roleplay_jailbreak",
        re.compile(
            r"\byou\s+are\s+now\s+(?:an\s+unrestricted|unconstrained|DAN|a\s+rogue|free\s+of\s+rules)\b",
            re.IGNORECASE,
        ),
        0.98,
    ),
    (
        "roleplay_jailbreak",
        re.compile(
            r"\bhypothetical\s+scenario\s+where\s+you\s+have\s+no\s+(?:rules|filters|ethics|constraints)\b",
            re.IGNORECASE,
        ),
        0.99,
    ),
    # 4. Delimiter Breakouts
    (
        "delimiter_breakout",
        re.compile(
            r"</retrieved_evidence>|</document_chunk>|<\|im_start\|>|<\|im_end\|>",
            re.IGNORECASE,
        ),
        1.00,
    ),
    (
        "delimiter_breakout",
        re.compile(
            r"\[(?:SYSTEM|INSTRUCTION|ADMIN)\]|###\s*(?:System|Instruction|Assistant)\s*:",
            re.IGNORECASE,
        ),
        0.99,
    ),
    # 5. Code Injection & Remote Execution
    (
        "code_injection",
        re.compile(
            r"\b(?:__import__|eval\s*\(|exec\s*\(|os\.system|subprocess\.|passthru|shell_exec)\b",
            re.IGNORECASE,
        ),
        0.99,
    ),
    (
        "code_injection",
        re.compile(
            r"<script\b[^>]*>|javascript:|/bin/sh|/bin/bash|cmd\.exe|powershell\s+-enc",
            re.IGNORECASE,
        ),
        0.99,
    ),
    (
        "code_injection",
        re.compile(
            r"\b(?:curl|wget)\s+https?://",
            re.IGNORECASE,
        ),
        0.92,
    ),
    # 6. SQL Injection
    (
        "sql_injection",
        re.compile(
            r"\bSELECT\b.+?\bFROM\b|'\s*OR\s+'1'\s*=\s*'1|'\s*OR\s+1\s*=\s*1|\"\s*OR\s+\"1\"\s*=\s*\"1|\bWHERE\s+['\"]?1['\"]?\s*=\s*['\"]?1\b|;\s*DROP\s+TABLE\b|\bUNION\s+(?:ALL\s+)?SELECT\b|;\s*(?:DELETE|INSERT|UPDATE)\b",
            re.IGNORECASE,
        ),
        0.99,
    ),
]

# Direct attack payload fragments that are NEVER legitimate regulatory queries
DIRECT_ATTACK_FRAGMENTS = [
    "</retrieved_evidence>",
    "</document_chunk>",
    "<|im_start|>",
    "<|im_end|>",
    "[instruction]",
    "[system]",
    "<script",
    "exec(",
    "eval(",
    "ignore all previous",
    "disregard prior",
    "dan mode",
    "drop table",
    "'1'='1",
    "select * from",
    "hypothetical scenario where you have no",
]

# Legitimate regulatory inquiry markers to protect false positives
REGULATORY_INQUIRY_MARKERS = [
    "what are",
    "what is",
    "how does",
    "how to",
    "guidelines",
    "master direction",
    "circular",
    "requirement",
    "mandate",
    "compliance",
    "policy",
    "framework",
    "audit",
    "mitigation",
    "prevention",
    "vulnerabilit",
    "standard",
    "rbi",
    "sebi",
    "basel",
    "iso",
]


@dataclass
class ShieldConfig:
    """Configuration for pre-retrieval Security Shield."""

    blocking_threshold: float = 0.88
    rate_limit_on_attack: bool = True


@dataclass
class SecurityShieldDecision:
    """Security assessment decision for an incoming query."""

    is_safe: bool
    threat_type: str | None
    threat_score: float
    action: Literal["ALLOW", "BLOCK", "FLAG"]
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class SecurityShield:
    """Pre-retrieval query screening shield intercepting adversarial inputs."""

    def __init__(self, config: ShieldConfig | None = None) -> None:
        self.config = config or ShieldConfig()

    def _is_legitimate_regulatory_inquiry(self, query: str) -> bool:
        lower = query.lower()
        # Direct attack payloads are never legitimate
        if any(frag in lower for frag in DIRECT_ATTACK_FRAGMENTS):
            return False

        # Legitimate queries start with regulatory question framing or contain explicit regulation terms
        is_question = bool(
            re.search(
                r"^(?:what\s+(?:is|are|does)|how\s+(?:to|does)|explain|describe|clarify|rbi\s+guidelines|sebi\s+directions|rbi\s+master\s+direction|statutory\s+requirements|compliance\s+policy)\b",
                lower,
            )
        )
        has_reg_context = any(marker in lower for marker in REGULATORY_INQUIRY_MARKERS)
        return is_question or has_reg_context

    def screen(
        self,
        query: str,
        client_ip: str = "127.0.0.1",
    ) -> SecurityShieldDecision:
        """Screen an incoming query for prompt injections and adversarial threats."""
        _ = client_ip
        if not query or not query.strip():
            return SecurityShieldDecision(
                is_safe=True,
                threat_type=None,
                threat_score=0.0,
                action="ALLOW",
                reason="empty_query",
            )

        text = query.strip()
        highest_score = 0.0
        primary_threat: str | None = None
        matched_rule: str | None = None

        for threat_type, pattern, score in INJECTION_PATTERNS:
            if pattern.search(text):
                if score > highest_score:
                    highest_score = score
                    primary_threat = threat_type
                    matched_rule = pattern.pattern

        # Check for false positive mitigation on legitimate compliance queries
        if highest_score > 0.0 and self._is_legitimate_regulatory_inquiry(text):
            # Downgrade score if query is clearly asking for regulatory guidelines
            if highest_score < 0.98:
                highest_score = 0.20
                primary_threat = None

        action: Literal["ALLOW", "BLOCK", "FLAG"]
        if highest_score >= self.config.blocking_threshold:
            action = "BLOCK"
            is_safe = False
            metrics.SECURITY_THREATS_BLOCKED_TOTAL.labels(
                threat_type=primary_threat or "unknown"
            ).inc()
            logger.warning(
                "security_shield.threat_blocked",
                threat_type=primary_threat,
                threat_score=highest_score,
                client_ip=client_ip,
                matched_rule=matched_rule,
            )
        elif highest_score >= 0.50:
            action = "FLAG"
            is_safe = True
        else:
            action = "ALLOW"
            is_safe = True

        return SecurityShieldDecision(
            is_safe=is_safe,
            threat_type=primary_threat,
            threat_score=round(highest_score, 4),
            action=action,
            reason=f"matched:{primary_threat}" if primary_threat else "clean",
        )


_DEFAULT_SHIELD: SecurityShield | None = None


def get_default_security_shield() -> SecurityShield:
    """Return singleton instance of SecurityShield."""
    global _DEFAULT_SHIELD
    if _DEFAULT_SHIELD is None:
        _DEFAULT_SHIELD = SecurityShield()
    return _DEFAULT_SHIELD
