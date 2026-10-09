"""Answer generation and citation binding for DocScout."""

from __future__ import annotations

from app.generate.generator import (
    BaseGenerator,
    DeterministicLocalGenerator,
    HostedGenerator,
    get_generator,
)
from app.generate.injection import (
    DEFAULT_CANARY_FORBIDDEN,
    scan_injection_signatures,
    verify_canary_resistance,
)
from app.generate.models import CitationSpan, GeneratedAnswer, GenerationConfig
from app.generate.prompt import SYSTEM_PROMPT, build_generation_prompt, format_evidence_context

__all__ = [
    "DEFAULT_CANARY_FORBIDDEN",
    "SYSTEM_PROMPT",
    "BaseGenerator",
    "CitationSpan",
    "DeterministicLocalGenerator",
    "GeneratedAnswer",
    "GenerationConfig",
    "HostedGenerator",
    "build_generation_prompt",
    "format_evidence_context",
    "get_generator",
    "scan_injection_signatures",
    "verify_canary_resistance",
]
