"""Okapi BM25 over the lexemes Postgres already stores in chunks.tsv.

Why BM25 at all: the ADR-0002 bake-off measured BM25 at R@5 = 1.000 against dense at
0.945 on this corpus. Regulatory text is full of exact tokens -- circular numbers, section
references, "T+1", percentages -- where lexical matching is not a weaker form of semantic
matching but a better one. Dropping the lexical arm would lose measured recall.

Why the term statistics come from `chunks.tsv` rather than from a Python tokenizer:
tsv is a generated column computed by `to_tsvector('english', ...)`, the same expression
the GIN index is built on. Tokenizing again in Python would create a second, silently
divergent notion of what a term is -- the classic failure where the index and the scorer
disagree about stemming and a query that should match returns nothing. Here there is one
tokenizer, and it is the database's.

Why the statistics are parsed by Postgres (`unnest(tsvector)`) rather than by a regex over
tsv::text: the text form quotes and escapes lexemes ('it''s':4) and decorates positions
with weight letters (:3A). A hand-rolled parser for that is a bug waiting to be found by
the one document that contains an apostrophe.

Why not Postgres's own ts_rank_cd instead of BM25: ts_rank_cd is not BM25 and has no
document-length normalisation or IDF saturation; its scores are not comparable to anything
in the literature. Since fusion only needs a ranking, either would "work", but the brief
and ADR-0006 commit to BM25 and the numbers should mean what their name says.

Scaling limit, stated rather than hidden: this builds the full term-frequency table in
memory at construction (one query, 170 chunks, ~30k rows here). That is the right trade at
this corpus size and the wrong one at a million chunks, where the lexical arm should move
to a real BM25 index (ParadeDB's pg_search, OpenSearch). The interface below does not
change when that happens -- `search()` takes a query and returns ranked chunk ids.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

import psycopg

from app.rowtypes import as_int, as_str

# Okapi BM25's standard parameters. k1 controls term-frequency saturation, b controls how
# strongly document length is normalised. These are the canonical defaults and are held
# fixed so the retrieval A/B varies the architecture, not the constants.
K1 = 1.2
B = 0.75


@dataclass(frozen=True)
class _Posting:
    chunk_id: str
    tf: int


class BM25Index:
    """An in-memory BM25 index built from the database's own lexemes."""

    def __init__(self, conn: psycopg.Connection[tuple[object, ...]]) -> None:
        self._postings: dict[str, list[_Posting]] = defaultdict(list)
        self._doc_len: dict[str, int] = defaultdict(int)
        self._lexemes_by_chunk: dict[str, set[str]] | None = None
        self._build(conn)
        self._n = len(self._doc_len)
        self._avgdl = (sum(self._doc_len.values()) / self._n) if self._n else 0.0

    def _build(self, conn: psycopg.Connection[tuple[object, ...]]) -> None:
        # array_length over an empty/NULL positions array yields NULL, which happens for
        # lexemes stored without positions; coalesce to 1 so such a term still counts once
        # rather than vanishing from the index.
        rows = conn.execute(
            """
            SELECT c.chunk_id::text,
                   u.lexeme,
                   COALESCE(array_length(u.positions, 1), 1) AS tf
            FROM chunks AS c, unnest(c.tsv) AS u(lexeme, positions, weights)
            """
        ).fetchall()
        for chunk_id, lexeme, tf in rows:
            count = as_int(tf)
            self._postings[as_str(lexeme)].append(_Posting(as_str(chunk_id), count))
            self._doc_len[as_str(chunk_id)] += count

    def lexemes_of(self, chunk_id: str) -> set[str]:
        """The analyzed terms of one chunk.

        Exposed because measuring how much of a question appears verbatim in its own gold
        chunk is the only way to tell a retriever that understands the question from one
        that is being handed the answer's vocabulary. Built from the postings already in
        memory rather than re-querying.
        """
        if self._lexemes_by_chunk is None:
            table: dict[str, set[str]] = {}
            for lexeme, postings in self._postings.items():
                for posting in postings:
                    table.setdefault(posting.chunk_id, set()).add(lexeme)
            self._lexemes_by_chunk = table
        return self._lexemes_by_chunk.get(chunk_id, set())

    @property
    def n_documents(self) -> int:
        return self._n

    @property
    def average_length(self) -> float:
        return self._avgdl

    def _idf(self, term: str) -> float:
        df = len(self._postings.get(term, ()))
        if df == 0:
            return 0.0
        # Robertson/Sparck-Jones IDF in the +1 form, which cannot go negative. The bare
        # form does go negative for terms in more than half the documents, which on a
        # 170-chunk corpus of near-identical circulars would let a common term actively
        # push a correct chunk down the ranking.
        return math.log(1.0 + (self._n - df + 0.5) / (df + 0.5))

    def query_terms(self, conn: psycopg.Connection[tuple[object, ...]], query: str) -> list[str]:
        """Lexemes for a query, produced by the same analyzer that produced the index."""
        rows = conn.execute(
            "SELECT u.lexeme FROM unnest(to_tsvector('english', %s)) AS u(lexeme, positions, weights)",
            (query,),
        ).fetchall()
        return [as_str(r[0]) for r in rows]

    def search(
        self, conn: psycopg.Connection[tuple[object, ...]], query: str, k: int
    ) -> list[tuple[str, float]]:
        """Return the top-k (chunk_id, score), highest first."""
        scores: dict[str, float] = defaultdict(float)
        for term in self.query_terms(conn, query):
            idf = self._idf(term)
            if idf == 0.0:
                continue
            for posting in self._postings[term]:
                dl = self._doc_len[posting.chunk_id]
                denom = posting.tf + K1 * (1.0 - B + B * dl / self._avgdl)
                scores[posting.chunk_id] += idf * posting.tf * (K1 + 1.0) / denom
        # Ties broken by chunk_id so a run is reproducible; dict iteration order would
        # otherwise leak insertion order into the ranking.
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        return ranked[:k]
