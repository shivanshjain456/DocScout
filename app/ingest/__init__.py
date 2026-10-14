"""DocScout corpus ingestion  -  SPEC FR-1 … FR-8, ARCHITECTURE §3.1.

Stages: fetch → extract → guard → clean → chunk → embed → store.

An offline CLI pipeline, never reachable from `app/api/` (OUT-5). The public names below
are the pipeline's seams; everything else is an implementation detail of a stage.
"""

from __future__ import annotations

from app.ingest.chunk import (
    Chunk,
    chunk_document,
    chunk_document_hierarchical,
    verify_offsets,
)
from app.ingest.clean import clean_char_count, clean_preserving_offsets
from app.ingest.deadline_extractor import (
    DeadlineAlertConfig,
    DeadlineExtractor,
    RegulatoryDeadline,
    extract_regulatory_deadlines,
)
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
from app.ingest.hierarchical_chunker import (
    ChunkingConfig,
    HierarchicalChunk,
    HierarchicalChunker,
    get_default_hierarchical_chunker,
)
from app.ingest.ocr_quality import (
    ImagePreprocessor,
    OCRQualityConfig,
    OCRQualityEvaluator,
    OCRQualityScore,
    assess_page_quality,
    compute_wer,
    get_default_quality_evaluator,
)
from app.ingest.offset_matrix import (
    ChunkCoordinates,
    OffsetTraceabilityMatrix,
    TraceabilityConfig,
    extract_span_coordinates,
    get_default_offset_matrix,
)
from app.ingest.pipeline import IngestReport, run_ingest, verify_stored_chunks
from app.ingest.scope_classifier import (
    ScopeClassification,
    ScopeClassifier,
    ScopeConfig,
    classify_scope,
)
from app.ingest.source import SourceDocument, iter_manifest_documents
from app.ingest.store import Action, StoreOutcome, connect, store_document
from app.ingest.table_parser import (
    ExtractedTable,
    TableParser,
    TableParserConfig,
    extract_tables_from_pdf,
    get_default_table_parser,
)

__all__ = [
    "EMBEDDING_DIM",
    "MODEL_ID",
    "QUERY_PREFIX",
    "Action",
    "Chunk",
    "ChunkCoordinates",
    "ChunkingConfig",
    "CredentialBleedError",
    "DeadlineAlertConfig",
    "DeadlineExtractor",
    "DisallowedHostError",
    "EmbeddingContractError",
    "Embedder",
    "ExtractedTable",
    "ExtractionError",
    "HierarchicalChunk",
    "HierarchicalChunker",
    "ImagePreprocessor",
    "IngestError",
    "IngestReport",
    "OCRQualityConfig",
    "OCRQualityEvaluator",
    "OCRQualityScore",
    "OffsetTraceabilityMatrix",
    "RegulatoryDeadline",
    "ScopeClassification",
    "ScopeClassifier",
    "ScopeConfig",
    "ShortExtractionError",
    "SourceDocument",
    "StoreOutcome",
    "TableParser",
    "TableParserConfig",
    "TraceabilityConfig",
    "assert_extraction_long_enough",
    "assert_no_deploy_credentials",
    "assess_page_quality",
    "chunk_document",
    "chunk_document_hierarchical",
    "classify_scope",
    "clean_char_count",
    "clean_preserving_offsets",
    "compute_wer",
    "connect",
    "extract",
    "extract_regulatory_deadlines",
    "extract_span_coordinates",
    "extract_tables_from_pdf",
    "get_default_hierarchical_chunker",
    "get_default_offset_matrix",
    "get_default_quality_evaluator",
    "get_default_table_parser",
    "iter_manifest_documents",
    "run_ingest",
    "store_document",
    "verify_offsets",
    "verify_stored_chunks",
]
