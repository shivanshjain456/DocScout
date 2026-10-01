"""DocScout corpus ingestion — SPEC FR-1 … FR-8, ARCHITECTURE §3.1.

Stages: fetch → extract → guard → clean → chunk → embed → store.

An offline CLI pipeline, never reachable from `app/api/` (OUT-5). The public names below
are the pipeline's seams; everything else is an implementation detail of a stage.
"""

from __future__ import annotations

from app.ingest.chunk import Chunk, chunk_document, verify_offsets
from app.ingest.clean import clean_char_count, clean_preserving_offsets
from app.ingest.embed import EMBEDDING_DIM, MODEL_ID, QUERY_PREFIX, Embedder
from app.ingest.errors import (
    CredentialBleedError,
    DisallowedHostError,
    EmbeddingContractError,
    ExtractionError,
    IngestError,
    ShortExtractionError,
)
from app.ingest.extract import assert_extraction_long_enough, extract
from app.ingest.guards import assert_no_deploy_credentials
from app.ingest.pipeline import IngestReport, run_ingest, verify_stored_chunks
from app.ingest.source import SourceDocument, iter_manifest_documents
from app.ingest.store import Action, StoreOutcome, connect, store_document

__all__ = [
    "EMBEDDING_DIM",
    "MODEL_ID",
    "QUERY_PREFIX",
    "Action",
    "Chunk",
    "CredentialBleedError",
    "DisallowedHostError",
    "EmbeddingContractError",
    "Embedder",
    "ExtractionError",
    "IngestError",
    "IngestReport",
    "ShortExtractionError",
    "SourceDocument",
    "StoreOutcome",
    "assert_extraction_long_enough",
    "assert_no_deploy_credentials",
    "chunk_document",
    "clean_char_count",
    "clean_preserving_offsets",
    "connect",
    "extract",
    "iter_manifest_documents",
    "run_ingest",
    "store_document",
    "verify_offsets",
    "verify_stored_chunks",
]
