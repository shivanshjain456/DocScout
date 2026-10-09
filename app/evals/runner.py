"""Run retrieval configurations against the gold set and write a reproducible report.

Contract with EVAL_PROTOCOL: a metric that has no raw output file does not exist. Every
run therefore writes evals/reports/<UTC timestamp>/results.json containing the per-item
rankings that produced the headline numbers, plus report.md for humans. Deleting the
report deletes the claim.

E-14 provenance is captured here rather than written by hand, because a provenance block
a human maintains is a provenance block that goes stale. Everything in it is read from the
artifact it describes at the moment of the run.

No judge, no generator, no network. This stage measures retrieval only, and says so in
the report rather than leaving a reader to assume the gaps are zeros.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from app.config import database_url, sha256_file
from app.evals import abstention, scorers, stats
from app.evals.goldset import (
    DEFAULT_GOLDSET,
    build_corpus_index,
    is_unanswerable,
    load_goldset,
    resolve_groups,
)
from app.ingest.chunk import CHUNK_OVERLAP, CHUNK_SIZE, MAX_TOKENS
from app.ingest.embed import EMBEDDING_DIM, MODEL_ID, QUERY_PREFIX, Embedder
from app.retrieval import SERVING_CONFIG, RetrievalConfig, Retriever
from app.retrieval.confidence import LOW_EVIDENCE_THRESHOLD
from app.rowtypes import as_int, as_str

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = REPO_ROOT / "evals" / "reports"

# Cutoffs reported for every configuration. 10 is the serving depth; 1 and 5 are kept
# because a system that is excellent at k=10 and poor at k=1 will mislead a generator that
# only reads the first chunk.
CUTOFFS = (1, 3, 5, 10)

# The single cutoff the A/B narrative, the paired bootstrap and the leakage bands all use.
# Fixed in one place because quoting a headline at one k and its confidence interval at
# another is how a report ends up contradicting itself.
AB_CUTOFF = 5

# The A/B that ADR-0006 rests on. Both single-arm configurations are run, not just the
# winner, because the brief requires the loser's numbers and why it lost.
# P1-3 adds hybrid-expanded to evaluate domain query understanding across leakage bands.
EXPANDED_CONFIG = RetrievalConfig(
    name="hybrid-expanded",
    mode="hybrid",
    k_dense=50,
    k_lexical=50,
    k_final=10,
    rrf_k=SERVING_CONFIG.rrf_k,
    anchor_arm_top1=True,
    expand_query=True,
    expansion_mode="synonym",
)

GRAPH_HYBRID_CONFIG = RetrievalConfig(
    name="graph-hybrid",
    mode="graph-hybrid",
    k_dense=50,
    k_lexical=50,
    k_final=10,
    rrf_k=SERVING_CONFIG.rrf_k,
    anchor_arm_top1=True,
)

BASELINE_CONFIGS: tuple[RetrievalConfig, ...] = (
    RetrievalConfig(name="dense-only", mode="dense", k_dense=50, k_final=10),
    RetrievalConfig(name="bm25-only", mode="bm25", k_lexical=50, k_final=10),
    SERVING_CONFIG,
    EXPANDED_CONFIG,
    GRAPH_HYBRID_CONFIG,
)


def _host_context() -> dict[str, Any]:
    """Hardware the numbers were measured on. E-16 makes this mandatory beside latency."""
    mem_kb = 0
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                mem_kb = int(line.split()[1])
                break
    import os

    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "mem_total_gib": round(mem_kb / 1024 / 1024, 2) if mem_kb else None,
    }


def _provenance(goldset_path: Path, conn: psycopg.Connection[tuple[object, ...]]) -> dict[str, Any]:
    metadata_path = goldset_path.parent / "metadata.json"
    metadata: dict[str, Any] = {}
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    counts = conn.execute(
        "SELECT (SELECT count(*) FROM documents), (SELECT count(*) FROM chunks)"
    ).fetchone()
    server = conn.execute("SHOW server_version").fetchone()
    return {
        "goldset_version": metadata.get("goldset_version", "unknown"),
        "goldset_sha256": sha256_file(goldset_path),
        "goldset_items": metadata.get("item_count"),
        "corpus_manifest_digest": sha256_file(REPO_ROOT / "corpus" / "raw" / "manifest.json"),
        "corpus_documents_in_db": as_int(counts[0]) if counts else None,
        "corpus_chunks_in_db": as_int(counts[1]) if counts else None,
        "chunker": {
            "chunk_size": CHUNK_SIZE,
            "overlap": CHUNK_OVERLAP,
            "max_tokens": MAX_TOKENS,
        },
        "embedding": {
            "model": MODEL_ID,
            "dim": EMBEDDING_DIM,
            "query_prefix": QUERY_PREFIX,
            "normalised": True,
        },
        # Named rather than silently omitted: a reader must be able to tell the difference
        # between "we used the default" and "this stage does not exist yet".
        "reranker": None,
        "generator": None,
        "judge": None,
        "uv_lock_sha256": sha256_file(REPO_ROOT / "uv.lock"),
        "postgres_version": as_str(server[0]) if server else None,
        "host": _host_context(),
    }


@dataclass
class ConfigRun:
    config: RetrievalConfig
    item_rows: list[dict[str, Any]]
    latencies_ms: list[float]
    by_cutoff: dict[int, scorers.Aggregate]

    def latency_summary(self) -> dict[str, float]:
        values = sorted(self.latencies_ms)
        if not values:
            return {}
        return {
            "mean_ms": round(statistics.fmean(values), 2),
            "p50_ms": round(values[len(values) // 2], 2),
            # Nearest-rank p95: with 131 queries the interpolated variant invents a value
            # between two measurements, and a latency figure should be one we observed.
            "p95_ms": round(values[min(len(values) - 1, math.ceil(0.95 * len(values)) - 1)], 2),
            "max_ms": round(values[-1], 2),
        }


def lexical_overlap(
    retriever: Retriever,
    conn: psycopg.Connection[tuple[object, ...]],
    question: str,
    groups: Sequence[Sequence[str]],
) -> float:
    """Fraction of a question's analyzed terms that appear verbatim in its gold evidence.

    This is a leakage probe, not a quality metric. The gold set was authored FROM the
    evidence quotes, so its questions inherit the vocabulary of the chunk they point at.
    A lexical retriever is then being handed part of the answer, and its score overstates
    what it would achieve on a question a human asked in their own words.

    Measured on the first baseline run: 0.733 against the gold chunk versus 0.094 against
    a random chunk, a 7.8x advantage. Reported per item so results can be stratified by
    it instead of the confound being averaged into one misleading headline.
    """
    terms = set(retriever.bm25.query_terms(conn, question))
    if not terms:
        return 0.0
    gold: set[str] = set()
    for group in groups:
        for chunk_id in group:
            gold |= retriever.bm25.lexemes_of(chunk_id)
    return len(terms & gold) / len(terms)


def run_config(
    retriever: Retriever,
    config: RetrievalConfig,
    items: Sequence[dict[str, Any]],
    groups_by_item: dict[str, list[list[str]]],
    overlap_by_item: dict[str, float],
) -> ConfigRun:
    rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    per_cutoff: dict[int, list[scorers.ItemScore]] = {k: [] for k in CUTOFFS}

    for item in items:
        item_id = str(item["item_id"])
        groups = groups_by_item[item_id]
        started = time.perf_counter()
        results = retriever.retrieve(str(item["question"]), config)
        latencies.append((time.perf_counter() - started) * 1000.0)
        ranked = [r.chunk_id for r in results]

        for k in CUTOFFS:
            per_cutoff[k].append(scorers.score_item(item_id, groups, ranked, k))

        at_final = scorers.score_item(item_id, groups, ranked, config.k_final)
        per_k = {k: scorers.score_item(item_id, groups, ranked, k) for k in CUTOFFS}
        rows.append(
            {
                "item_id": item_id,
                "question": item["question"],
                "answer_type": item.get("answer_type"),
                "difficulty": item.get("difficulty"),
                "n_groups": len(groups),
                "recall_at": {str(k): round(v.recall, 4) for k, v in per_k.items()},
                "hit_at": {str(k): v.hit for k, v in per_k.items()},
                "gold_groups": groups,
                "retrieved": [
                    {
                        "rank": r.rank,
                        "chunk_id": r.chunk_id,
                        "score": round(r.score, 6),
                        "arm_ranks": r.arm_ranks,
                    }
                    for r in results
                ],
                "recall": round(at_final.recall, 4),
                "hit": at_final.hit,
                "mrr": round(at_final.mrr, 4),
                "ndcg": round(at_final.ndcg, 4),
                "first_relevant_rank": at_final.first_relevant_rank,
                "missed_groups": at_final.missed_groups,
                "lexical_overlap": round(overlap_by_item.get(item_id, 0.0), 4),
                "latency_ms": round(latencies[-1], 2),
            }
        )

    return ConfigRun(
        config=config,
        item_rows=rows,
        latencies_ms=latencies,
        by_cutoff={k: scorers.aggregate(v) for k, v in per_cutoff.items()},
    )


def _slice_scores(run: ConfigRun, key: str) -> dict[str, dict[str, float | int]]:
    """Aggregate by answer_type / difficulty, so a headline mean cannot hide a weak slice."""
    buckets: dict[str, list[scorers.ItemScore]] = {}
    for row in run.item_rows:
        bucket = str(row.get(key) or "unknown")
        buckets.setdefault(bucket, []).append(
            scorers.ItemScore(
                item_id=str(row["item_id"]),
                n_groups=int(row["n_groups"]),
                groups_covered=0,
                recall=float(row["recall"]),
                hit=bool(row["hit"]),
                mrr=float(row["mrr"]),
                ndcg=float(row["ndcg"]),
                first_relevant_rank=row["first_relevant_rank"],
            )
        )
    return {name: scorers.aggregate(v).as_dict() for name, v in sorted(buckets.items())}


def _leakage_bands(runs: list[ConfigRun]) -> dict[str, dict[str, dict[str, float | int]]]:
    """Recall@AB_CUTOFF per configuration, split by how much the question leaks its answer.

    The bands are fixed cut points rather than terciles of this particular gold set, so
    the same band means the same thing in a later run against a different gold set.
    """
    bands = (("low <0.5", 0.0, 0.5), ("mid 0.5-0.8", 0.5, 0.8), ("high >=0.8", 0.8, 1.01))
    out: dict[str, dict[str, dict[str, float | int]]] = {}
    for label, low, high in bands:
        out[label] = {}
        for run in runs:
            selected = [
                scorers.ItemScore(
                    item_id=str(r["item_id"]),
                    n_groups=int(r["n_groups"]),
                    groups_covered=0,
                    recall=float(r["recall_at"][str(AB_CUTOFF)]),
                    hit=bool(r["hit_at"][str(AB_CUTOFF)]),
                    mrr=float(r["mrr"]),
                    ndcg=float(r["ndcg"]),
                    first_relevant_rank=r["first_relevant_rank"],
                )
                for r in run.item_rows
                if low <= float(r["lexical_overlap"]) < high
            ]
            out[label][run.config.name] = scorers.aggregate(selected).as_dict()
    return out


def _comparisons(runs: list[ConfigRun]) -> list[dict[str, Any]]:
    """Every pairwise difference with a paired bootstrap CI and discordant-pair counts."""
    out: list[dict[str, Any]] = []
    for i, a in enumerate(runs):
        for b in runs[i + 1 :]:
            diff = stats.paired_bootstrap(
                [float(r["recall"]) for r in a.item_rows],
                [float(r["recall"]) for r in b.item_rows],
            )
            a_only, b_only = stats.mcnemar_counts(
                [bool(r["hit"]) for r in a.item_rows], [bool(r["hit"]) for r in b.item_rows]
            )
            out.append(
                {
                    "a": a.config.name,
                    "b": b.config.name,
                    "metric": "recall@k_final",
                    **diff.as_dict(),
                    "discordant_hits": {
                        f"{a.config.name}_only": a_only,
                        f"{b.config.name}_only": b_only,
                    },
                }
            )
    return out


#: Thresholds swept for the abstention curve. Dense around the shipped operating point so
#: the cost of moving it is visible rather than extrapolated.
ABSTENTION_THRESHOLDS = (0.40, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.90)


def _score_abstention(
    answerable: list[dict[str, Any]],
    unanswerable: list[dict[str, Any]],
    embedder: Embedder,
) -> dict[str, Any]:
    """Measure evidence coverage on both halves of the gold set and sweep the threshold.

    Uses the serving configuration, because a signal measured on a configuration nobody
    runs says nothing about the system anybody uses.
    """
    coverage: dict[str, list[float]] = {"answerable": [], "unanswerable": []}
    per_item: list[dict[str, Any]] = []
    with psycopg.connect(database_url()) as conn:
        retriever = Retriever(conn, embedder=embedder)
        for label, group in (("answerable", answerable), ("unanswerable", unanswerable)):
            for item in group:
                question = str(item["question"])
                hits = retriever.retrieve(question, SERVING_CONFIG)
                assessed = retriever.assess_confidence(question, hits)
                coverage[label].append(assessed.evidence_coverage)
                per_item.append(
                    {
                        "item_id": str(item["item_id"]),
                        "answerable": label == "answerable",
                        "evidence_coverage": round(assessed.evidence_coverage, 4),
                        "low_evidence": assessed.low_evidence,
                        "missing_terms": assessed.missing_terms[:8],
                    }
                )

    shipped = abstention.score_at_threshold(
        coverage["answerable"], coverage["unanswerable"], LOW_EVIDENCE_THRESHOLD
    )
    return {
        "signal": "evidence_coverage",
        "shipped_threshold": LOW_EVIDENCE_THRESHOLD,
        "separation_auc": round(
            abstention.separation_auc(coverage["answerable"], coverage["unanswerable"]), 4
        ),
        "at_shipped_threshold": shipped.as_dict(),
        "sweep": [
            s.as_dict()
            for s in abstention.sweep(
                coverage["answerable"], coverage["unanswerable"], ABSTENTION_THRESHOLDS
            )
        ],
        "items": per_item,
    }


def write_report(
    runs: list[ConfigRun],
    provenance: dict[str, Any],
    excluded_unanswerable: int,
    out_dir: Path,
    abstention_report: dict[str, Any] | None = None,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)

    comparisons = _comparisons(runs)
    bands = _leakage_bands(runs)
    run_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    items_scored = runs[0].by_cutoff[CUTOFFS[0]].n if runs else 0

    results = {
        "schema": "docscout.eval.retrieval/1",
        "run_utc": run_utc,
        "stage": "retrieval-only",
        "judge": None,
        "provenance": provenance,
        "cutoffs": list(CUTOFFS),
        "items_scored": items_scored,
        "items_excluded_unanswerable": excluded_unanswerable,
        "abstention": abstention_report,
        "comparisons": comparisons,
        "by_lexical_overlap_recall": bands,
        "configs": [
            {
                "config": run.config.as_dict(),
                "metrics": {str(k): agg.as_dict() for k, agg in run.by_cutoff.items()},
                "latency": run.latency_summary(),
                "by_answer_type": _slice_scores(run, "answer_type"),
                "by_difficulty": _slice_scores(run, "difficulty"),
                "items": run.item_rows,
            }
            for run in runs
        ],
    }
    results_path = out_dir / "results.json"
    results_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    ranked = sorted(runs, key=lambda r: -r.by_cutoff[5].recall)
    winner, *losers = ranked

    lines: list[str] = []
    lines.append(f"# Retrieval baseline  -  {run_utc}\n")
    lines.append(
        "Retrieval only. No reranker, no generator, no LLM judge: those stages do not exist "
        "yet, and are reported as `null` rather than as zeros.\n"
    )
    lines.append("## Configurations compared\n")
    lines.append("| config | mode | k_dense | k_lexical | k_final | rrf_k |")
    lines.append("|---|---|---|---|---|---|")
    for run in runs:
        c = run.config
        lines.append(
            f"| `{c.name}` | {c.mode} | {c.k_dense if c.mode != 'bm25' else ' - '} | "
            f"{c.k_lexical if c.mode != 'dense' else ' - '} | {c.k_final} | "
            f"{c.rrf_k if c.mode == 'hybrid' else ' - '} |"
        )
    lines.append("")
    lines.append(
        f"Scored on {items_scored} answerable gold items; "
        f"{excluded_unanswerable} unanswerable items excluded from retrieval metrics "
        "(they carry no citations to cover; they are scored for abstention instead).\n"
    )

    for k in CUTOFFS:
        lines.append(f"## Results @ k={k}\n")
        lines.append("| config | recall | hit rate | MRR | nDCG |")
        lines.append("|---|---|---|---|---|")
        for run in runs:
            a = run.by_cutoff[k]
            lines.append(
                f"| `{run.config.name}` | {a.recall:.3f} | {a.hit_rate:.3f} | "
                f"{a.mrr:.3f} | {a.ndcg:.3f} |"
            )
        lines.append("")

    lines.append("## Latency\n")
    host = provenance["host"]
    lines.append(
        f"Measured on {host['cpu_count']} vCPU / {host['mem_total_gib']} GiB, "
        f"{host['platform']}. Retrieval only; the embedding model is loaded once before "
        "the run and excluded, because loading it per query would measure startup.\n"
    )
    lines.append("| config | mean | p50 | p95 | max |")
    lines.append("|---|---|---|---|---|")
    for run in runs:
        latency = run.latency_summary()
        lines.append(
            f"| `{run.config.name}` | {latency['mean_ms']:.1f} ms | {latency['p50_ms']:.1f} ms | "
            f"{latency['p95_ms']:.1f} ms | {latency['max_ms']:.1f} ms |"
        )
    lines.append("")

    lines.append("## A/B outcome\n")
    lines.append(
        f"Ranked by recall@5: **`{winner.config.name}`** leads at "
        f"{winner.by_cutoff[5].recall:.3f}.\n"
    )
    for loser in losers:
        delta = winner.by_cutoff[5].recall - loser.by_cutoff[5].recall
        lines.append(
            f"- `{loser.config.name}`: recall@5 {loser.by_cutoff[5].recall:.3f} "
            f"({delta:+.3f} vs leader, {delta * winner.by_cutoff[5].n:+.1f} items), "
            f"MRR {loser.by_cutoff[5].mrr:.3f}, "
            f"p95 {loser.latency_summary()['p95_ms']:.1f} ms."
        )
    lines.append("")
    lines.append("### Is the difference real?\n")
    lines.append(
        "Paired bootstrap, 10,000 resamples, fixed seed. `excludes zero` means the sign of "
        "the difference survived resampling; it is not a hypothesis test.\n"
    )
    lines.append(
        "| comparison | diff (recall) | 95% CI | in items | discordant hits | excludes zero |"
    )
    lines.append("|---|---|---|---|---|---|")
    for comparison in comparisons:
        discordant = comparison["discordant_hits"]
        pair = " / ".join(f"{k.replace('_only', '')}:{v}" for k, v in discordant.items())
        lines.append(
            f"| `{comparison['a']}` vs `{comparison['b']}` | {comparison['difference']:+.4f} | "
            f"[{comparison['ci_low']:+.4f}, {comparison['ci_high']:+.4f}] | "
            f"{comparison['difference_in_items']:+.1f} | {pair} | "
            f"{'yes' if comparison['excludes_zero'] else '**no**'} |"
        )
    lines.append("")
    lines.append("### Leakage caveat\n")
    lines.append(
        "The gold set's questions were authored from the evidence quotes, so they share "
        "vocabulary with the chunk they point at: on this run a question's analyzed terms "
        "appear in its own gold chunk far more often than in a random one. That advantages "
        "the lexical arm, so BM25's standing here is inflated by construction and is not "
        "evidence that BM25 beats hybrid on questions a human would type. Recall by "
        "leakage band:\n"
    )
    lines.append(
        "| question/evidence term overlap | "
        + " | ".join(f"`{r.config.name}`" for r in runs)
        + " | n |"
    )
    lines.append("|---" * (len(runs) + 2) + "|")
    for label, per_config in bands.items():
        first = next(iter(per_config.values()))
        row = " | ".join(f"{per_config[r.config.name]['recall']:.3f}" for r in runs)
        lines.append(f"| {label} | {row} | {first['n']} |")
    lines.append("")

    if abstention_report:
        lines.append("## Abstention\n")
        shipped = abstention_report["at_shipped_threshold"]
        lines.append(
            f"Signal: evidence coverage, separation AUC **{abstention_report['separation_auc']}** "
            f"(0.5 is chance). At the shipped threshold "
            f"{abstention_report['shipped_threshold']}:\n"
        )
        lines.append("| metric | value |")
        lines.append("|---|---|")
        for key in (
            "abstention_recall",
            "false_rejection_rate",
            "refusal_precision",
            "selective_accuracy",
            "refusal_rate",
        ):
            lines.append(f"| {key.replace('_', ' ')} | {shipped[key]:.3f} |")
        lines.append("")
        lines.append("| threshold | caught unanswerable | wrongly flagged | precision |")
        lines.append("|---|---|---|---|")
        for row in abstention_report["sweep"]:
            lines.append(
                f"| {row['threshold']:.2f} | {row['correct_refusals']}/{row['unanswerable']} "
                f"| {row['false_refusals']}/{row['answerable']} | {row['refusal_precision']:.2f} |"
            )
        lines.append("")

    lines.append("## Reproduce\n")
    lines.append("```bash\nmake eval\n```\n")
    lines.append(
        f"Gold set `{provenance['goldset_version']}` "
        f"(sha256 `{provenance['goldset_sha256'][:16]}…`), "
        f"corpus manifest `{provenance['corpus_manifest_digest'][:16]}…`, "
        f"uv.lock `{provenance['uv_lock_sha256'][:16]}…`.\n"
    )
    lines.append("Raw per-item rankings: `results.json`.\n")

    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return results_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the retrieval eval over the gold set.")
    parser.add_argument("--goldset", type=Path, default=DEFAULT_GOLDSET)
    parser.add_argument("--limit", type=int, default=None, help="score only the first N items")
    parser.add_argument("--report-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    all_items = load_goldset(args.goldset)
    items = [i for i in all_items if not is_unanswerable(i)]
    # No longer merely "excluded": these are scored for abstention below. They stay out of
    # the retrieval metrics because an item with no citations has no citation coverage to
    # measure, which is a different claim from having nothing to contribute.
    unanswerable_items = [i for i in all_items if is_unanswerable(i)]
    excluded = len(unanswerable_items)
    if args.limit:
        items = items[: args.limit]

    embedder = Embedder()
    print(f"  building corpus index ({len(items)} answerable items)…")
    index = build_corpus_index(embedder.count_tokens)
    groups_by_item = {str(i["item_id"]): resolve_groups(i, index) for i in items}

    ungrounded = [k for k, v in groups_by_item.items() if not v]
    if ungrounded:
        # Loud, not silent: an item whose quotes resolve to nothing would otherwise be
        # scored 0 for every configuration and quietly drag every mean down.
        raise SystemExit(f"items whose quotes resolve to no chunk: {ungrounded}")

    runs: list[ConfigRun] = []
    with psycopg.connect(database_url()) as conn:
        retriever = Retriever(conn, embedder=embedder)
        provenance = _provenance(args.goldset, conn)
        overlap_by_item = {
            str(i["item_id"]): lexical_overlap(
                retriever, conn, str(i["question"]), groups_by_item[str(i["item_id"])]
            )
            for i in items
        }
        for config in BASELINE_CONFIGS:
            print(f"  running {config.name}…", flush=True)
            runs.append(run_config(retriever, config, items, groups_by_item, overlap_by_item))

    print("  scoring abstention over the unanswerable items…", flush=True)
    abstention_report = _score_abstention(items, unanswerable_items, embedder)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.report_dir or (REPORTS_DIR / stamp)
    results_path = write_report(runs, provenance, excluded, out_dir, abstention_report)

    print()
    for run in runs:
        a = run.by_cutoff[5]
        print(
            f"  {run.config.name:<12} recall@5 {a.recall:.3f}  hit@5 {a.hit_rate:.3f}  "
            f"MRR {a.mrr:.3f}  nDCG {a.ndcg:.3f}  p95 {run.latency_summary()['p95_ms']:.0f} ms"
        )
    print(f"\n  report  {results_path.parent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
