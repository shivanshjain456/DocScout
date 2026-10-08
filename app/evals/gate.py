"""The regression gate: fail the build when quality drops against recent baselines.

EVAL_PROTOCOL E-12 and the project brief both require a gate that fails on a regression
greater than one percentage point against the last three baselines. This module is that
gate, and `make eval-gate` is how it runs.

Two kinds of check, deliberately separated, because conflating them is how a gate becomes
either noisy or useless:

1. INVARIANTS. Deterministic facts that make a comparison meaningful at all -- the gold
   set is the one the baselines were measured against, the corpus is the same corpus, no
   items quietly disappeared. A violated invariant is not a regression, it is a statement
   that the numbers are not comparable, and it fails hard with its own message. Checking
   these first prevents the classic false green: a gold set silently shrinks to its easy
   items, every metric improves, and the gate congratulates you.

2. METRIC REGRESSION. The 1pp rule, applied to the serving configuration against the mean
   of the last three accepted baselines.

On the honesty of the 1pp threshold
-----------------------------------
Measured in ADR-0006: on a 131-item gold set one item is worth 0.76pp, and every pairwise
bootstrap CI in the first baseline straddled zero. A 1pp threshold is therefore roughly
1.3 items, which is inside the noise band of this gold set. The brief specifies 1pp and
this gate enforces 1pp -- it is not quietly widened, because a threshold a tool relaxes on
its own authority is worse than one that is too tight.

What the gate does instead is report the noise floor beside its verdict, so a failure is
never mistaken for a conclusion it cannot support. `minimum_detectable_effect` is the
half-width of the paired bootstrap CI against the most recent baseline: a drop smaller
than that is indistinguishable from resampling noise even when it trips the threshold. The
fix is a larger gold set, which is tracked, not a looser gate.
"""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.evals import stats

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = REPO_ROOT / "evals" / "reports"
BASELINES_DIR = REPO_ROOT / "evals" / "baselines"

# The configuration whose numbers the gate protects. Gating on every configuration would
# fail the build when a deliberately-kept loser arm moves, which is not a regression in
# anything shipped. ADR-0006 names hybrid-rrf as the serving configuration.
SERVING_CONFIG = "hybrid-rrf"

# Cutoff for the gated metrics, matching the A/B cutoff the reports and ADR-0006 quote.
GATE_CUTOFF = "5"

# Metrics the gate protects. Any one of them dropping more than the threshold fails the
# build: a system that holds recall while its ranking collapses has regressed, and a gate
# watching only recall would pass it.
GATED_METRICS = ("recall", "mrr", "ndcg")

# One percentage point, as a fraction. From the brief and EVAL_PROTOCOL E-12.
THRESHOLD = 0.01

# The rule is "greater than one point", so a drop of exactly 1pp must pass. Binary floating
# point does not cooperate: 0.97 - 0.96 is 0.010000000000000009, which compares as greater
# than 0.01 and fails a build the specification allows. Metrics are reported to four
# decimals, so rounding the delta to six is far finer than the data and removes the
# artifact without widening the rule.
_DELTA_PRECISION = 6

# How many accepted baselines the comparison averages over.
BASELINE_WINDOW = 3


class GateError(RuntimeError):
    """Raised when the gate cannot run at all, as distinct from failing a comparison."""


@dataclass
class Finding:
    kind: str  # "invariant" | "regression" | "improvement" | "note"
    severity: str  # "fail" | "warn" | "info"
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


def _display(path: Path) -> str:
    """Repo-relative when possible, absolute otherwise.

    --report-dir legitimately points outside the repository (the smoke target writes to
    /tmp), and relative_to() raises rather than falling back, which turned a cosmetic
    path into a crash after the gate had already done its work.
    """
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def _git_commit() -> str:
    """The current commit, read from .git rather than by running git.

    No subprocess: the only thing needed is a 40-character string for provenance, and
    shelling out would add a dependency on the git binary being installed and on PATH
    inside whatever container runs the gate. Reading the files is also the honest scope --
    S603/S607 flag subprocess use in application code, and the right answer to a security
    rule is usually to stop doing the thing rather than to annotate it.

    Returns "unknown" rather than raising: a missing commit id must not stop a gate from
    reporting a regression.
    """
    git_dir = REPO_ROOT / ".git"
    head_file = git_dir / "HEAD"
    if not head_file.is_file():
        return "unknown"
    head = head_file.read_text(encoding="utf-8").strip()
    if not head.startswith("ref:"):
        # Detached HEAD: the file already holds the sha.
        return head
    ref = head.split(" ", 1)[1].strip()
    loose = git_dir / ref
    if loose.is_file():
        return loose.read_text(encoding="utf-8").strip()
    # Refs get packed by `git gc`, after which the loose file no longer exists.
    packed = git_dir / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8").splitlines():
            if line.startswith(("#", "^")):
                continue
            parts = line.split(" ", 1)
            if len(parts) == 2 and parts[1].strip() == ref:
                return parts[0].strip()
    return "unknown"


def latest_report() -> Path:
    """Newest results.json under evals/reports/, by directory name (UTC timestamps sort)."""
    candidates = sorted(p for p in REPORTS_DIR.glob("*/results.json"))
    if not candidates:
        raise GateError(
            "no eval run found under evals/reports/. Run `make eval` before `make eval-gate`."
        )
    return candidates[-1]


def serving_metrics(results: dict[str, Any]) -> dict[str, float]:
    """Pull the gated metrics for the serving configuration out of a results.json."""
    for config in results.get("configs", []):
        if config["config"]["name"] == SERVING_CONFIG:
            at_cutoff = config["metrics"][GATE_CUTOFF]
            return {m: float(at_cutoff[m]) for m in GATED_METRICS}
    raise GateError(
        f"results.json contains no configuration named {SERVING_CONFIG!r}; "
        f"found {[c['config']['name'] for c in results.get('configs', [])]}"
    )


def per_item_recall(results: dict[str, Any]) -> dict[str, float]:
    """Per-item recall at the gate cutoff for the serving config, keyed by item_id.

    Needed for the paired bootstrap: the noise floor is a property of the item-level
    differences, and cannot be recovered from the aggregates.
    """
    for config in results.get("configs", []):
        if config["config"]["name"] == SERVING_CONFIG:
            return {
                str(row["item_id"]): float(row["recall_at"][GATE_CUTOFF])
                for row in config.get("items", [])
            }
    return {}


def baseline_record(results: dict[str, Any], results_path: Path) -> dict[str, Any]:
    """The committed summary of an accepted baseline.

    Deliberately self-contained: it carries the identifying digests rather than only a
    path, so a baseline stays meaningful even if its report directory is pruned, and a
    gold set swapped underneath the ledger is detectable.
    """
    provenance = results["provenance"]
    return {
        "schema": "docscout.eval.baseline/1",
        "run_utc": results["run_utc"],
        "report_dir": _display(results_path.parent),
        "git_commit": _git_commit(),
        "goldset_version": provenance["goldset_version"],
        "goldset_sha256": provenance["goldset_sha256"],
        "corpus_manifest_digest": provenance["corpus_manifest_digest"],
        "corpus_chunks_in_db": provenance["corpus_chunks_in_db"],
        "items_scored": results["items_scored"],
        "serving_config": SERVING_CONFIG,
        "cutoff": GATE_CUTOFF,
        "metrics": serving_metrics(results),
        "per_item_recall": per_item_recall(results),
    }


def load_baselines(limit: int = BASELINE_WINDOW) -> list[dict[str, Any]]:
    """The most recent accepted baselines, newest last."""
    if not BASELINES_DIR.exists():
        return []
    records = []
    for path in sorted(BASELINES_DIR.glob("*.json")):
        records.append(json.loads(path.read_text(encoding="utf-8")))
    records.sort(key=lambda r: str(r["run_utc"]))
    return records[-limit:]


def check_invariants(current: dict[str, Any], baselines: list[dict[str, Any]]) -> list[Finding]:
    """Facts that must hold for a comparison to mean anything."""
    findings: list[Finding] = []
    provenance = current["provenance"]
    newest = baselines[-1]

    # A gold set whose contents changed without a version bump makes every historical
    # number incomparable while looking identical in the ledger.
    if provenance["goldset_version"] == newest["goldset_version"]:
        if provenance["goldset_sha256"] != newest["goldset_sha256"]:
            findings.append(
                Finding(
                    "invariant",
                    "fail",
                    f"gold set {provenance['goldset_version']} changed content without a "
                    "version bump; baselines are not comparable",
                    {
                        "baseline_sha256": newest["goldset_sha256"][:16],
                        "current_sha256": provenance["goldset_sha256"][:16],
                    },
                )
            )
    else:
        findings.append(
            Finding(
                "invariant",
                "warn",
                f"gold set version changed {newest['goldset_version']} -> "
                f"{provenance['goldset_version']}; the comparison spans different rulers",
                {},
            )
        )

    if provenance["corpus_manifest_digest"] != newest["corpus_manifest_digest"]:
        findings.append(
            Finding(
                "invariant",
                "fail",
                "corpus manifest changed since the last baseline; retrieval metrics "
                "measured over different corpora are not comparable",
                {
                    "baseline_digest": newest["corpus_manifest_digest"][:16],
                    "current_digest": provenance["corpus_manifest_digest"][:16],
                },
            )
        )

    # Items silently disappearing is the failure mode that makes every metric improve.
    if current["items_scored"] < newest["items_scored"]:
        findings.append(
            Finding(
                "invariant",
                "fail",
                f"scored {current['items_scored']} items, baseline scored "
                f"{newest['items_scored']}; items vanished from the gold set",
                {},
            )
        )

    if provenance["corpus_chunks_in_db"] != newest["corpus_chunks_in_db"]:
        findings.append(
            Finding(
                "invariant",
                "warn",
                f"corpus chunk count moved {newest['corpus_chunks_in_db']} -> "
                f"{provenance['corpus_chunks_in_db']} with an unchanged manifest; "
                "re-ingest may be incomplete",
                {},
            )
        )

    return findings


def check_regression(
    current: dict[str, Any], baselines: list[dict[str, Any]]
) -> tuple[list[Finding], dict[str, Any]]:
    """The 1pp rule against the mean of the baseline window."""
    findings: list[Finding] = []
    current_metrics = serving_metrics(current)
    comparison: dict[str, Any] = {}

    for metric in GATED_METRICS:
        history = [float(b["metrics"][metric]) for b in baselines]
        reference = statistics.fmean(history)
        value = current_metrics[metric]
        delta = round(value - reference, _DELTA_PRECISION)
        comparison[metric] = {
            "current": round(value, 4),
            "baseline_mean": round(reference, 4),
            "baseline_values": [round(h, 4) for h in history],
            "delta": round(delta, 4),
            "delta_pp": round(delta * 100, 2),
            "threshold_pp": THRESHOLD * 100,
        }
        if delta < -THRESHOLD:
            findings.append(
                Finding(
                    "regression",
                    "fail",
                    f"{metric}@{GATE_CUTOFF} fell {abs(delta) * 100:.2f}pp against "
                    f"{'the baseline' if len(baselines) == 1 else f'the mean of the last {len(baselines)} baselines'} "
                    f"({value:.4f} vs {reference:.4f}); threshold is "
                    f"{THRESHOLD * 100:.0f}pp",
                    comparison[metric],
                )
            )
        elif delta > THRESHOLD:
            findings.append(
                Finding(
                    "improvement",
                    "info",
                    f"{metric}@{GATE_CUTOFF} rose {delta * 100:.2f}pp "
                    f"({value:.4f} vs {reference:.4f})",
                    comparison[metric],
                )
            )
    return findings, comparison


def noise_floor(current: dict[str, Any], baselines: list[dict[str, Any]]) -> dict[str, Any]:
    """Half-width of the paired bootstrap CI for recall against the newest baseline.

    A drop smaller than this cannot be told from resampling noise, whatever the threshold
    says. Reported so a verdict is never read as more certain than the data allows.
    Requires per-item recall on both sides; older ledger entries may predate it.
    """
    newest = baselines[-1]
    previous = newest.get("per_item_recall") or {}
    current_items = per_item_recall(current)
    shared = sorted(set(previous) & set(current_items))
    if len(shared) < 2:
        return {
            "available": False,
            "reason": "no per-item recall shared with the most recent baseline",
        }
    diff = stats.paired_bootstrap(
        [current_items[i] for i in shared],
        [previous[i] for i in shared],
    )
    half_width = (diff.ci_high - diff.ci_low) / 2.0
    return {
        "available": True,
        "n_paired_items": len(shared),
        "observed_delta": round(diff.difference, 4),
        "ci_low": round(diff.ci_low, 4),
        "ci_high": round(diff.ci_high, 4),
        "excludes_zero": diff.excludes_zero,
        "minimum_detectable_effect_pp": round(half_width * 100, 2),
        "threshold_is_below_noise": half_width > THRESHOLD,
    }


@dataclass
class GateResult:
    passed: bool
    findings: list[Finding]
    comparison: dict[str, Any]
    noise: dict[str, Any]
    baselines_used: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "docscout.eval.gate/1",
            "checked_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "passed": self.passed,
            "serving_config": SERVING_CONFIG,
            "cutoff": GATE_CUTOFF,
            "threshold_pp": THRESHOLD * 100,
            "baselines_used": self.baselines_used,
            "comparison": self.comparison,
            "noise_floor": self.noise,
            "findings": [
                {"kind": f.kind, "severity": f.severity, "message": f.message, "detail": f.detail}
                for f in self.findings
            ],
        }


def evaluate(current: dict[str, Any], baselines: list[dict[str, Any]]) -> GateResult:
    """Run every check. Pure: no I/O, so the rules are testable without a database."""
    if not baselines:
        return GateResult(
            passed=True,
            findings=[
                Finding(
                    "note",
                    "warn",
                    "no accepted baselines yet; nothing to compare against. Accept this run "
                    "with `make eval-baseline` once you believe it.",
                )
            ],
            comparison={},
            noise={"available": False, "reason": "no baselines"},
            baselines_used=[],
        )

    findings = check_invariants(current, baselines)
    regression_findings, comparison = check_regression(current, baselines)
    findings.extend(regression_findings)
    noise = noise_floor(current, baselines)

    if noise.get("threshold_is_below_noise"):
        findings.append(
            Finding(
                "note",
                "warn",
                f"the {THRESHOLD * 100:.0f}pp threshold is below this gold set's noise floor "
                f"(minimum detectable effect {noise['minimum_detectable_effect_pp']:.2f}pp "
                f"over {noise['n_paired_items']} paired items). A verdict near the threshold "
                "is not evidence of a real change; grow the gold set.",
                {k: noise[k] for k in ("minimum_detectable_effect_pp", "n_paired_items")},
            )
        )

    passed = not any(f.severity == "fail" for f in findings)
    return GateResult(
        passed=passed,
        findings=findings,
        comparison=comparison,
        noise=noise,
        baselines_used=[str(b["run_utc"]) for b in baselines],
    )


def render(result: GateResult) -> str:
    lines: list[str] = []
    verdict = "PASS" if result.passed else "FAIL"
    lines.append(f"  eval gate: {verdict}")
    lines.append(f"  serving config: {SERVING_CONFIG} @ k={GATE_CUTOFF}")
    if result.baselines_used:
        lines.append(f"  baselines: {', '.join(result.baselines_used)}")
    lines.append("")
    if result.comparison:
        lines.append(f"  {'metric':<10} {'current':>9} {'baseline':>9} {'delta':>9}")
        for metric, row in result.comparison.items():
            lines.append(
                f"  {metric:<10} {row['current']:>9.4f} {row['baseline_mean']:>9.4f} "
                f"{row['delta_pp']:>+8.2f}pp"
            )
        lines.append("")
    for finding in result.findings:
        marker = {"fail": "FAIL", "warn": "WARN", "info": "ok  "}[finding.severity]
        lines.append(f"  [{marker}] {finding.message}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail the build on an eval regression.")
    parser.add_argument(
        "--results", type=Path, default=None, help="results.json (default: newest run)"
    )
    parser.add_argument(
        "--accept",
        action="store_true",
        help="record this run as an accepted baseline instead of gating against them",
    )
    args = parser.parse_args(argv)

    try:
        # Resolve before use: a relative --results path is natural to type and would
        # otherwise blow up in relative_to() after the work is already done.
        results_path = (args.results or latest_report()).resolve()
        if not results_path.is_file():
            raise GateError(f"no such results file: {results_path}")
        results = json.loads(results_path.read_text(encoding="utf-8"))

        if args.accept:
            record = baseline_record(results, results_path)
            BASELINES_DIR.mkdir(parents=True, exist_ok=True)
            stamp = str(record["run_utc"]).replace(":", "").replace("-", "")
            out = BASELINES_DIR / f"{stamp}.json"
            out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            print(f"  accepted baseline {record['run_utc']}")
            print(f"  metrics {record['metrics']}")
            print(f"  written {_display(out)}")
            return 0

        result = evaluate(results, load_baselines())
        gate_path = results_path.parent / "gate.json"
        gate_path.write_text(json.dumps(result.as_dict(), indent=2) + "\n", encoding="utf-8")
        print(render(result))
        print(f"\n  raw: {_display(gate_path)}")
        return 0 if result.passed else 1
    except GateError as exc:
        print(f"  eval gate: ERROR\n  {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
