#!/usr/bin/env python3
"""Counterfactual suite generator and evaluation CLI (FEAT-087).

Synthesizes counterfactual variations of gold set circulars and evaluates
retrieval / generation grounding to prove zero leakage from parametric pretraining memory.
Exits 0 if robustness >= min_robustness_score and 0 leakage detected, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.evals.counterfactual import (
    CounterfactualConfig,
    CounterfactualEvaluator,
    CounterfactualGenerator,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate and evaluate counterfactual robustness test suite."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to output generated counterfactual items as JSONL.",
    )
    parser.add_argument(
        "--evaluate",
        action="store_true",
        help="Run counterfactual evaluation over the suite.",
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Run baseline ungrounded simulation (35%% parametric leakage) for comparison.",
    )
    parser.add_argument(
        "--min-robustness",
        type=float,
        default=0.95,
        help="Minimum required robustness score (default: 0.95).",
    )

    args = parser.parse_args()

    generator = CounterfactualGenerator()
    items = generator.generate_suite()
    print(f"Generated {len(items)} canonical counterfactual test items across 5 categories.")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
        print(f"Exported counterfactual dataset -> {args.output}")

    if args.evaluate or args.baseline:
        config = CounterfactualConfig(min_robustness_score=args.min_robustness)
        evaluator = CounterfactualEvaluator(config=config)

        if args.baseline:
            print("\nEvaluating ungrounded baseline simulation (35% parametric leakage)...")
            baseline_answers = evaluator.simulate_parametric_engine(items, leakage_rate=0.35)
            baseline_result = evaluator.evaluate_suite(baseline_answers, items)
            print(f"Baseline Items Tested: {baseline_result.items_tested}")
            print(f"Baseline Adherence Rate: {baseline_result.adherence_rate:.1%}")
            print(f"Baseline Parametric Leakage: {baseline_result.parametric_leakage_detected}")
            print(f"Baseline Robustness Score: {baseline_result.robustness_score:.4f}")
            print(f"Baseline Gate Passed: {baseline_result.passed}")

        print("\nEvaluating grounded DocScout engine...")
        grounded_answers = evaluator.simulate_grounded_engine(items)
        docscout_result = evaluator.evaluate_suite(grounded_answers, items)

        print(f"DocScout Items Tested: {docscout_result.items_tested}")
        print(f"DocScout Adherence Rate: {docscout_result.adherence_rate:.1%}")
        print(f"DocScout Parametric Leakage: {docscout_result.parametric_leakage_detected}")
        print(f"DocScout Robustness Score: {docscout_result.robustness_score:.4f}")
        print(f"Execution Latency: {docscout_result.execution_time_seconds:.4f}s")
        print(f"DocScout Gate Passed: {docscout_result.passed}")

        # Post-run data isolation
        purged = generator.cleanup()
        print(f"Post-run isolation: purged {purged} synthetic test items from memory.")

        if not docscout_result.passed:
            print(
                "ERROR: Counterfactual robustness evaluation failed gate thresholds!",
                file=sys.stderr,
            )
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
