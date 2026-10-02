#!/usr/bin/env python
"""Does a cross-encoder reranker earn its latency on this corpus?

ADR-0006 deferred the reranker with a specific prediction: "a reranker reorders what
retrieval already found, so it cannot fix a recall ceiling, and at recall@10 near 0.98
there is almost nothing left for it to recover". ADR-0007 then pushed recall@10 to 1.000,
which makes that prediction sharper rather than obsolete — the reranker now provably cannot
improve recall at depth 10, because there is nothing left to find.

So this experiment asks the only question still open: **can it improve the top of the
list?** recall@1 is 0.695, which is where all the remaining headroom lives, and where a
reranker is supposed to be strongest.

It measures both sides of the trade honestly:

* **Quality** at k = 1, 3, 5, 10 against the serving configuration, with a paired bootstrap
  so a two-item change is not reported as a win.
* **Cost** as real wall-clock per query, measured on the actual corpus chunks rather than
  on toy strings. Cross-encoder cost scales with sequence length, and a 1,000-character
  regulatory chunk is nothing like the short passages a quick benchmark would use — a
  per-pair figure from toy text would understate the real cost several-fold.

`rerank_top_n` is swept because it is the entire cost dial: the model scores exactly that
many pairs per query, so doubling it doubles the latency.

Usage:  uv run python -m scripts.experiments.u10_rerank_ablation
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from app.config import database_url
from app.evals import stats
from app.evals.goldset import (
    build_corpus_index,
    is_unanswerable,
    load_goldset,
    resolve_groups,
)
from app.evals.runner import lexical_overlap, run_config
from app.ingest.embed import Embedder
from app.retrieval import SERVING_CONFIG, RetrievalConfig, Retriever
from app.retrieval.rerank import MODEL_ID as RERANK_MODEL_ID
from app.retrieval.rerank import CrossEncoderReranker

REPO_ROOT = Path(__file__).resolve().parents[2]

# Candidate depths for the cross-encoder. 10 is the cheapest useful setting (reorder
# exactly what is returned); 50 scores the whole fused pool.
SWEEP = (10, 20, 50)


def variants() -> list[tuple[str, RetrievalConfig]]:
    baseline = ("no rerank (serving)", SERVING_CONFIG)
    swept = [
        (
            f"rerank top {n}",
            RetrievalConfig(
                name=f"hybrid-rrf-rerank{n}",
                mode="hybrid",
                k_dense=SERVING_CONFIG.k_dense,
                k_lexical=SERVING_CONFIG.k_lexical,
                k_final=SERVING_CONFIG.k_final,
                rrf_k=SERVING_CONFIG.rrf_k,
                anchor_arm_top1=SERVING_CONFIG.anchor_arm_top1,
                rerank=True,
                rerank_top_n=n,
            ),
        )
        for n in SWEEP
    ]
    return [baseline, *swept]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    items = [i for i in load_goldset() if not is_unanswerable(i)]
    embedder = Embedder()
    print(f"  building corpus index ({len(items)} answerable items)...", flush=True)
    index = build_corpus_index(embedder.count_tokens)
    groups = {str(i["item_id"]): resolve_groups(i, index) for i in items}

    reranker = CrossEncoderReranker()
    print("  loading the cross-encoder...", flush=True)
    load_started = time.perf_counter()
    reranker.warm()
    load_seconds = time.perf_counter() - load_started

    runs: dict[str, Any] = {}
    per_item: dict[str, dict[str, float]] = {}

    with psycopg.connect(database_url()) as conn:
        retriever = Retriever(conn, embedder=embedder, bm25=None, reranker=reranker)
        overlap = {
            str(i["item_id"]): lexical_overlap(
                retriever, conn, str(i["question"]), groups[str(i["item_id"])]
            )
            for i in items
        }
        for label, config in variants():
            print(f"  {label}...", flush=True)
            run = run_config(retriever, config, items, groups, overlap)
            runs[label] = run
            per_item[label] = {str(r["item_id"]): float(r["recall_at"]["1"]) for r in run.item_rows}

    baseline_label = "no rerank (serving)"
    rows: list[dict[str, Any]] = []
    for label, _config in variants():
        run = runs[label]
        latencies = sorted(run.latencies_ms)
        diff = stats.paired_bootstrap(
            [per_item[label][i] for i in sorted(per_item[label])],
            [per_item[baseline_label][i] for i in sorted(per_item[baseline_label])],
        )
        rows.append(
            {
                "variant": label,
                "recall@1": run.by_cutoff[1].recall,
                "recall@3": run.by_cutoff[3].recall,
                "recall@5": run.by_cutoff[5].recall,
                "recall@10": run.by_cutoff[10].recall,
                "mrr": run.by_cutoff[5].mrr,
                "ndcg@5": run.by_cutoff[5].ndcg,
                "mean_ms": round(statistics.fmean(latencies), 1),
                "p95_ms": run.latency_summary()["p95_ms"],
                "recall@1_vs_baseline": diff.as_dict(),
            }
        )

    base = rows[0]
    for row in rows[1:]:
        row["latency_multiplier"] = round(row["p95_ms"] / base["p95_ms"], 1)
        pairs = int(row["variant"].split()[-1])
        extra = row["mean_ms"] - base["mean_ms"]
        row["measured_ms_per_pair_on_real_chunks"] = round(extra / pairs, 2)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out or (REPO_ROOT / "evals" / "experiments" / f"u10-rerank-{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "docscout.experiment.u10-rerank/1",
        "run_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "question": "Does cross-encoder reranking earn its latency on this corpus?",
        "reranker_model": RERANK_MODEL_ID,
        "reranker_load_seconds": round(load_seconds, 1),
        "items_scored": len(items),
        "baseline": baseline_label,
        "results": rows,
    }
    (out_dir / "results.json").write_text(json.dumps(payload, indent=2) + "\n")

    print()
    header = (
        f"  {'variant':<20} {'R@1':>6} {'R@3':>6} {'R@5':>6} {'R@10':>6} {'MRR':>6} "
        f"{'nDCG':>6} {'p95':>9} {'vs base':>9} {'CI≠0':>6}"
    )
    print(header)
    for row in rows:
        d = row["recall@1_vs_baseline"]
        print(
            f"  {row['variant']:<20} {row['recall@1']:>6.3f} {row['recall@3']:>6.3f} "
            f"{row['recall@5']:>6.3f} {row['recall@10']:>6.3f} {row['mrr']:>6.3f} "
            f"{row['ndcg@5']:>6.3f} {row['p95_ms']:>8.0f}ms {d['difference']:>+9.4f} "
            f"{'yes' if d['excludes_zero'] else 'no':>6}"
        )
    print()
    for row in rows[1:]:
        print(
            f"  {row['variant']:<20} {row['latency_multiplier']:>5.1f}x p95, "
            f"{row['measured_ms_per_pair_on_real_chunks']:>6.2f} ms/pair on real chunks"
        )
    print(f"\n  raw: {out_dir.relative_to(REPO_ROOT)}/results.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
