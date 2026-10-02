"""Logging configuration and request correlation.

Before this module there was no logging configuration anywhere in the repository. Six
`logger.*` calls in `app/api/app.py` wrote to an unconfigured root logger, so everything at
INFO — every access line — was silently discarded, and the only records that reached a
terminal were uvicorn's own. "Can you debug this from logs?" answered itself.

Three decisions worth stating.

**structlog rather than a hand-rolled JSON formatter.** It was already a declared
dependency and imported nowhere, which is a supply-chain surface with no benefit. Using it
removes that, and `structlog.stdlib.ProcessorFormatter` is the piece that matters here: it
routes *stdlib* records — uvicorn's, psycopg's, ours — through the same processor chain, so
one configuration produces one format for every log line in the process rather than two
formats that drift.

**JSON off a TTY, human-readable on one.** A developer reading a terminal and a log
shipper parsing a stream want opposite things, and guessing wrong makes one of them
miserable. `DOCSCOUT_LOG_JSON` overrides the detection when the guess is wrong.

**Redaction is a processor, not a convention.** Any event key whose name looks like a
credential is replaced before rendering. Relying on every future call site to remember not
to log the API key is how keys end up in logs; doing it once in the pipeline means a
mistake at a call site is contained.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import uuid
from collections.abc import MutableMapping
from typing import Any

import structlog

#: Event keys replaced with a placeholder before rendering. Matched case-insensitively as
#: substrings, so `x_api_key`, `DB_PASSWORD` and `authorization` are all caught.
SENSITIVE_KEY_PARTS = ("api_key", "apikey", "password", "secret", "token", "authorization")

REDACTED = "[redacted]"

#: Inbound X-Request-ID values are echoed into every log record for the request, so they
#: are untrusted input to the log. Restricting the charset and length stops a caller
#: injecting newlines (forging log entries) or megabytes (filling the disk).
_REQUEST_ID_SAFE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")

#: Library loggers quieted to WARNING. Chatty at INFO about work that is not the
#: application's: HTTP calls to the model hub, tokenizer downloads, connection churn.
THIRD_PARTY_QUIET = (
    "httpx",
    "httpcore",
    "huggingface_hub",
    "sentence_transformers",
    "transformers",
    "urllib3",
    "filelock",
)

_configured = False


def _redact_sensitive(
    _logger: Any, _name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Replace credential-looking *string* values before anything renders them.

    Only strings and bytes are redacted. The first version matched on the key name alone
    and turned `api_keys=1` -- the number of configured keys, logged at startup -- into
    "[redacted]", which destroys a useful operational signal and tells nobody anything.
    A credential is a string; a count, a flag and a duration are not.
    """
    for key, value in list(event_dict.items()):
        if not isinstance(value, (str, bytes)):
            continue
        if any(part in key.lower() for part in SENSITIVE_KEY_PARTS):
            event_dict[key] = REDACTED
    return event_dict


def configure_logging(level: str | None = None, *, json_output: bool | None = None) -> None:
    """Configure structlog and the stdlib root logger as one pipeline.

    Idempotent: uvicorn imports the application module and may trigger this more than once,
    and adding a second handler would duplicate every line.
    """
    global _configured
    if _configured:
        return

    resolved_level = (level or os.environ.get("DOCSCOUT_LOG_LEVEL") or "INFO").upper()
    if json_output is None:
        override = os.environ.get("DOCSCOUT_LOG_JSON", "").strip().lower()
        if override in {"1", "true", "yes"}:
            json_output = True
        elif override in {"0", "false", "no"}:
            json_output = False
        else:
            json_output = not sys.stderr.isatty()

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact_sensitive,
    ]

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            # foreign_pre_chain runs for records that did NOT come from structlog --
            # uvicorn's and psycopg's -- so third-party logs arrive in the same shape.
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(resolved_level)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    # Third-party INFO is about their work, not ours. Loading the embedding model emits
    # ~30 httpx lines resolving files on the Hugging Face hub, which buries the one line
    # that matters ("api.ready"). Raised to WARNING so failures still surface.
    for name in THIRD_PARTY_QUIET:
        logging.getLogger(name).setLevel(
            max(logging.WARNING, logging.getLevelNamesMapping().get(resolved_level, logging.INFO))
        )

    _configured = True


def reset_logging_for_tests() -> None:
    """Allow a test to reconfigure. Not used by application code."""
    global _configured
    _configured = False


def normalise_request_id(raw: str | None) -> str:
    """Return a safe correlation id, minting one when the caller supplied nothing usable.

    An inbound id is honoured so a request can be traced across a proxy or a client that
    already has one, but only if it is short and free of control characters — it is
    attacker-controlled text that ends up in every log line for the request.
    """
    if raw and _REQUEST_ID_SAFE.match(raw):
        return raw
    return uuid.uuid4().hex[:16]


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
