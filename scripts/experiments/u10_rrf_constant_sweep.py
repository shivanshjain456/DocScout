#!/usr/bin/env python
"""U-10: sweep the RRF constant over the whole gold set.

Why this exists, and why it is not the premature tuning ADR-0006 rejected.

ADR-0006 declined to tune the RRF constant because every pairwise difference in the first
baseline had a confidence interval straddling zero: tuning then would have been fitting
noise, and the winning value would have been whichever flipped a single item.

What changed is not the appetite for tuning, it is the evidence. Gold item g-038 asks which
withdrawn circular covered CCTV coverage of currency chests. BM25 ranks the correct chunk
FIRST, with a decisive margin. Dense ranks it 41st. Hybrid RRF at k=60 fuses those into rank
14 and the serving depth of 10 never sees it, so the item scores zero recall at every cutoff
while one arm had the answer at position one.

That is a structural failure, not a close call. RRF scores by 1/(k + rank), so at k=60 the
gap between rank 1 and rank 41 is only 1.66x: a document both arms rank near the top beats a
document one arm is certain about. fusion.py already documented that RRF "throws away margin"
as an accepted cost. This is that cost, measured, costing an answer outright.

So the question this sweep asks is deliberately narrow: does a sharper constant recover items
like g-038 WITHOUT damaging the rest of the gold set? A constant is only adopted if it wins on
the full 131 items with a paired bootstrap behind it -- not because it rescues one question.

Usage:  uv run python scripts/experiments/u10_rrf_constant_sweep.py [--out DIR]
"""

from __future__ import annotations

import argparse
import json
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
from app.retrieval import RetrievalConfig, Retriever

REPO_ROOT = Path(__file__).resolve().parents[2]

# The incumbent, from ADR-0006 and Cormack et al. (2009).
INCUMBENT = 60

# Swept values. 60 is the published default; below it the fusion discriminates ranks more
# sharply; 100 is included so the sweep can show the curve going the wrong way rather than
# only exploring one direction, which would make any minimum look like an edge.
SWEEP = (1, 5, 10, 20, 30, 60, 100)

# The item that motivated the sweep. Reported individually so the write-up can state plainly
# whether the constant that wins on aggregate also fixes the defect that prompted the work.
WITNESS_ITEM = "g-038"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    items = [i for i in load_goldset() if not is_unanswerable(i)]
    embedder = Embedder()
    print(f"  building corpus index ({len(items)} answerable items)...")
    index = build_corpus_index(embedder.count_tokens)
    groups = {str(i["item_id"]): resolve_groups(i, index) for i in items}

    runs: dict[str, Any] = {}
    per_item_recall: dict[str, dict[str, float]] = {}
    variants: list[tuple[str, RetrievalConfig]] = [
        (
            f"k={k}",
            RetrievalConfig(
                name=f"hybrid-rrf-k{k}",
                mode="hybrid",
                k_dense=50,
                k_lexical=50,
                k_final=10,
                rrf_k=k,
            ),
        )
        for k in SWEEP
    ]
    # The structural alternative to tuning the constant: keep k=60 and reserve a seat for
    # each arm's own top hit. Included in the same sweep so the two candidate fixes are
    # measured against each other on identical data rather than in separate write-ups.
    # The two fixes are orthogonal -- one sharpens rank discrimination, the other reserves a
    # seat -- so the combination is measured rather than assumed to be the sum of its parts.
    variants.append(
        (
            "k=5+anchor",
            RetrievalConfig(
                name="hybrid-rrf-k5-anchor",
                mode="hybrid",
                k_dense=50,
                k_lexical=50,
                k_final=10,
                rrf_k=5,
                anchor_arm_top1=True,
            ),
        )
    )
    variants.append(
        (
            "k=60+anchor",
            RetrievalConfig(
                name="hybrid-rrf-k60-anchor",
                mode="hybrid",
                k_dense=50,
                k_lexical=50,
                k_final=10,
                rrf_k=INCUMBENT,
                anchor_arm_top1=True,
            ),
        )
    )

    with psycopg.connect(database_url()) as conn:
        retriever = Retriever(conn, embedder=embedder)
        overlap = {
            str(i["item_id"]): lexical_overlap(
                retriever, conn, str(i["question"]), groups[str(i["item_id"])]
            )
            for i in items
        }
        for label, config in variants:
            print(f"  {label}...", flush=True)
            run = run_config(retriever, config, items, groups, overlap)
            runs[label] = run
            per_item_recall[label] = {
                str(r["item_id"]): float(r["recall_at"]["5"]) for r in run.item_rows
            }

    incumbent_label = f"k={INCUMBENT}"
    rows: list[dict[str, Any]] = []
    for label, _config in variants:
        run = runs[label]
        witness = next((r for r in run.item_rows if r["item_id"] == WITNESS_ITEM), None)
        diff = stats.paired_bootstrap(
            [per_item_recall[label][i] for i in sorted(per_item_recall[label])],
            [per_item_recall[incumbent_label][i] for i in sorted(per_item_recall[incumbent_label])],
        )
        rows.append(
            {
                "variant": label,
                "recall@1": run.by_cutoff[1].recall,
                "recall@5": run.by_cutoff[5].recall,
                "recall@10": run.by_cutoff[10].recall,
                "mrr": run.by_cutoff[5].mrr,
                "ndcg@5": run.by_cutoff[5].ndcg,
                "p95_ms": run.latency_summary()["p95_ms"],
                "vs_incumbent": diff.as_dict(),
                f"{WITNESS_ITEM}_recall@5": witness["recall_at"]["5"] if witness else None,
                f"{WITNESS_ITEM}_recall@10": witness["recall_at"]["10"] if witness else None,
                f"{WITNESS_ITEM}_first_relevant_rank": (
                    witness["first_relevant_rank"] if witness else None
                ),
            }
        )

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out or (REPO_ROOT / "evals" / "experiments" / f"u10-rrf-{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "docscout.experiment.u10-rrf/1",
        "run_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "question": "U-10: what RRF constant should hybrid retrieval use?",
        "incumbent": INCUMBENT,
        "items_scored": len(items),
        "witness_item": WITNESS_ITEM,
        "results": rows,
    }
    (out_dir / "results.json").write_text(json.dumps(payload, indent=2) + "\n")

    header = (
        f"  {'variant':>12} {'R@1':>7} {'R@5':>7} {'R@10':>7} {'MRR':>7} {'nDCG':>7} "
        f"{'vs k=60':>9} {'CI excl 0':>10} {'g-038 R@5':>10} {'R@10':>6}"
    )
    print()
    print(header)
    for row in rows:
        print(
            f"  {row['variant']:>12} {row['recall@1']:>7.3f} {row['recall@5']:>7.3f} "
            f"{row['recall@10']:>7.3f} {row['mrr']:>7.3f} {row['ndcg@5']:>7.3f} "
            f"{row['vs_incumbent']['difference']:>+9.4f} "
            f"{'yes' if row['vs_incumbent']['excludes_zero'] else 'no':>10} "
            f"{row[f'{WITNESS_ITEM}_recall@5']:>10.2f} "
            f"{row[f'{WITNESS_ITEM}_recall@10']:>6.2f}"
        )
    print(f"\n  raw: {out_dir.relative_to(REPO_ROOT)}/results.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
