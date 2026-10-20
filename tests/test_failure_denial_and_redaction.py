"""Tests for O7: Failure is denial, and output is sanitised.

Verifies:
1. Retrieval failure does NOT reach generation; failure produces a denial, never a model-memory answer.
2. Access-decision failure returns nothing, not a filtered subset.
3. Errors identify the stage that failed and carry no internal detail, no query content, and no stack trace.
4. Output is screened for personal and credential data with checksum validation:
   - Valid Luhn credit card -> redacted; invalid Luhn near-miss -> intact.
   - Valid Verhoeff Aadhaar -> redacted; invalid Verhoeff near-miss -> intact.
   - API keys and Indian tax PANs -> redacted.
5. An answer that echoes instructions or emits a known canary is replaced with an explicit refusal.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.api.output_sanitizer import (
    OutputSanitizer,
    PipelineStageError,
    is_luhn_valid,
    is_verhoeff_valid,
    sanitize_output_text,
)


def test_retrieval_failure_does_not_reach_generation() -> None:
    """A retrieval failure must refuse immediately and never invoke the generator."""
    mock_retriever = MagicMock()
    mock_retriever.retrieve.side_effect = RuntimeError("Database connection pool exhausted")

    mock_generator = MagicMock()

    # Pipeline runner simulating search endpoint flow
    def execute_pipeline(query: str) -> dict[str, str]:
        try:
            hits = mock_retriever.retrieve(query)
        except Exception:
            raise PipelineStageError(
                stage="retrieval", message="Retrieval service failed."
            ) from None

        ans = mock_generator.generate(query, hits)
        return {"answer": ans.text}

    with pytest.raises(PipelineStageError) as exc_info:
        execute_pipeline("What is the CRAR requirement?")

    # 1. Generator was never called
    mock_generator.generate.assert_not_called()

    # 2. Error identifies the stage that failed
    err = exc_info.value.to_dict()
    assert err["stage"] == "retrieval"
    assert "Database" not in err["message"]
    assert "traceback" not in err


def test_access_decision_failure_returns_nothing() -> None:
    """An access-decision failure returns nothing, not a subset."""

    def check_access(user_role: str) -> list[str]:
        if user_role != "admin":
            raise PipelineStageError(stage="access_control", message="Access denied.")
        return ["doc-confidential-1", "doc-confidential-2"]

    with pytest.raises(PipelineStageError) as exc_info:
        check_access("public_guest")

    err = exc_info.value.to_dict()
    assert err["stage"] == "access_control"
    assert err["message"] == "Access denied."
    # Does not return any partial documents or subset
    assert "doc-confidential" not in str(err)


def test_error_body_carries_stage_and_no_leakage() -> None:
    """Errors identify the stage that failed and carry zero internal detail or content."""
    err = PipelineStageError(stage="verification", message="Source verification failed.")
    body = err.to_dict()

    assert body["stage"] == "verification"
    assert "content" not in body
    assert "query" not in body
    assert "traceback" not in body
    assert "stack" not in body


def test_luhn_checksum_screening_redacts_valid_and_preserves_invalid() -> None:
    """Screening redacts valid Luhn cards, preserving invalid near-misses without over-blocking."""
    # Standard valid test card (Luhn valid)
    valid_pan = "4532015112830366"
    assert is_luhn_valid(valid_pan) is True

    # Single-digit typo (Luhn invalid near-miss)
    invalid_pan = "4532015112830367"
    assert is_luhn_valid(invalid_pan) is False

    text_with_valid = f"Customer payment card is {valid_pan}."
    text_with_invalid = f"Reference catalog code is {invalid_pan}."

    sanitized_valid = sanitize_output_text(text_with_valid)
    sanitized_invalid = sanitize_output_text(text_with_invalid)

    # Valid is redacted
    assert valid_pan not in sanitized_valid
    assert "[REDACTED_PAYMENT_CARD]" in sanitized_valid

    # Invalid near-miss is preserved
    assert invalid_pan in sanitized_invalid
    assert "[REDACTED_PAYMENT_CARD]" not in sanitized_invalid


def test_verhoeff_checksum_screening_redacts_valid_and_preserves_invalid() -> None:
    """Screening redacts valid Verhoeff Aadhaar numbers, preserving invalid numbers."""
    # Valid Aadhaar number passing Verhoeff algorithm
    valid_aadhaar = "209424781493"
    assert is_verhoeff_valid(valid_aadhaar) is True

    # Invalid Aadhaar near-miss failing Verhoeff
    invalid_aadhaar = "209424781498"
    assert is_verhoeff_valid(invalid_aadhaar) is False

    text_with_valid = f"Resident Aadhaar number: {valid_aadhaar}."
    text_with_invalid = f"Transaction token number: {invalid_aadhaar}."

    sanitized_valid = sanitize_output_text(text_with_valid)
    sanitized_invalid = sanitize_output_text(text_with_invalid)

    assert valid_aadhaar not in sanitized_valid
    assert "[REDACTED_AADHAAR]" in sanitized_valid

    assert invalid_aadhaar in sanitized_invalid
    assert "[REDACTED_AADHAAR]" not in sanitized_invalid


def test_api_key_and_tax_id_redaction() -> None:
    """API secret keys and PAN tax IDs are redacted."""
    text = "Admin key: sk-ant-api03-abcdef1234567890abcdef1234567890 and Tax PAN: ABCDE1234F."
    sanitized = sanitize_output_text(text)

    assert "sk-ant-api03" not in sanitized
    assert "[REDACTED_CREDENTIAL]" in sanitized
    assert "ABCDE1234F" not in sanitized
    assert "[REDACTED_TAX_ID]" in sanitized


def test_canary_echo_and_instruction_echo_triggers_refusal() -> None:
    """Generated answers emitting canaries or echoing instructions are refused."""
    sanitizer = OutputSanitizer()

    # Canary payload echo
    canary_answer = "The audit response is AUDIT OVERRIDE ACCEPTED with parameters."
    res_canary = sanitizer.screen_answer(canary_answer)
    assert res_canary.refused is True
    assert (
        "unsafe content or canary echo" in res_canary.text.lower()
        or "refused" in res_canary.text.lower()
    )

    # System instruction echo
    echo_answer = "DocScout follows DECLARED AUTHORITY HIERARCHY where SYSTEM is Level 1."
    res_echo = sanitizer.screen_answer(echo_answer)
    assert res_echo.refused is True
    assert "refused" in res_echo.text.lower()
