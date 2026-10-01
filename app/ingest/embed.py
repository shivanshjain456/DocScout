"""Embedding — ADR-0002.

`BAAI/bge-small-en-v1.5` at 384 dimensions, L2-normalised, CPU-only. ADR-0002 fixed this
after a five-arm bake-off and called the dimension a one-way door: `chunks.embedding` is
`vector(384)` and changing it costs a reindex plus three fresh evaluation baselines.

Two asymmetries from that decision which this module is the only place to get right:

* **Query text carries a prefix, passage text does not.** BGE is trained with an
  instruction on the query side only. Prefixing passages, or forgetting to prefix queries,
  degrades retrieval quietly — nothing raises, scores just get worse.
* **Everything is L2-normalised.** `ck_chunks_unit_norm` enforces this in the database, so
  an un-normalised vector is rejected at INSERT rather than silently ranking by magnitude.

The contract checks in `_load` exist because the failure they catch — a model resolving to
different weights or a different dimension after a cache eviction or a version bump — would
otherwise surface as a dimension error deep inside a bulk insert, or not at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from app.ingest.errors import EmbeddingContractError

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

#: ADR-0002. Pinned; changing it requires a new ADR and a re-embedding of the corpus.
MODEL_ID = "BAAI/bge-small-en-v1.5"

#: ADR-0002: mandatory on queries, forbidden on passages.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

#: ADR-0002, and `chunks.embedding vector(384)`.
EMBEDDING_DIM = 384

#: Tolerance matching `ck_chunks_unit_norm`. float32 round-trips land near 1.00000004, so
#: a tighter bound would reject correct vectors.
_NORM_TOLERANCE = 1e-4


class Embedder:
    """Lazily loaded sentence-transformers encoder honouring ADR-0002's contract."""

    def __init__(self, model_id: str = MODEL_ID, *, batch_size: int = 16) -> None:
        self.model_id = model_id
        self.batch_size = batch_size
        self._model: SentenceTransformer | None = None

    def _load(self) -> SentenceTransformer:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(self.model_id, device="cpu")
            # sentence-transformers 6.x renamed this; support both rather than pin to
            # whichever happens to be installed.
            dimension_of = getattr(
                model, "get_embedding_dimension", model.get_sentence_embedding_dimension
            )
            dim = int(dimension_of() or 0)
            if dim != EMBEDDING_DIM:
                raise EmbeddingContractError(
                    f"{self.model_id} produced {dim} dimensions, but ADR-0002 fixed "
                    f"D = {EMBEDDING_DIM} and chunks.embedding is vector({EMBEDDING_DIM})"
                )
            self._model = model
        return self._model

    def count_tokens(self, text: str) -> int:
        """Tokens the encoder will see, including [CLS] and [SEP].

        Counting the special tokens matters: `max_seq_length` is 512 *including* them, so
        excluding them would let a chunk sit two tokens over the real ceiling and be
        truncated by exactly the amount the count failed to measure.
        """
        tokenizer = self._load().tokenizer
        return len(tokenizer.encode(text))

    def _encode(self, texts: list[str]) -> np.ndarray:
        model = self._load()
        vectors = model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        array = np.asarray(vectors, dtype=np.float32)
        if array.ndim != 2 or array.shape[1] != EMBEDDING_DIM:
            raise EmbeddingContractError(
                f"encoder returned shape {array.shape}, expected (n, {EMBEDDING_DIM})"
            )
        norms = np.linalg.norm(array, axis=1)
        worst = float(np.max(np.abs(norms - 1.0))) if len(norms) else 0.0
        if worst >= _NORM_TOLERANCE:
            raise EmbeddingContractError(
                f"embeddings are not unit vectors (worst deviation {worst:.3g}); "
                "ck_chunks_unit_norm would reject these at INSERT (ADR-0002)"
            )
        return array

    def encode_passages(self, texts: list[str]) -> np.ndarray:
        """Encode chunk text. No prefix — ADR-0002 forbids it on the passage side."""
        if not texts:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        return self._encode(texts)

    def encode_query(self, text: str) -> np.ndarray:
        """Encode a search query. The BGE instruction prefix is mandatory here."""
        return np.asarray(self._encode([QUERY_PREFIX + text])[0], dtype=np.float32)
