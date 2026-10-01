---
name: load-test-protocol
description: Use this skill for any performance work on DocScout - writing or editing k6 scripts, running load or soak or spike tests, benchmarking retrieval or embedding or reranking, measuring cache effectiveness, sizing workers, and before stating ANY latency, throughput, concurrency, cost-per-query, or tokens-per-second number in a README, commit, ADR, report, or conversation. Use it when asked "how fast is it", "how many users can it handle", "what is p95", "is the cache helping", or "what does a query cost".
---

# Load test protocol

A performance number is a claim about reality. It needs a reproducible generator, a comparison arm,
and a saved report — or it does not get said.

## Required for every run

1. **Seeded, documented workload generator.** Record in the script header and the report:
   - prompt/query mix (how many short vs long, lookup vs multi-hop, cached vs novel)
   - corpus size at test time (documents, chunks, index size on disk)
   - retrieval depth (k before rerank, k after rerank)
   - generation settings (model ID, max tokens) or whether generation was stubbed
   - RNG seed — the same seed must reproduce the same request sequence
2. **Minimum two arms.** A single number is uninterpretable. Always compare, e.g.
   cache-on vs cache-off, N workers vs 2N, rerank-on vs rerank-off, HNSW vs exact.
3. **Thresholds declared in the script** (k6 `thresholds`), not judged after the fact:
   p50, p95, p99, RPS, error rate. A run that breaches its thresholds is a FAIL that gets reported,
   not a run you quietly rerun until it passes.
4. **Full k6 output saved** to `loadtests/reports/<UTC-timestamp>/` — stdout, the JSON summary, the
   script version/git SHA, and a `conditions.md` describing the environment (CPU count, RAM,
   container limits, whether services shared the box).
5. **A number is claimable only with its report directory.** Cite the path next to the number.

## Reporting rules

- Report **p50 / p95 / p99 and error rate together**. A mean alone is misleading; a p95 without an
  error rate hides a system that got fast by failing fast.
- State the arm and the hardware in the same sentence as the number.
- **No "approximately", no rounded-up marketing numbers, no numbers from memory.** If the report
  says 412 ms, write 412 ms.
- Include the failure point: ramp until something breaks and report where it broke.

## Gotchas

- **Warm-up contaminates p50.** JIT, connection pools, and an empty cache make the first seconds
  unrepresentative. Discard or report warm-up separately — and never let a warm cache silently
  inflate a "cold" arm.
- **Testing against a dummy endpoint measures the harness, not the system.** Setup-phase runs
  against a stub are pipeline checks; label them meaningless for performance purposes.
- **Generator-side bottlenecks masquerade as server latency.** On a small box, k6 itself competes
  for CPU with the service under test. Record whether load generator and service shared hardware —
  on a 2-vCPU box, they did, and that caps the credible RPS.
- **LLM calls dominate and are provider-rate-limited.** Throughput numbers that include a hosted
  generator are measuring the vendor's queue as much as DocScout. Separate retrieval-only latency
  from end-to-end latency; report both.
- **Cost per query must use live pricing** fetched at test time and the *measured* token counts, not
  estimated tokens and remembered prices.
- **p99 needs volume.** 100 requests cannot support a p99 claim. Report sample size with the
  percentile, and do not quote a p99 from fewer than ~1000 samples.
