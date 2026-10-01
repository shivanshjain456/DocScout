"""Typed failures for the ingestion pipeline.

Every one of these corresponds to a requirement that says the ingester MUST refuse
something. They are distinct types rather than one `IngestError` with a message because
the pipeline has to tell "this document is bad" (skip it, record it, keep going) apart
from "this environment is unsafe" (stop immediately), and callers should not have to
pattern-match on strings to do that.
"""

from __future__ import annotations


class IngestError(Exception):
    """Base class for every ingestion failure."""


class CredentialBleedError(IngestError):
    """Deploy or cloud credentials were present in the environment (FR-6, SECURITY S-4).

    Fatal and unconditional: raised before any network call or database connection.
    """


class DisallowedHostError(IngestError):
    """A URL outside the CORPUS_SPEC §2 host allowlist (FR-1, C-1).

    A hard error, never a skip, and raised before any network call.
    """


class ShortExtractionError(IngestError):
    """Extraction produced fewer than the required number of clean characters (FR-3).

    This is the SEBI detail-page failure mode (K-17): ~227 characters that look like a
    successful fetch. Storing it would be silent data loss.
    """


class ExtractionError(IngestError):
    """The extractor could not produce text at all (corrupt PDF, unknown media type)."""


class EmbeddingContractError(IngestError):
    """The embedder violated the contract ADR-0002 fixed (dimension or normalisation)."""
