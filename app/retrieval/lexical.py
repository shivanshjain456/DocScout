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
import structlog

from app.retrieval.types import ChunkMeta, MetadataFilter
from app.rowtypes import as_int, as_str

logger = structlog.get_logger(__name__)

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
        self._chunk_meta: dict[str, ChunkMeta] = {}
        self._lexemes_by_chunk: dict[str, set[str]] | None = None
        self._build(conn)
        self._n = len(self._doc_len)
        self._avgdl = (sum(self._doc_len.values()) / self._n) if self._n else 0.0

    def _build(self, conn: psycopg.Connection[tuple[object, ...]]) -> None:
        # array_length over an empty/NULL positions array yields NULL, which happens for
        # lexemes stored without positions; coalesce to 1 so such a term still counts once
        # rather than vanishing from the index.
        # Superseded versions are excluded here rather than filtered after scoring,
        # because their terms would otherwise distort the corpus statistics BM25 depends
        # on -- document frequency and average length -- and so change the score of every
        # current chunk, not merely add wrong rows to the result.
        has_tax_layer = False
        try:
            col_check = conn.execute(
                "SELECT 1 FROM information_schema.columns WHERE table_name='chunks' AND column_name='taxonomy_layer'"
            ).fetchone()
            has_tax_layer = col_check is not None
        except Exception:
            has_tax_layer = False

        query_sql = (
            """
            SELECT c.chunk_id::text,
                   c.document_id::text,
                   d.source,
                   d.published_date,
                   v.fetch_ts,
                   v.is_current,
                   d.canonical_url,
                   d.title,
                   d.is_synthetic,
                   u.lexeme,
                   COALESCE(array_length(u.positions, 1), 1) AS tf,
                   c.taxonomy_layer
            FROM chunks AS c
            JOIN document_versions AS v ON v.version_id = c.version_id
            JOIN documents AS d ON d.document_id = c.document_id,
                 unnest(c.tsv) AS u(lexeme, positions, weights)
            WHERE v.is_current
            """
            if has_tax_layer
            else """
            SELECT c.chunk_id::text,
                   c.document_id::text,
                   d.source,
                   d.published_date,
                   v.fetch_ts,
                   v.is_current,
                   d.canonical_url,
                   d.title,
                   d.is_synthetic,
                   u.lexeme,
                   COALESCE(array_length(u.positions, 1), 1) AS tf,
                   NULL::text AS taxonomy_layer
            FROM chunks AS c
            JOIN document_versions AS v ON v.version_id = c.version_id
            JOIN documents AS d ON d.document_id = c.document_id,
                 unnest(c.tsv) AS u(lexeme, positions, weights)
            WHERE v.is_current
            """
        )
        # Check if framework_control_crosswalk exists to link standard mappings to chunks
        chunk_stds: dict[str, set[str]] = defaultdict(set)
        try:
            cw_check = conn.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_name = 'framework_control_crosswalk'"
            ).fetchone()
            if cw_check is not None:
                cw_rows = conn.execute(
                    """
                    SELECT chunk_id::text, standard_id, source_framework, target_framework
                    FROM framework_control_crosswalk
                    WHERE chunk_id IS NOT NULL
                    """
                ).fetchall()
                for c_id, std_id, src_fw, tgt_fw in cw_rows:
                    if c_id:
                        c_str = as_str(c_id)
                        if std_id:
                            chunk_stds[c_str].add(as_str(std_id))
                        if src_fw:
                            chunk_stds[c_str].add(as_str(src_fw))
                        if tgt_fw:
                            chunk_stds[c_str].add(as_str(tgt_fw))
        except Exception as exc:
            logger.debug("crosswalk_standard_load_failed", error=str(exc))

        rows = conn.execute(query_sql).fetchall()
        for (
            chunk_id,
            document_id,
            source,
            pub_date,
            fetch_ts,
            is_current,
            canon_url,
            doc_title,
            is_synthetic,
            lexeme,
            tf,
            tax_layer,
        ) in rows:
            cid = as_str(chunk_id)
            if cid not in self._chunk_meta:
                self._chunk_meta[cid] = ChunkMeta(
                    chunk_id=cid,
                    document_id=as_str(document_id),
                    source=as_str(source),
                    published_date=pub_date,  # type: ignore[arg-type]
                    fetch_ts=fetch_ts,  # type: ignore[arg-type]
                    is_current=bool(is_current),
                    canonical_url=as_str(canon_url) if canon_url is not None else None,
                    title=as_str(doc_title) if doc_title is not None else None,
                    is_synthetic=bool(is_synthetic),
                    taxonomy_layer=as_str(tax_layer) if tax_layer is not None else None,
                    standard_ids=tuple(sorted(chunk_stds.get(cid, set()))),
                )

            count = as_int(tf)
            self._postings[as_str(lexeme)].append(_Posting(cid, count))
            self._doc_len[cid] += count

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
        self,
        conn: psycopg.Connection[tuple[object, ...]],
        query: str,
        k: int,
        filter: MetadataFilter | None = None,
    ) -> list[tuple[str, float]]:
        """Return the top-k (chunk_id, score), highest first.

        If a filter is provided, candidate chunks are checked against its metadata
        during posting iteration, skipping disqualified candidates before accumulation.
        """
        matching_cids: set[str] | None = None
        if filter is not None and filter.standard is not None:
            from app.compliance.standards_registry import get_default_standards_registry

            std = get_default_standards_registry().get_standard(filter.standard)
            match_keys = {
                filter.standard,
                filter.standard.lower(),
                filter.standard.upper(),
                filter.standard.replace("-", "_"),
                filter.standard.replace("_", " "),
            }
            if std is not None:
                match_keys.add(std.id)
                match_keys.add(std.name)
                for a in std.aliases:
                    match_keys.add(a)
            clean_keys = list({k for k in match_keys if k})
            try:
                cw_rows = conn.execute(
                    """
                    SELECT DISTINCT chunk_id::text
                    FROM framework_control_crosswalk
                    WHERE chunk_id IS NOT NULL
                      AND (standard_id = ANY(%(keys)s) OR source_framework = ANY(%(keys)s) OR target_framework = ANY(%(keys)s))
                    """,
                    {"keys": clean_keys},
                ).fetchall()
                matching_cids = {as_str(r[0]) for r in cw_rows if r[0]}
            except Exception:
                matching_cids = None

        scores: dict[str, float] = defaultdict(float)
        for term in self.query_terms(conn, query):
            idf = self._idf(term)
            if idf == 0.0:
                continue
            for posting in self._postings[term]:
                if matching_cids is not None and posting.chunk_id not in matching_cids:
                    continue
                if filter is not None and not filter.matches(
                    self._chunk_meta.get(posting.chunk_id)
                ):
                    continue
                dl = self._doc_len[posting.chunk_id]
                denom = posting.tf + K1 * (1.0 - B + B * dl / self._avgdl)
                scores[posting.chunk_id] += idf * posting.tf * (K1 + 1.0) / denom
        # Ties broken by chunk_id so a run is reproducible; dict iteration order would
        # otherwise leak insertion order into the ranking.
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        return ranked[:k]
