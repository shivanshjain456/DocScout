#!/usr/bin/env python
"""U-9 decision experiment: which embedding model, and therefore which vector dimension.

This is a ONE-OFF DECISION EXPERIMENT, not production code and not the evaluation harness.
It exists to produce evidence for docs/decisions/0002-embedding-model-and-dimension.md.
Nothing in app/ imports it. The chunker here is a crude fixed-width placeholder and decides
NOTHING about U-8; it is held constant so that the only variable across arms is the model.

What it measures, per candidate:
  quality  - Recall@1/@5 and MRR on two independent probe sets (hand-written, and automated
             masked-sentence known-item retrieval), plus a BM25 lexical control arm
  cost     - model load time, peak RSS, corpus encode throughput, single-query p50/p95 latency
  fit      - max sequence length, truncation rate at this chunk size, bytes/vector, projected
             pgvector index size

Run:  uv run python scripts/experiments/u9_embedding_bakeoff.py
"""

from __future__ import annotations

import gc
import json
import random
import re
import statistics
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
CORPUS = REPO / "corpus" / "raw"
OUT_JSON = REPO / "docs" / "decisions" / "evidence" / "u9-embedding-bakeoff.json"

SEED = 20261001
CHUNK_CHARS = 1000  # experiment-only; does not decide U-8
PROBE_B_COUNT = 200
MIN_SENT_CHARS = 60

# Candidates. `qp`/`pp` are the model's documented query/passage instruction prefixes; applying
# them is not optional - BGE and E5 are trained with them and omitting them is a silent handicap.
CANDIDATES: list[dict[str, Any]] = [
    {
        "key": "bge-small-en-v1.5",
        "repo": "BAAI/bge-small-en-v1.5",
        "dim": 384,
        "qp": "Represent this sentence for searching relevant passages: ",
        "pp": "",
        "why": "Phase 0 incumbent; the model config/models.json already names",
    },
    {
        "key": "all-MiniLM-L6-v2",
        "repo": "sentence-transformers/all-MiniLM-L6-v2",
        "dim": 384,
        "qp": "",
        "pp": "",
        "why": "config/models.json claims bge was 'chosen over' this, citing no measurement",
    },
    {
        "key": "bge-base-en-v1.5",
        "repo": "BAAI/bge-base-en-v1.5",
        "dim": 768,
        "qp": "Represent this sentence for searching relevant passages: ",
        "pp": "",
        "why": "does doubling D buy retrieval quality on this corpus?",
    },
    {
        "key": "multilingual-e5-small",
        "repo": "intfloat/multilingual-e5-small",
        "dim": 384,
        "qp": "query: ",
        "pp": "passage: ",
        "why": "corpus is 2.5% Devanagari and one doc is 33%; test it rather than assume",
    },
]

# 21 hand-written queries, one or more per real document, gold label verified by reading the
# source text. 'lex' reuses the document's own terminology (a realistic keyword search);
# 'para' deliberately avoids it (a realistic natural-language question). The split matters:
# lexical overlap flatters BM25, so reporting a single blended number would mislead.
HAND_PROBES: list[tuple[str, int, str]] = [
    ("Can a bank swap ATM cassettes instead of loading loose notes at the machine?", 2, "para"),
    ("Cassette swaps in ATMs", 2, "lex"),
    ("Which currency management circulars has the RBI withdrawn?", 1, "para"),
    ("Credit facilities to Scheduled Castes and Scheduled Tribes", 3, "lex"),
    ("What must a bank do when the UN sanctions list for ISIL and Al-Qaida changes?", 4, "para"),
    ("How is an organisation designated as a terrorist organisation under UAPA?", 6, "para"),
    ("What changed in the FEMA regulations on export and import of goods and services?", 5, "para"),
    ("Exim Bank line of credit to Maldives for developmental projects", 7, "lex"),
    ("Investment portfolio classification rules for payments banks", 9, "lex"),
    ("Small Finance Banks classification valuation investment portfolio amendment", 10, "lex"),
    (
        "Classification and valuation of investment portfolio of all India financial institutions",
        8,
        "lex",
    ),
    ("Can a foreign portfolio investor submit a power of attorney signed digitally?", 11, "para"),
    ("Where do I report a cyber incident to SEBI, and in which format?", 12, "para"),
    ("Amendment to the regulations on issue and listing of municipal debt securities", 13, "lex"),
    ("Are KYC registration agencies allowed to share data with IFSCA regulated firms?", 14, "para"),
    ("Has the deadline for research analysts to enrol with PaRRVA been pushed back?", 15, "para"),
    ("Extension of timeline for base price, price bands and call auction norms", 16, "lex"),
    ("How should an InvIT compute its net distributable cash flows?", 17, "para"),
    ("IT Resilience Index for Market Infrastructure Institutions", 18, "lex"),
    ("What has changed for online bond platform providers?", 19, "para"),
    ("Historical scenarios in stress testing for the commodity derivatives segment", 20, "lex"),
]


@dataclass
class Chunk:
    chunk_id: int
    doc_n: int
    source: str
    text: str


@dataclass
class ArmResult:
    key: str
    repo: str
    dim: int
    note: str = ""
    load_s: float = 0.0
    peak_rss_mb: float = 0.0
    max_seq_tokens: int | None = None
    truncated_chunks: int = 0
    encode_chunks_s: float = 0.0
    chunks_per_s: float = 0.0
    query_ms_p50: float = 0.0
    query_ms_p95: float = 0.0
    bytes_per_vector: int = 0
    disk_mb: float = 0.0
    metrics: dict[str, Any] = field(default_factory=dict)
    probe_b_positions: list[int | None] = field(default_factory=list)
    probe_b_unmasked_positions: list[int | None] = field(default_factory=list)


def rss_peak_mb() -> float:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmHWM:"):
            return int(line.split()[1]) / 1024
    return 0.0


def load_corpus() -> tuple[list[Chunk], dict[int, str]]:
    manifest = json.loads((CORPUS / "manifest.json").read_text())
    chunks: list[Chunk] = []
    titles: dict[int, str] = {}
    cid = 0
    for doc in manifest["documents"]:
        if not doc.get("ok"):
            continue
        base = REPO / doc["local_path"]
        txt_path = Path(str(base) + ".txt")
        if not txt_path.exists() and base.suffix == ".txt" and base.exists():
            txt_path = base  # the canary is already a .txt; do not double-suffix it
        if not txt_path.exists():
            print(f"  WARN missing text for doc {doc['n']}", file=sys.stderr)
            continue
        raw = txt_path.read_text(errors="replace")
        text = re.sub(r"[ \t]+", " ", raw)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        titles[doc["n"]] = doc.get("url", "")
        # Non-overlapping fixed-width chunks on whitespace boundaries. Non-overlapping is a
        # deliberate choice: probe set B masks a sentence from its source chunk, and overlap
        # would leak that sentence into a neighbour and silently inflate every arm's recall.
        pos = 0
        while pos < len(text):
            end = min(pos + CHUNK_CHARS, len(text))
            if end < len(text):
                space = text.rfind(" ", pos + CHUNK_CHARS // 2, end)
                if space > pos:
                    end = space
            piece = text[pos:end].strip()
            if len(piece) >= 50:
                chunks.append(Chunk(cid, doc["n"], doc["source"], piece))
                cid += 1
            pos = end
    return chunks, titles


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.;:])\s+", text)
    return [p.strip() for p in parts if len(p.strip()) >= MIN_SENT_CHARS]


def build_probe_b(chunks: list[Chunk]) -> tuple[list[tuple[str, int]], list[Chunk]]:
    """Masked-sentence known-item probes.

    For each selected chunk, lift one sentence out to serve as the query and DELETE it from the
    indexed copy of that chunk. The model therefore cannot win by matching the sentence to
    itself; it has to match the sentence to the surrounding context. Sentences that occur more
    than once in the corpus are rejected, otherwise the gold label would be ambiguous.
    """
    rng = random.Random(SEED)  # noqa: S311 - experiment sampling, not security
    corpus_text = "\n".join(c.text for c in chunks)
    candidates = []
    for ch in chunks:
        sents = sentences(ch.text)
        if len(sents) < 2:
            continue
        for s in sents:
            if corpus_text.count(s) == 1:
                candidates.append((ch.chunk_id, s))
                break
    rng.shuffle(candidates)
    chosen = candidates[:PROBE_B_COUNT]
    masked = {cid: s for cid, s in chosen}
    index_chunks = [
        Chunk(
            c.chunk_id,
            c.doc_n,
            c.source,
            c.text.replace(masked[c.chunk_id], " ").strip() if c.chunk_id in masked else c.text,
        )
        for c in chunks
    ]
    probes = [(s, cid) for cid, s in chosen]
    return probes, index_chunks


def score_ranking(ranked_gold_positions: list[int | None], ks: tuple[int, ...]) -> dict[str, float]:
    n = len(ranked_gold_positions)
    out: dict[str, float] = {}
    for k in ks:
        hits = sum(1 for p in ranked_gold_positions if p is not None and p < k)
        out[f"recall@{k}"] = round(hits / n, 4)
    mrr = sum(1.0 / (p + 1) for p in ranked_gold_positions if p is not None) / n
    out["mrr"] = round(mrr, 4)
    out["n"] = n
    return out


def rank_probe_b(
    sims: Any, probes_b: list[tuple[str, int]], pool: list[Chunk], np: Any
) -> list[int | None]:
    out: list[int | None] = []
    for row, (_q, gold_cid) in enumerate(probes_b):
        order = np.argsort(-sims[row])[:10]
        ids = [pool[int(i)].chunk_id for i in order]
        out.append(ids.index(gold_cid) if gold_cid in ids else None)
    return out


def model_disk_mb(repo: str) -> float:
    """On-disk size of the cached snapshot. Deterministic, unlike an RSS high-water mark."""
    cache = Path.home() / ".cache" / "huggingface" / "hub" / ("models--" + repo.replace("/", "--"))
    if not cache.exists():
        return 0.0
    total = sum(f.stat().st_size for f in cache.rglob("*") if f.is_file() and not f.is_symlink())
    return round(total / 1_048_576, 1)


def paired_stats(
    base: list[int | None], other: list[int | None], seed: int = SEED, iters: int = 10000
) -> dict[str, Any]:
    """Paired bootstrap on the SAME probes, plus an exact McNemar on rank-1 hits.

    Two arms are compared on identical queries, so an unpaired comparison would overstate the
    uncertainty. This answers the only question that matters here: is the gap real, or noise?
    """
    rng = random.Random(seed)  # noqa: S311 - resampling for a CI, not security
    n = len(base)
    hb = [1 if p == 0 else 0 for p in base]
    ho = [1 if p == 0 else 0 for p in other]
    rb = [0.0 if p is None else 1.0 / (p + 1) for p in base]
    ro = [0.0 if p is None else 1.0 / (p + 1) for p in other]
    d_r1, d_mrr = [], []
    for _ in range(iters):
        idx = [rng.randrange(n) for _ in range(n)]
        d_r1.append(sum(ho[i] - hb[i] for i in idx) / n)
        d_mrr.append(sum(ro[i] - rb[i] for i in idx) / n)
    d_r1.sort()
    d_mrr.sort()
    lo, hi = int(0.025 * iters), int(0.975 * iters) - 1
    b_only = sum(1 for i in range(n) if hb[i] and not ho[i])
    o_only = sum(1 for i in range(n) if ho[i] and not hb[i])
    # exact two-sided binomial p on the discordant pairs
    m = b_only + o_only
    if m == 0:
        pval = 1.0
    else:
        from math import comb

        k = min(b_only, o_only)
        pval = min(1.0, 2 * sum(comb(m, i) for i in range(k + 1)) / (2**m))
    return {
        "delta_recall@1": round(sum(ho) / n - sum(hb) / n, 4),
        "delta_recall@1_ci95": [round(d_r1[lo], 4), round(d_r1[hi], 4)],
        "delta_mrr": round(sum(ro) / n - sum(rb) / n, 4),
        "delta_mrr_ci95": [round(d_mrr[lo], 4), round(d_mrr[hi], 4)],
        "mcnemar_discordant": [b_only, o_only],
        "mcnemar_p": round(pval, 4),
        "significant_at_0.05": bool(pval < 0.05),
    }


def eval_bm25(
    chunks: list[Chunk], index_chunks: list[Chunk], probes_b: list[tuple[str, int]]
) -> ArmResult:
    from rank_bm25 import BM25Okapi

    def tok(s: str) -> list[str]:
        s = unicodedata.normalize("NFKC", s).lower()
        return re.findall(r"[a-z0-9₹]+", s)

    arm = ArmResult(
        key="bm25-okapi",
        repo="rank-bm25 (lexical control)",
        dim=0,
        note="no vectors; control arm answering 'are embeddings needed at all?'",
    )
    t0 = time.perf_counter()
    bm_b = BM25Okapi([tok(c.text) for c in index_chunks])
    bm_a = BM25Okapi([tok(c.text) for c in chunks])
    arm.encode_chunks_s = round(time.perf_counter() - t0, 3)

    lat = []
    pos_a: list[int | None] = []
    for q, gold_doc, _kind in HAND_PROBES:
        t = time.perf_counter()
        scores = bm_a.get_scores(tok(q))
        lat.append((time.perf_counter() - t) * 1000)
        order = sorted(range(len(chunks)), key=lambda i: -scores[i])
        seen: list[int] = []
        for i in order:
            if chunks[i].doc_n not in seen:
                seen.append(chunks[i].doc_n)
            if len(seen) >= 10:
                break
        pos_a.append(seen.index(gold_doc) if gold_doc in seen else None)

    pos_b: list[int | None] = []
    for q, gold_cid in probes_b:
        scores = bm_b.get_scores(tok(q))
        order = sorted(range(len(index_chunks)), key=lambda i: -scores[i])[:10]
        ids = [index_chunks[i].chunk_id for i in order]
        pos_b.append(ids.index(gold_cid) if gold_cid in ids else None)

    pos_b_un: list[int | None] = []
    for q, gold_cid in probes_b:
        scores = bm_a.get_scores(tok(q))
        order = sorted(range(len(chunks)), key=lambda i: -scores[i])[:10]
        ids = [chunks[i].chunk_id for i in order]
        pos_b_un.append(ids.index(gold_cid) if gold_cid in ids else None)

    arm.query_ms_p50 = round(statistics.median(lat), 2)
    arm.query_ms_p95 = round(sorted(lat)[max(0, int(len(lat) * 0.95) - 1)], 2)
    arm.probe_b_positions = pos_b
    arm.probe_b_unmasked_positions = pos_b_un
    arm.metrics = {
        "probe_a_doc_level": score_ranking(pos_a, (1, 3, 5)),
        "probe_b_chunk_level": score_ranking(pos_b, (1, 5, 10)),
        "probe_b_unmasked_control": score_ranking(pos_b_un, (1, 5)),
        "probe_a_by_kind": by_kind(pos_a),
    }
    return arm


def by_kind(pos_a: list[int | None]) -> dict[str, Any]:
    out = {}
    for kind in ("lex", "para"):
        idx = [i for i, (_q, _g, k) in enumerate(HAND_PROBES) if k == kind]
        out[kind] = score_ranking([pos_a[i] for i in idx], (1, 5))
    return out


def eval_model(
    cand: dict[str, Any],
    chunks: list[Chunk],
    index_chunks: list[Chunk],
    probes_b: list[tuple[str, int]],
) -> ArmResult:
    import numpy as np
    from sentence_transformers import SentenceTransformer

    arm = ArmResult(key=cand["key"], repo=cand["repo"], dim=cand["dim"], note=cand["why"])
    rss_before = rss_peak_mb()
    t0 = time.perf_counter()
    model = SentenceTransformer(cand["repo"], device="cpu")
    arm.load_s = round(time.perf_counter() - t0, 2)
    arm.max_seq_tokens = int(model.max_seq_length)
    arm.peak_rss_mb = round(max(rss_peak_mb() - rss_before, 0.0), 1)

    tokenizer = model.tokenizer
    lens = [len(tokenizer.encode(c.text)) for c in chunks]
    arm.truncated_chunks = sum(1 for n in lens if n > arm.max_seq_tokens)

    def embed(texts: list[str], prefix: str) -> Any:
        return model.encode(
            [prefix + t for t in texts],
            batch_size=16,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )

    t0 = time.perf_counter()
    emb_a = embed([c.text for c in chunks], cand["pp"])
    arm.encode_chunks_s = round(time.perf_counter() - t0, 2)
    arm.chunks_per_s = round(len(chunks) / arm.encode_chunks_s, 1)
    arm.bytes_per_vector = int(emb_a.shape[1]) * 4
    emb_b = embed([c.text for c in index_chunks], cand["pp"])

    # Single-query latency is what production p95 sees; batch throughput is not a substitute.
    lat = []
    pos_a: list[int | None] = []
    for q, gold_doc, _kind in HAND_PROBES:
        t = time.perf_counter()
        qv = model.encode(
            [cand["qp"] + q],
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )[0]
        lat.append((time.perf_counter() - t) * 1000)
        sims = emb_a @ qv
        order = np.argsort(-sims)
        seen: list[int] = []
        for i in order:
            d = chunks[int(i)].doc_n
            if d not in seen:
                seen.append(d)
            if len(seen) >= 10:
                break
        pos_a.append(seen.index(gold_doc) if gold_doc in seen else None)
    arm.query_ms_p50 = round(statistics.median(lat), 2)
    arm.query_ms_p95 = round(sorted(lat)[max(0, int(len(lat) * 0.95) - 1)], 2)

    qv_b = embed([q for q, _ in probes_b], cand["qp"])
    pos_b = rank_probe_b(qv_b @ emb_b.T, probes_b, index_chunks, np)
    # Control: the SAME probes against the UNMASKED corpus. The query sentence is then present
    # verbatim in its gold chunk, so any sane retriever must score near 1.0. If it does not, the
    # harness is broken and none of the masked numbers mean anything.
    pos_b_un = rank_probe_b(qv_b @ emb_a.T, probes_b, chunks, np)

    arm.disk_mb = model_disk_mb(cand["repo"])
    arm.probe_b_positions = pos_b
    arm.probe_b_unmasked_positions = pos_b_un
    arm.metrics = {
        "probe_a_doc_level": score_ranking(pos_a, (1, 3, 5)),
        "probe_b_chunk_level": score_ranking(pos_b, (1, 5, 10)),
        "probe_b_unmasked_control": score_ranking(pos_b_un, (1, 5)),
        "probe_a_by_kind": by_kind(pos_a),
    }
    del emb_a, emb_b, qv_b
    gc.collect()
    return arm


def main() -> int:
    import torch

    torch.set_num_threads(2)
    chunks, _titles = load_corpus()
    probes_b, index_chunks = build_probe_b(chunks)
    print(
        f"corpus: {len(chunks)} chunks from {len({c.doc_n for c in chunks})} docs; "
        f"probe A: {len(HAND_PROBES)} hand-written; probe B: {len(probes_b)} masked-sentence"
    )

    arms: list[ArmResult] = [eval_bm25(chunks, index_chunks, probes_b)]
    print(f"  [bm25] done  R@1(doc)={arms[0].metrics['probe_a_doc_level']['recall@1']}")
    for cand in CANDIDATES:
        print(f"  [{cand['key']}] loading ...", flush=True)
        try:
            arm = eval_model(cand, chunks, index_chunks, probes_b)
        except Exception as exc:  # noqa: BLE001 - an arm failing must not void the whole run
            arm = ArmResult(
                key=cand["key"],
                repo=cand["repo"],
                dim=cand["dim"],
                note=f"ARM FAILED: {type(exc).__name__}: {exc}",
            )
            print(f"  [{cand['key']}] FAILED: {exc}", file=sys.stderr)
        arms.append(arm)
        m = arm.metrics.get("probe_a_doc_level", {})
        print(
            f"  [{arm.key}] R@1(doc)={m.get('recall@1')} "
            f"R@1(chunk)={arm.metrics.get('probe_b_chunk_level', {}).get('recall@1')} "
            f"q_p95={arm.query_ms_p95}ms rss={arm.peak_rss_mb}MB",
            flush=True,
        )

    incumbent = next(a for a in arms if a.key == "bge-small-en-v1.5")
    pairwise = {
        a.key: paired_stats(incumbent.probe_b_positions, a.probe_b_positions)
        for a in arms
        if a.key != incumbent.key and a.probe_b_positions
    }

    payload = {
        "experiment": "U-9 embedding model and vector dimension bake-off",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "DECISION EXPERIMENT - not the evaluation harness, not production code",
        "seed": SEED,
        "corpus": {
            "chunks": len(chunks),
            "docs": len({c.doc_n for c in chunks}),
            "chunk_chars": CHUNK_CHARS,
            "chunking": "fixed-width, non-overlapping, whitespace boundary; placeholder, U-8 undecided",
            "total_chars": sum(len(c.text) for c in chunks),
        },
        "probe_sets": {
            "A": {"kind": "hand-written queries, document-level gold", "n": len(HAND_PROBES)},
            "B": {"kind": "masked-sentence known-item, chunk-level gold", "n": len(probes_b)},
        },
        "arms": [asdict(a) for a in arms],
        "pairwise_vs_incumbent": pairwise,
        "index_size_projection": {
            "note": "pgvector stores 4 bytes/dimension + 8 bytes overhead per vector; HNSW adds"
            " roughly 1.5x on top. Chunk counts are illustrative, C-5 is UNRESOLVED.",
            "per_dim": {
                str(d): {
                    "bytes_per_vector": d * 4 + 8,
                    "mb_at_10k_chunks": round((d * 4 + 8) * 10_000 * 2.5 / 1_048_576, 1),
                    "mb_at_100k_chunks": round((d * 4 + 8) * 100_000 * 2.5 / 1_048_576, 1),
                }
                for d in (384, 768)
            },
        },
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\nwrote {OUT_JSON.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
