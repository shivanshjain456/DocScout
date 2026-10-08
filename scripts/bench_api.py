#!/usr/bin/env python
"""Measure the serving API: end-to-end latency, the effect of caching, and cost per 1,000.

Artifact 3 asks for measured p95, cost per 1,000 queries, and the measured effect of
caching -- each from a committed script whose raw output is saved. This is that script.

What it measures, and why each choice is the honest one:

* **End to end over HTTP, not in-process.** The number a caller experiences includes
  serialisation, validation and the ASGI stack. Timing `Retriever.retrieve()` directly
  would report a smaller number that nobody can observe.
* **Real questions.** Queries come from the committed gold set, so the distribution of
  query length and vocabulary is the one the system is evaluated on, not a repeated
  lorem-ipsum string that would flatter the cache and the BM25 arm equally.
* **Cold means cold.** The cache-bypass phase sends `use_cache: false`, so every request
  pays full retrieval. Comparing a warm run against a *different* warm run is the usual
  way cache benchmarks lie.
* **p95 is nearest-rank.** With a few hundred samples, interpolation invents a value
  between two observations; a latency figure should be one that actually happened.
* **Cost is derived from measured throughput and a published instance price**, not from a
  vendor calculator. The price is a third-party listing and is labelled as such in the
  output, because an unsourced cost figure is the easiest number in this project to fake.

The script raises the server's rate limit via DOCSCOUT_RATE_LIMIT_PER_MINUTE before
starting; it cannot do that itself, so it checks and tells you if the limit would be hit.

Usage:
    uv run python scripts/bench_api.py --base-url http://127.0.0.1:8000 --n 200
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDSET = REPO_ROOT / "evals" / "gold" / "v1" / "gold.jsonl"

# AWS EC2 t4g.small on-demand, Linux, ap-south-1 (Mumbai): 2 vCPU / 2 GiB, the closest
# published shape to the 2 vCPU / 1.9 GiB host these numbers come from, in the region a
# service over Indian regulatory documents would actually run in.
#
# $0.0112/hour. Source: three independent price aggregators agreeing as of 2026-10
# (cloudprice.net, instance-pricing.com, devzero.io). NOT read from AWS's own calculator,
# which is JavaScript-driven; treat it as a close estimate rather than a quotation, and
# re-check before putting it in front of anyone who will act on it.
INSTANCE_NAME = "AWS t4g.small (2 vCPU / 2 GiB), ap-south-1, Linux on-demand"
INSTANCE_USD_PER_HOUR = 0.0112
INSTANCE_PRICE_SOURCE = (
    "third-party aggregators (cloudprice.net, instance-pricing.com, devzero.io), 2026-10"
)


def nearest_rank(values: list[float], quantile: float) -> float:
    """Nearest-rank percentile: always an observed value, never an interpolation."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def summarise(values: list[float], *, label: str = "phase") -> dict[str, float]:
    """Latency summary, refusing to compute statistics over nothing.

    Without the guard an empty phase dies inside `statistics.fmean` with "requires at least
    one data point", which tells the operator nothing about the actual cause -- usually that
    every request was rejected by the rate limiter. Observed while writing this script.
    """
    if not values:
        raise SystemExit(
            f"the {label} phase recorded no successful responses. Every request failed; "
            "the usual cause is the server's rate limit. Restart it with "
            "DOCSCOUT_RATE_LIMIT_PER_MINUTE set well above --n, and check "
            "the printed status counts."
        )
    return {
        "n": len(values),
        "mean_ms": round(statistics.fmean(values), 2),
        "p50_ms": round(nearest_rank(values, 0.50), 2),
        "p95_ms": round(nearest_rank(values, 0.95), 2),
        "p99_ms": round(nearest_rank(values, 0.99), 2),
        "max_ms": round(max(values), 2),
    }


def load_queries(limit: int) -> list[str]:
    """Real questions from the gold set, cycled if more samples than items are requested."""
    questions = [
        json.loads(line)["question"]
        for line in GOLDSET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not questions:
        raise SystemExit("gold set is empty; nothing to benchmark against")
    return [questions[i % len(questions)] for i in range(limit)]


def post(client: httpx.Client, query: str, *, use_cache: bool) -> tuple[float, bool, int]:
    """One request. Returns (elapsed_ms, cache_hit, status)."""
    started = time.perf_counter()
    response = client.post("/v1/search", json={"query": query, "k": 10, "use_cache": use_cache})
    elapsed = (time.perf_counter() - started) * 1000.0
    if response.status_code != 200:
        return elapsed, False, response.status_code
    return elapsed, bool(response.json()["timings"]["cache_hit"]), 200


def phase(
    client: httpx.Client, queries: list[str], *, use_cache: bool
) -> tuple[list[float], int, dict[int, int]]:
    latencies: list[float] = []
    hits = 0
    statuses: dict[int, int] = {}
    for query in queries:
        elapsed, hit, status = post(client, query, use_cache=use_cache)
        statuses[status] = statuses.get(status, 0) + 1
        if status != 200:
            continue
        latencies.append(elapsed)
        hits += int(hit)
    return latencies, hits, statuses


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--n", type=int, default=150, help="requests per phase")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    api_key = os.environ.get("DOCSCOUT_API_KEY", "").split(",")[0].strip()
    if not api_key:
        raise SystemExit("DOCSCOUT_API_KEY is not set; export it before benchmarking")

    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    with httpx.Client(base_url=args.base_url, headers=headers, timeout=60.0) as client:
        health = client.get("/healthz")
        health.raise_for_status()
        health_body = health.json()
        limit = int(health_body["rate_limit_per_minute"])
        if limit < args.n:
            raise SystemExit(
                f"the server's rate limit ({limit}/min) is below --n ({args.n}); restart it "
                f"with DOCSCOUT_RATE_LIMIT_PER_MINUTE={args.n * 4} so the benchmark measures "
                "latency rather than throttling"
            )

        queries = load_queries(args.n)

        # Warm up the process: the first requests touch import paths and allocator pages
        # that no later request pays for, and including them would inflate the tail.
        print("  warmup...", flush=True)
        phase(client, queries[:5], use_cache=False)

        print(f"  cold phase: {args.n} requests, cache bypassed...", flush=True)
        cold, cold_hits, cold_status = phase(client, queries, use_cache=False)

        print(f"  warm phase: {args.n} requests, cache enabled...", flush=True)
        phase(client, queries, use_cache=True)  # populate
        warm, warm_hits, warm_status = phase(client, queries, use_cache=True)

        print(f"  throughput: {args.n} requests at concurrency {args.concurrency}...", flush=True)
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            list(pool.map(lambda q: post(client, q, use_cache=False), queries))
        wall = time.perf_counter() - started
        throughput = args.n / wall if wall > 0 else 0.0

        cache_stats = client.get("/healthz").json()["cache"]

    cold_summary = summarise(cold, label="cold")
    warm_summary = summarise(warm, label="warm")

    # Cost model, stated explicitly so it can be argued with: one instance serving
    # continuously at the measured concurrent throughput. Hours for 1,000 queries is
    # 1000 / (qps * 3600); multiply by the hourly rate.
    hours_per_1k = (1000.0 / throughput / 3600.0) if throughput > 0 else 0.0
    cost_per_1k = hours_per_1k * INSTANCE_USD_PER_HOUR
    # The same arithmetic if every query were a cache hit, which is the ceiling the cache
    # buys -- not a claim that production would reach it.
    warm_qps = (1000.0 / warm_summary["mean_ms"]) if warm_summary["mean_ms"] else 0.0

    payload: dict[str, Any] = {
        "schema": "docscout.bench.api/1",
        "run_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "base_url": args.base_url,
        "requests_per_phase": args.n,
        "concurrency": args.concurrency,
        "host": {
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
            "note": "single uvicorn worker; cache and rate limiter are in-process",
        },
        "server": {
            "corpus_chunks": health_body["corpus_chunks"],
            "embedding_model": health_body["embedding_model"],
            "rate_limit_per_minute": limit,
        },
        "cold_cache_bypassed": {**cold_summary, "cache_hits": cold_hits, "statuses": cold_status},
        "warm_cache_enabled": {**warm_summary, "cache_hits": warm_hits, "statuses": warm_status},
        "cache_effect": {
            "p95_speedup_x": round(cold_summary["p95_ms"] / warm_summary["p95_ms"], 1)
            if warm_summary["p95_ms"]
            else None,
            "mean_speedup_x": round(cold_summary["mean_ms"] / warm_summary["mean_ms"], 1)
            if warm_summary["mean_ms"]
            else None,
            "p95_saved_ms": round(cold_summary["p95_ms"] - warm_summary["p95_ms"], 2),
            "server_hit_rate_pct": cache_stats["hit_rate_pct"],
        },
        "throughput": {
            "concurrency": args.concurrency,
            "queries_per_second": round(throughput, 2),
            "wall_seconds": round(wall, 2),
        },
        "cost": {
            "instance": INSTANCE_NAME,
            "usd_per_hour": INSTANCE_USD_PER_HOUR,
            "price_source": INSTANCE_PRICE_SOURCE,
            "model": "one instance serving continuously at the measured concurrent throughput",
            "usd_per_1000_queries_uncached": round(cost_per_1k, 6),
            "usd_per_1000_queries_all_cache_hits": round(
                (1000.0 / warm_qps / 3600.0) * INSTANCE_USD_PER_HOUR if warm_qps else 0.0, 6
            ),
            "llm_cost_usd": 0.0,
            "llm_note": "no model is called in the request path; this is compute only",
            "usd_per_million_queries_uncached": round(cost_per_1k * 1000, 4),
        },
    }

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out or (REPO_ROOT / "evals" / "bench" / stamp)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "bench.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print()
    print(f"  {'phase':<22} {'mean':>9} {'p50':>9} {'p95':>9} {'p99':>9} {'max':>9}")
    for label, summary in (
        ("cold (cache bypassed)", cold_summary),
        ("warm (cache hit)", warm_summary),
    ):
        print(
            f"  {label:<22} {summary['mean_ms']:>8.2f}ms {summary['p50_ms']:>8.2f}ms "
            f"{summary['p95_ms']:>8.2f}ms {summary['p99_ms']:>8.2f}ms {summary['max_ms']:>8.2f}ms"
        )
    effect = payload["cache_effect"]
    print(
        f"\n  cache effect     p95 {cold_summary['p95_ms']:.1f}ms -> {warm_summary['p95_ms']:.2f}ms "
        f"({effect['p95_speedup_x']}x, {effect['p95_saved_ms']:.1f}ms saved), "
        f"server hit rate {effect['server_hit_rate_pct']}%"
    )
    print(
        f"  throughput       {throughput:.2f} q/s at concurrency {args.concurrency} "
        f"on {os.cpu_count()} vCPU"
    )
    # Printed per million as well: retrieval on this corpus is cheap enough that four
    # decimal places round it to nothing, and "$0.0001" reads as a rounding artifact
    # rather than a measurement.
    print(
        f"  cost per 1,000   ${cost_per_1k:.6f} uncached "
        f"(= ${cost_per_1k * 1000:.2f} per million), "
        f"${payload['cost']['usd_per_1000_queries_all_cache_hits']:.6f} all-cache-hits"
    )
    print(f"                   {INSTANCE_NAME} @ ${INSTANCE_USD_PER_HOUR}/hr")
    print("                   no LLM in the request path, so this is the entire query cost")
    print(f"\n  raw: {out_dir.relative_to(REPO_ROOT)}/bench.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
