"""Tests for logging configuration and request correlation.

These assert on emitted records rather than on the configuration object, because the
failure that matters is "nothing came out" or "the key came out", and only the output
shows either. Before this module existed, every INFO record in the API was discarded by an
unconfigured root logger, which no configuration-shaped assertion would have caught.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
import structlog

from app.observability import (
    REDACTED,
    configure_logging,
    get_logger,
    normalise_request_id,
    reset_logging_for_tests,
)


@pytest.fixture(autouse=True)
def _isolate_logging() -> Iterator[None]:
    reset_logging_for_tests()
    structlog.contextvars.clear_contextvars()
    yield
    reset_logging_for_tests()
    structlog.reset_defaults()
    logging.getLogger().handlers.clear()


def emitted(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    """Parse the JSON lines written to stderr."""
    return [json.loads(line) for line in capsys.readouterr().err.splitlines() if line.strip()]


# --- the records actually come out, and are JSON ----------------------------------------
def test_info_records_are_emitted_as_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_output=True)
    get_logger("docscout.test").info("search.completed", mode="hybrid", k=10)
    records = emitted(capsys)
    assert len(records) == 1
    assert records[0]["event"] == "search.completed"
    assert records[0]["mode"] == "hybrid"
    assert records[0]["k"] == 10
    assert records[0]["level"] == "info"
    assert records[0]["timestamp"].endswith("Z")


def test_level_is_respected(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("WARNING", json_output=True)
    log = get_logger("docscout.test")
    log.info("suppressed")
    log.warning("kept")
    assert [r["event"] for r in emitted(capsys)] == ["kept"]


def test_stdlib_loggers_render_through_the_same_pipeline(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """uvicorn and psycopg log via stdlib; one process must not emit two formats."""
    configure_logging("INFO", json_output=True)
    logging.getLogger("uvicorn.error").info("started")
    records = emitted(capsys)
    assert len(records) == 1
    assert records[0]["event"] == "started"
    assert records[0]["logger"] == "uvicorn.error"


def test_configuration_is_idempotent(capsys: pytest.CaptureFixture[str]) -> None:
    """uvicorn imports the app module more than once; a second handler would double lines."""
    configure_logging("INFO", json_output=True)
    configure_logging("INFO", json_output=True)
    get_logger("docscout.test").info("once")
    assert len(emitted(capsys)) == 1


def test_console_renderer_is_used_off_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_output=False)
    get_logger("docscout.test").info("human readable")
    err = capsys.readouterr().err
    assert "human readable" in err
    with pytest.raises(json.JSONDecodeError):
        json.loads(err.splitlines()[0])


# --- credentials must never reach a log -------------------------------------------------
@pytest.mark.parametrize(
    "key",
    [
        "api_key",
        "X_API_KEY",
        "apikey",
        "password",
        "db_password",
        "secret",
        "token",
        "authorization",
    ],
)
def test_credential_shaped_keys_are_redacted(capsys: pytest.CaptureFixture[str], key: str) -> None:
    """Redaction is a processor so one forgetful call site cannot leak a key."""
    configure_logging("INFO", json_output=True)
    get_logger("docscout.test").info("auth", **{key: "super-secret-value"})
    record = emitted(capsys)[0]
    assert record[key] == REDACTED
    assert "super-secret-value" not in json.dumps(record)


def test_non_sensitive_fields_are_untouched(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_output=True)
    get_logger("docscout.test").info("search", key_fingerprint="abc123", mode="hybrid")
    record = emitted(capsys)[0]
    assert record["key_fingerprint"] == "abc123"  # a fingerprint is safe, a key is not
    assert record["mode"] == "hybrid"


# --- correlation ------------------------------------------------------------------------
def test_bound_context_appears_on_every_record(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_output=True)
    structlog.contextvars.bind_contextvars(request_id="req-1", path="/v1/search")
    get_logger("a").info("first")
    get_logger("b").info("second")
    assert [r["request_id"] for r in emitted(capsys)] == ["req-1", "req-1"]


def test_exceptions_are_rendered_with_a_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_output=True)
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        get_logger("docscout.test").exception("http.unhandled")
    record = emitted(capsys)[0]
    assert "RuntimeError: boom" in record["exception"]


# --- request id validation --------------------------------------------------------------
def test_a_usable_inbound_id_is_honoured() -> None:
    assert normalise_request_id("trace-abc.123:xyz") == "trace-abc.123:xyz"


@pytest.mark.parametrize(
    "hostile",
    [
        None,
        "",
        "has space",
        "newline\ninjected",  # forging a second log line
        "carriage\rreturn",
        "x" * 65,  # unbounded length
        "semi;colon",
        "\x00null",
    ],
)
def test_unusable_inbound_ids_are_replaced(hostile: str | None) -> None:
    """The id is echoed into every log line for the request, so it is untrusted input."""
    generated = normalise_request_id(hostile)
    assert generated != hostile
    assert len(generated) == 16
    assert generated.isalnum()


def test_generated_ids_are_unique() -> None:
    assert len({normalise_request_id(None) for _ in range(200)}) == 200


def test_non_string_values_are_not_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    """`api_keys=1` is a count, not a credential.

    The first version of the redactor matched on the key name alone and destroyed this
    signal at startup, which is how a safety measure becomes an operational blind spot.
    """
    configure_logging("INFO", json_output=True)
    get_logger("docscout.test").info("api.ready", api_keys=2, token_count=512, secret_ok=True)
    record = emitted(capsys)[0]
    assert record["api_keys"] == 2
    assert record["token_count"] == 512
    assert record["secret_ok"] is True


def test_string_credentials_are_still_redacted_alongside_counts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", json_output=True)
    get_logger("docscout.test").info("mixed", api_keys=2, api_key="real-secret-value")
    record = emitted(capsys)[0]
    assert record["api_keys"] == 2
    assert record["api_key"] == REDACTED


def test_third_party_info_is_quieted(capsys: pytest.CaptureFixture[str]) -> None:
    """Loading the encoder emits ~30 httpx lines that bury the one line that matters."""
    configure_logging("INFO", json_output=True)
    logging.getLogger("httpx").info("HTTP Request: HEAD https://huggingface.co/...")
    logging.getLogger("httpx").warning("connection failed")
    events = [r["event"] for r in emitted(capsys)]
    assert events == ["connection failed"]
