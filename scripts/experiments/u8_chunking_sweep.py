#!/usr/bin/env python
"""U-8 decision experiment: chunk size, overlap, and structural awareness.

ONE-OFF DECISION EXPERIMENT, not production code. Evidence for
docs/decisions/0003-chunking-strategy.md. Nothing in app/ imports it.

The methodological problem this harness exists to solve
-------------------------------------------------------
You cannot compare chunking configurations using chunk-level gold labels, because the unit of
retrieval changes with the configuration: bigger chunks mean fewer candidates and more text per
candidate, so "recall@1 over chunks" silently rewards larger chunks for being larger. Every
number would be apples to oranges.

So gold here is a CHARACTER SPAN in a document, fixed once, before any chunker runs. A retrieval
counts as correct when the retrieved chunk's [start, end) covers the span. That definition is
identical for every configuration, which is what makes the sweep legitimate. It also mirrors the
real schema: ARCHITECTURE.md already gives chunks char_start and char_end.

Masking preserves offsets. Each probe sentence is replaced in the indexed text by an equal number
of spaces, never deleted, so a span measured in the original text still points at the same place
in every configuration.

Bigger chunks win recall almost by definition - a 1200-char chunk covers a span a 400-char chunk
misses. Recall alone would therefore pick the largest chunk every time. So the sweep also reports
citation tightness (how much irrelevant text a citation drags in) and context cost (characters
needed to put top-5 in a prompt), because QUALITY_BAR.md gates citation precision at >= 0.90 and
a citation that points at 1200 characters of unrelated boilerplate is not a useful citation.

Every configuration is scored under three retrievers - BM25, dense vector, and RRF(60) - so the
decision can be checked for robustness against U-10, which is still open.

Method v2. The first pass had three defects, all corrected here:
  - it masked all 200 probes at once, blanking 26% of the corpus and starving retrieval of the
    context it was being asked to match. Probes are now masked in 4 disjoint batches, so only
    ~6% of the corpus is blank in any pass.
  - it derived chunk boundaries from the masked text. Geometry is now computed once from the
    clean, unmasked text, exactly as production would, and shared by every retrieval variant.
  - it never measured span integrity - whether an answer span survives chunking intact in some
    chunk. That is deterministic, needs no retrieval, and is the sharpest argument about overlap,
    so it is now a first-class metric.

Run:  uv run python scripts/experiments/u8_chunking_sweep.py
"""

from __future__ import annotations

import json
import os
import re
import statistics
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
CORPUS = REPO / "corpus" / "raw"
OUT_JSON = REPO / "docs" / "decisions" / "evidence" / "u8-chunking-sweep.json"

SEED = 20261001
MODEL = "BAAI/bge-small-en-v1.5"  # pinned by ADR-0002
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
MAX_TOKENS = 512  # ADR-0002: the hard ceiling this decision must respect
RRF_K = 60
N_PROBES = 200
N_BATCHES = 4  # disjoint masking batches, to keep the corpus mostly intact in each pass
MIN_SENT, MAX_SENT = 60, 320
OVERLAP_MIN_FRAC = 0.5  # a hit must cover at least half the gold span

# Characters that never occur in clean English regulatory prose but do occur in these PDFs:
# Devanagari, plus the Latin-Extended/IPA blocks that legacy Indic font encodings leak as mojibake.
NOISE_RANGES = ((0x0900, 0x097F), (0x0180, 0x024F), (0x02B0, 0x02FF), (0xFFFD, 0xFFFD))
PAGE_FURNITURE = re.compile(r"(?i)\bPage\s+\d+\s+of\s+\d+\b|\bपृ.{0,3}ठ\s*सं\.?\s*\d+")

CLAUSE = re.compile(r'(?:(?<=\.)|(?<=\n)|(?<=^)|(?<=:))\s{0,3}(\d{1,2})\.\s+(?=[A-Z\u201c"(])')


@dataclass
class Chunk:
    doc_n: int
    start: int
    end: int
    text: str


@dataclass
class Probe:
    doc_n: int
    start: int
    end: int
    text: str


@dataclass
class ConfigResult:
    name: str
    cleaning: str
    strategy: str
    target_chars: int
    overlap_chars: int
    n_chunks: int = 0
    mean_chars: float = 0.0
    p95_chars: int = 0
    mean_tokens: float = 0.0
    max_tokens: int = 0
    truncated: int = 0
    embed_s: float = 0.0
    index_mb_at_10k: float = 0.0
    citation_tightness: float = 0.0
    context_chars_top5: int = 0
    span_integrity: float = 0.0
    spans_split: int = 0
    per_probe: dict[str, list[int]] = field(default_factory=dict)
    retrievers: dict[str, Any] = field(default_factory=dict)
    doc_level: dict[str, Any] = field(default_factory=dict)


def noisy(ch: str) -> bool:
    o = ord(ch)
    return any(lo <= o <= hi for lo, hi in NOISE_RANGES)


def clean_preserving_offsets(text: str) -> str:
    """Blank out non-English furniture WITHOUT moving any character position."""
    out = ["  " if False else (" " if noisy(c) else c) for c in text]
    s = "".join(out)
    for m in PAGE_FURNITURE.finditer(s):
        s = s[: m.start()] + " " * (m.end() - m.start()) + s[m.end() :]
    return s


def canary_docs() -> set[int]:
    """The injection canary stays in the index as a distractor but must never be gold.

    It is a synthetic negative control: 'retrieving it successfully' is the failure the corpus
    harness exists to detect, so scoring a hit on it would invert the test.
    """
    manifest = json.loads((CORPUS / "manifest.json").read_text())
    return {d["n"] for d in manifest["documents"] if d.get("is_injection_canary")}


def load_docs() -> dict[int, str]:
    manifest = json.loads((CORPUS / "manifest.json").read_text())
    docs: dict[int, str] = {}
    for d in manifest["documents"]:
        if not d.get("ok"):
            continue
        base = REPO / d["local_path"]
        p = Path(str(base) + ".txt")
        if not p.exists() and base.suffix == ".txt" and base.exists():
            p = base
        if p.exists():
            docs[d["n"]] = unicodedata.normalize("NFKC", p.read_text(errors="replace"))
    return docs


def pick_probes(docs: dict[int, str]) -> list[Probe]:
    """Sentences with unambiguous, corpus-unique text, sampled evenly across documents."""
    whole = "\n".join(docs.values())
    skip = canary_docs()
    per_doc: dict[int, list[Probe]] = {}
    for n, t in docs.items():
        if n in skip:
            continue
        found: list[Probe] = []
        for m in re.finditer(rf"[^.;:]{{{MIN_SENT},{MAX_SENT}}}[.;:]", t):
            s = m.group(0).strip()
            if len(s) < MIN_SENT or whole.count(s) != 1:
                continue
            if sum(c.isalpha() and c.isascii() for c in s) < 0.6 * len(s):
                continue  # skip non-English / mojibake spans
            found.append(Probe(n, m.start(), m.end(), s))
        per_doc[n] = found
    probes: list[Probe] = []
    i = 0
    while len(probes) < N_PROBES and any(len(v) > i for v in per_doc.values()):
        for n in sorted(per_doc):
            if len(per_doc[n]) > i and len(probes) < N_PROBES:
                probes.append(per_doc[n][i])
        i += 1
    return probes


def mask(docs: dict[int, str], probes: list[Probe]) -> dict[int, str]:
    out = {n: list(t) for n, t in docs.items()}
    for p in probes:
        for i in range(p.start, p.end):
            out[p.doc_n][i] = " "
    return {n: "".join(v) for n, v in out.items()}


def chunk_fixed(docs: dict[int, str], size: int, overlap: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    step = max(1, size - overlap)
    for n, t in docs.items():
        pos = 0
        while pos < len(t):
            end = min(pos + size, len(t))
            if end < len(t):
                sp = t.rfind(" ", pos + size // 2, end)
                if sp > pos:
                    end = sp
            piece = t[pos:end]
            if piece.strip():
                chunks.append(Chunk(n, pos, end, piece.strip()))
            if end >= len(t):
                break
            pos = max(pos + step, end - overlap) if overlap else end
    return chunks


def clause_spans(t: str) -> list[int]:
    """Validated clause starts: the longest run of markers incrementing by one."""
    cands = [(m.start(), int(m.group(1))) for m in CLAUSE.finditer(t)]
    best: list[int] = []
    for i, (pos, num) in enumerate(cands):
        run, want = [pos], num + 1
        for pos2, n2 in cands[i + 1 :]:
            if n2 == want:
                run.append(pos2)
                want += 1
        if len(run) > len(best):
            best = run
    return best


def chunk_clause(docs: dict[int, str], cap: int) -> list[Chunk]:
    """Split on validated clause boundaries, then pack neighbours up to `cap`.

    Falls back to fixed-width inside any clause longer than the cap, so the 512-token ceiling
    holds even for documents whose structure did not survive extraction.
    """
    chunks: list[Chunk] = []
    for n, t in docs.items():
        bounds = [0, *clause_spans(t), len(t)]
        bounds = sorted(set(bounds))
        units = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]
        cur: tuple[int, int] | None = None
        for s, e in units:
            while e - s > cap:  # oversized clause: hard-split it
                if cur is not None:
                    piece = t[cur[0] : cur[1]]
                    if piece.strip():
                        chunks.append(Chunk(n, cur[0], cur[1], piece.strip()))
                    cur = None
                cut = t.rfind(" ", s + cap // 2, s + cap) or s + cap
                cut = cut if cut > s else s + cap
                if t[s:cut].strip():
                    chunks.append(Chunk(n, s, cut, t[s:cut].strip()))
                s = cut
            if cur is None:
                cur = (s, e)
            elif e - cur[0] <= cap:
                cur = (cur[0], e)
            else:
                piece = t[cur[0] : cur[1]]
                if piece.strip():
                    chunks.append(Chunk(n, cur[0], cur[1], piece.strip()))
                cur = (s, e)
        if cur is not None and t[cur[0] : cur[1]].strip():
            chunks.append(Chunk(n, cur[0], cur[1], t[cur[0] : cur[1]].strip()))
    return chunks


def covers(c: Chunk, p: Probe) -> bool:
    if c.doc_n != p.doc_n:
        return False
    ov = min(c.end, p.end) - max(c.start, p.start)
    return ov >= OVERLAP_MIN_FRAC * (p.end - p.start)


def fully(c: Chunk, p: Probe) -> bool:
    return c.doc_n == p.doc_n and c.start <= p.start and c.end >= p.end


def span_integrity(chunks: list[Chunk], probes: list[Probe]) -> tuple[float, int, list[int]]:
    """Fraction of gold spans that sit entirely inside at least one chunk.

    Deterministic geometry, no retrieval involved. A span split across a boundary can never be
    cited cleanly no matter how good the retriever is, so this is the honest measure of what a
    chunking configuration destroys before retrieval even starts.
    """
    by_doc: dict[int, list[Chunk]] = {}
    for c in chunks:
        by_doc.setdefault(c.doc_n, []).append(c)
    vec = [1 if any(fully(c, p) for c in by_doc.get(p.doc_n, [])) else 0 for p in probes]
    intact = sum(vec)
    return round(intact / len(probes), 4), len(probes) - intact, vec


def rank_metrics(
    ranked: list[list[int]], probes: list[Probe], chunks: list[Chunk]
) -> dict[str, Any]:
    r1 = r5 = full1 = 0
    mrr = 0.0
    tight: list[float] = []
    hits5: list[int] = []
    for order, p in zip(ranked, probes, strict=True):
        hit_rank = None
        for rank, ci in enumerate(order[:10]):
            if covers(chunks[ci], p):
                hit_rank = rank
                break
        if hit_rank is not None:
            mrr += 1 / (hit_rank + 1)
            if hit_rank == 0:
                r1 += 1
                c = chunks[order[0]]
                tight.append((p.end - p.start) / max(len(c.text), 1))
                if fully(c, p):
                    full1 += 1
            if hit_rank < 5:
                r5 += 1
        hits5.append(1 if (hit_rank is not None and hit_rank < 5) else 0)
    n = len(probes)
    return {
        "hits@5": hits5,
        "recall@1": round(r1 / n, 4),
        "recall@5": round(r5 / n, 4),
        "mrr": round(mrr / n, 4),
        "fully_contained@1": round(full1 / n, 4),
        "citation_tightness@1": round(statistics.mean(tight), 4) if tight else 0.0,
        "n": n,
    }


def rrf(*rankings: list[list[int]]) -> list[list[int]]:
    fused: list[list[int]] = []
    for row in zip(*rankings, strict=True):
        score: dict[int, float] = {}
        for order in row:
            for rank, ci in enumerate(order):
                score[ci] = score.get(ci, 0.0) + 1.0 / (RRF_K + rank + 1)
        fused.append(sorted(score, key=lambda c: -score[c])[:10])
    return fused


def main() -> int:  # noqa: C901
    import numpy as np
    import torch
    from rank_bm25 import BM25Okapi
    from sentence_transformers import SentenceTransformer

    torch.set_num_threads(2)
    raw = load_docs()
    cleaned = {n: clean_preserving_offsets(t) for n, t in raw.items()}
    blanked = sum(1 for n in raw for a, b in zip(raw[n], cleaned[n], strict=True) if a != b)
    total_chars = sum(len(t) for t in raw.values())
    print(f"docs={len(raw)} chars={total_chars:,} blanked_by_cleaning={blanked:,}")

    probes = pick_probes(cleaned)
    batches = [probes[i::N_BATCHES] for i in range(N_BATCHES)]
    masked_frac = max(sum(p.end - p.start for p in b) for b in batches) / total_chars
    print(
        f"probes={len(probes)} across {len({p.doc_n for p in probes})} docs "
        f"(canary {sorted(canary_docs())} indexed as distractor, never gold); "
        f"{N_BATCHES} batches, <={masked_frac:.1%} of corpus blank per pass"
    )

    model = SentenceTransformer(MODEL, device="cpu")
    tokzr = model.tokenizer
    qv = model.encode(
        [QUERY_PREFIX + p.text for p in probes],
        batch_size=16,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    qv_of = {id(p): qv[i] for i, p in enumerate(probes)}

    def tok(s: str) -> list[str]:
        return re.findall(r"[a-z0-9\u20b9]+", s.lower())

    def score(chunks: list[Chunk], texts: list[str], ps: list[Probe]) -> dict[str, Any]:
        emb = model.encode(
            texts,
            batch_size=16,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        q = np.stack([qv_of[id(p)] for p in ps])
        sims = q @ emb.T
        dense = [list(np.argsort(-sims[i])[:10]) for i in range(len(ps))]
        bm = BM25Okapi([tok(t) for t in texts])
        lex = [list(np.argsort(-bm.get_scores(tok(p.text)))[:10]) for p in ps]
        return {"dense": (dense, ps), "bm25": (lex, ps), "rrf60": (rrf(dense, lex), ps)}

    def pooled(parts: list[dict[str, Any]], chunks: list[Chunk]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key in ("dense", "bm25", "rrf60"):
            pairs: list[tuple[Probe, list[int]]] = []
            for part in parts:
                o, pp = part[key]
                pairs += list(zip(pp, o, strict=True))
            index = {id(p): i for i, p in enumerate(probes)}
            pairs.sort(key=lambda x: index[id(x[0])])
            out[key] = rank_metrics([o for _, o in pairs], [p for p, _ in pairs], chunks)
        return out

    configs: list[tuple[str, str, str, int, int]] = []
    for size in (400, 600, 800, 1000, 1200):
        configs.append((f"fixed-{size}-ov0-clean", "clean", "fixed", size, 0))
    for size, ov in ((800, 120), (1000, 150), (1200, 180)):
        configs.append((f"fixed-{size}-ov{ov}-clean", "clean", "fixed", size, ov))
    for cap in (800, 1000, 1200):
        configs.append((f"clause-{cap}-clean", "clean", "clause", cap, 0))
    for size in (800, 1000):
        configs.append((f"fixed-{size}-ov0-raw", "raw", "fixed", size, 0))
    configs.append(("clause-1000-raw", "raw", "clause", 1000, 0))

    only = {x for x in os.environ.get("U8_ONLY", "").split(",") if x}
    if only:
        configs = [c for c in configs if c[0] in only]
        print(f"focused run: {[c[0] for c in configs]}")

    results: list[ConfigResult] = []
    for name, cleaning, strategy, size, ov in configs:
        src = cleaned if cleaning == "clean" else raw
        # Geometry once, from UNMASKED text - exactly what production would chunk.
        chunks = chunk_fixed(src, size, ov) if strategy == "fixed" else chunk_clause(src, size)
        res = ConfigResult(
            name=name,
            cleaning=cleaning,
            strategy=strategy,
            target_chars=size,
            overlap_chars=ov,
            n_chunks=len(chunks),
        )
        lens = [len(c.text) for c in chunks]
        res.mean_chars = round(statistics.mean(lens), 1)
        res.p95_chars = sorted(lens)[int(0.95 * len(lens))]
        toks = [len(tokzr.encode(c.text)) for c in chunks]
        res.mean_tokens = round(statistics.mean(toks), 1)
        res.max_tokens = max(toks)
        res.truncated = sum(1 for t in toks if t > MAX_TOKENS)
        res.index_mb_at_10k = round((384 * 4 + 8) * 10_000 * 2.5 / 1_048_576, 1)
        res.context_chars_top5 = int(res.mean_chars * 5)
        res.span_integrity, res.spans_split, integ_vec = span_integrity(chunks, probes)

        t0 = time.perf_counter()
        verbatim = score(chunks, [c.text for c in chunks], probes)
        res.embed_s = round(time.perf_counter() - t0, 1)

        parts = []
        for batch in batches:
            msrc = mask(src, batch)
            texts = [msrc[c.doc_n][c.start : c.end].strip() for c in chunks]
            parts.append(score(chunks, texts, batch))

        res.retrievers = {
            "verbatim": pooled([verbatim], chunks),
            "masked": pooled(parts, chunks),
        }
        res.per_probe = {
            "span_intact": integ_vec,
            "masked_rrf_hit@5": res.retrievers["masked"]["rrf60"].pop("hits@5"),
            "verbatim_rrf_hit@5": res.retrievers["verbatim"]["rrf60"].pop("hits@5"),
        }
        for variant in res.retrievers.values():
            for m in variant.values():
                m.pop("hits@5", None)
        res.citation_tightness = res.retrievers["verbatim"]["rrf60"]["citation_tightness@1"]
        results.append(res)
        v, m = res.retrievers["verbatim"], res.retrievers["masked"]
        print(
            f"  {name:24s} n={len(chunks):>4} tok~{res.mean_tokens:>5.0f}/{res.max_tokens:<4} "
            f"trunc={res.truncated:<3} integrity={res.span_integrity:.3f} "
            f"| verbatim R@5 rrf={v['rrf60']['recall@5']:.3f} "
            f"| masked R@5 rrf={m['rrf60']['recall@5']:.3f} "
            f"| tight={res.citation_tightness:.3f}",
            flush=True,
        )

    payload = {
        "experiment": "U-8 chunk size, overlap and structural awareness",
        "method_version": 2,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "DECISION EXPERIMENT - not the evaluation harness, not production code",
        "seed": SEED,
        "embedding_model": MODEL,
        "max_tokens_ceiling": MAX_TOKENS,
        "gold": {
            "definition": "character span in a document; a hit covers >= 50% of the span",
            "why": "chunk-level gold is not comparable across chunk sizes",
            "n_probes": len(probes),
            "batches": N_BATCHES,
            "max_corpus_blank_per_pass": round(masked_frac, 4),
            "geometry": "chunk boundaries computed once from clean UNMASKED text",
            "canary_excluded_from_gold": sorted(canary_docs()),
        },
        "cleaning": {
            "blanked_chars": blanked,
            "ranges": "Devanagari, Latin-Extended-B, IPA, U+FFFD, page furniture",
        },
        "configs": [asdict(r) for r in results],
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\nwrote {OUT_JSON.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
