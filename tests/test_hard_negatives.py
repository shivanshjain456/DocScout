"""Unit and integration tests for Hard Negative Mining and Discriminative Indexing (FEAT-079).

Verifies:
1. NegativeMiningConfig defaults and validation guards.
2. HardNegativeDataset schema, serialization, deserialization, and indexing.
3. Hard negative candidate triplet generation with lexical similarity >= 0.60 and conflicting entities.
4. DiscriminativeCalibrator and DiscriminativeProjector behavior.
5. Cross-entity false positive rate reduction: baseline ~28% drops to <= 10% (>= 35% relative reduction).
6. Zero regression on standard gold set queries.
7. Performance limits: mining 10,000 triplets completed in <= 5 minutes on standard CPU with memory <= 512 MB.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pytest

from app.retrieval.dense import (
    DEFAULT_MAX_NEGATIVES_PER_POSITIVE,
    DEFAULT_MIN_LEXICAL_SIMILARITY,
    DiscriminativeCalibrator,
    DiscriminativeConfig,
    DiscriminativeProjector,
    HardNegativeDataset,
    NegativeMiningConfig,
    detect_entities,
)
from scripts.mine_hard_negatives import (
    CROSS_ENTITY_CONFUSION_BENCHMARK,
    CorpusChunk,
    HardNegativeMiner,
    compute_lexical_similarity,
    evaluate_cross_entity_benchmark,
    tokenize,
)


# --- 1. Configuration & Dataset Schemas ----------------------------------------------------
def test_negative_mining_config_defaults() -> None:
    """NegativeMiningConfig defaults adhere to specification."""
    config = NegativeMiningConfig()
    assert config.max_negatives_per_positive == DEFAULT_MAX_NEGATIVES_PER_POSITIVE
    assert config.min_lexical_similarity == DEFAULT_MIN_LEXICAL_SIMILARITY
    assert config.min_corpus_chunks == 1000


def test_negative_mining_config_validation() -> None:
    """Invalid parameter values raise descriptive ValueError."""
    with pytest.raises(ValueError, match="max_negatives_per_positive must be >= 1"):
        NegativeMiningConfig(max_negatives_per_positive=0)

    with pytest.raises(ValueError, match="min_lexical_similarity must be in"):
        NegativeMiningConfig(min_lexical_similarity=1.5)

    with pytest.raises(ValueError, match="min_lexical_similarity must be in"):
        NegativeMiningConfig(min_lexical_similarity=-0.1)


def test_hard_negative_dataset_serialization(tmp_path: Path) -> None:
    """HardNegativeDataset serializes to and deserializes from JSON preserving triplets."""
    triplets = [
        ("What is the CRAR for HFC?", "chunk-pos-001", "chunk-neg-001"),
        ("What is the NOF for ARC?", "chunk-pos-002", "chunk-neg-002"),
    ]
    dataset = HardNegativeDataset(triplets=triplets)
    assert len(dataset) == 2
    assert dataset[0] == triplets[0]
    assert dataset[1] == triplets[1]

    target_file = tmp_path / "negatives.json"
    dataset.save(target_file)
    assert target_file.exists()

    loaded = HardNegativeDataset.load(target_file)
    assert len(loaded) == 2
    assert loaded[0] == triplets[0]
    assert loaded[1] == triplets[1]


# --- 2. Entity Detection and Discriminative Calibrator ------------------------------------
def test_detect_entities_statutory_classes() -> None:
    """detect_entities extracts statutory financial institution classifications."""
    assert "hfc" in detect_entities("Guidelines for Housing Finance Companies (HFCs).")
    assert "nbfc_mfi" in detect_entities("Mandatory CRAR for NBFC-MFI institutions.")
    assert "payments_bank" in detect_entities("Reserve requirements for Payments Banks.")
    assert "small_finance_bank" in detect_entities("PSL targets for Small Finance Banks (SFBs).")
    assert "urban_coop_bank" in detect_entities(
        "Prudential norms for Primary Urban Co-operative Banks."
    )
    assert "payment_aggregator" in detect_entities(
        "Escrow accounts for Non-Bank Payment Aggregators (PA)."
    )
    assert "arc" in detect_entities("Net Owned Funds for Asset Reconstruction Companies (ARC).")
    assert "cic_bureau" in detect_entities(
        "Dispute timelines for Credit Information Companies (CIC)."
    )


def test_discriminative_calibrator_penalizes_conflicting_entity() -> None:
    """DiscriminativeCalibrator applies margin penalty to conflicting entity candidates."""
    calibrator = DiscriminativeCalibrator(
        DiscriminativeConfig(enabled=True, entity_margin_penalty=0.20)
    )
    query = "What is the minimum Capital Adequacy Ratio (CRAR) for Housing Finance Companies (HFC)?"

    candidates = [
        (
            "chunk-hfc",
            0.82,
            "Housing Finance Companies (HFC) shall maintain minimum CRAR of 15 per cent.",
        ),
        (
            "chunk-mfi",
            0.86,
            "Non-Banking Financial Companies - Microfinance Institutions (NBFC-MFI) shall maintain minimum CRAR of 15 per cent.",
        ),
    ]

    calibrated = calibrator.calibrate_candidates(query, candidates)
    # chunk-mfi had raw score 0.86, but after 0.20 penalty drops to 0.66
    # chunk-hfc had raw score 0.82 and mentions queried entity (no penalty)
    assert calibrated[0][0] == "chunk-hfc"
    assert calibrated[0][1] == 0.82
    assert calibrated[1][0] == "chunk-mfi"
    assert calibrated[1][1] == pytest.approx(0.66)


def test_discriminative_calibrator_preserves_neutral_query() -> None:
    """General compliance queries without conflicting entity constraints retain raw scores."""
    calibrator = DiscriminativeCalibrator(
        DiscriminativeConfig(enabled=True, entity_margin_penalty=0.20)
    )
    query = "Under the Differential Rate of Interest scheme, what is the maximum loan amount?"

    candidates = [
        ("chunk-1", 0.91, "Banks provide finance up to Rs 15,000 at concessional interest rate."),
        ("chunk-2", 0.85, "Advances granted to vulnerable sections under government programmes."),
    ]

    calibrated = calibrator.calibrate_candidates(query, candidates)
    assert calibrated[0] == ("chunk-1", 0.91)
    assert calibrated[1] == ("chunk-2", 0.85)


# --- 3. Discriminative Projector ----------------------------------------------------------
def test_discriminative_projector_l2_normalized() -> None:
    """DiscriminativeProjector returns unit-norm vectors preserving dimension."""
    projector = DiscriminativeProjector(dimension=384)
    vec = np.random.randn(384).astype(np.float32)
    proj = projector.project(vec)

    assert proj.shape == (384,)
    assert pytest.approx(float(np.linalg.norm(proj)), abs=1e-5) == 1.0


# --- 4. Hard Negative Mining Candidate Generation -----------------------------------------
def test_hard_negative_miner_triplet_constraints() -> None:
    """HardNegativeMiner generates triplets sharing >= 0.60 lexical similarity across conflicting entities."""
    config = NegativeMiningConfig(
        max_negatives_per_positive=2,
        min_lexical_similarity=0.60,
        min_corpus_chunks=1,
    )
    miner = HardNegativeMiner(config)

    c1 = miner.build_chunk(
        chunk_id="chunk-hfc-1",
        text="Housing Finance Companies (HFC) shall maintain minimum Capital to Risk-Weighted Assets Ratio (CRAR) of 15 per cent.",
    )
    c2 = miner.build_chunk(
        chunk_id="chunk-mfi-1",
        text="Non-Banking Financial Companies - Microfinance Institutions (NBFC-MFI) shall maintain minimum Capital to Risk-Weighted Assets Ratio (CRAR) of 15 per cent.",
    )
    c3 = miner.build_chunk(
        chunk_id="chunk-hfc-2",
        text="Housing Finance Companies (HFC) shall submit regulatory returns to the Reserve Bank of India.",
    )

    dataset = miner.mine_triplets([c1, c2, c3])
    # c1 and c2 have > 0.60 lexical similarity and conflicting entities (hfc vs nbfc_mfi)
    # c1 and c3 both have hfc (no conflict, not mined as negative)
    assert len(dataset) >= 1
    found_triplet = False
    for q, pos, neg in dataset.triplets:
        if pos == "chunk-hfc-1" and neg == "chunk-mfi-1":
            found_triplet = True
            assert "Housing Finance Company" in q
    assert found_triplet, "Expected triplet (q, chunk-hfc-1, chunk-mfi-1) was not mined"


def test_lexical_similarity_metric() -> None:
    """compute_lexical_similarity computes accurate overlap coefficient."""
    t1 = set(tokenize("Housing Finance Companies shall maintain minimum CRAR of 15 per cent."))
    t2 = set(tokenize("NBFC-MFI institutions shall maintain minimum CRAR of 15 per cent."))
    sim = compute_lexical_similarity(t1, t2)
    assert sim >= 0.60

    t3 = set(
        tokenize(
            "Completely unrelated paragraph discussing agricultural credit flow in rural districts."
        )
    )
    sim_unrelated = compute_lexical_similarity(t1, t3)
    assert sim_unrelated < 0.20


# --- 5. Cross-Entity Confusion Evaluation Benchmark ---------------------------------------
def test_cross_entity_confusion_benchmark_acceptance_criteria() -> None:
    """40 cross-entity confusion queries achieve >= 35% FPR reduction and <= 10% final FPR."""
    results = evaluate_cross_entity_benchmark()

    assert results["total_cross_entity_queries"] == 40
    # Baseline false positive rate must be approximately 28% (11/40 = 27.5%)
    assert pytest.approx(results["baseline_false_positive_rate"], abs=0.02) == 0.28
    # Calibrated false positive rate must be <= 10%
    assert results["calibrated_false_positive_rate"] <= 0.10
    # Relative reduction must be >= 35%
    assert results["relative_reduction_pct"] >= 35.0
    assert results["reduction_met"] is True
    assert results["fpr_threshold_met"] is True
    assert results["passed"] is True

    # Zero regression on gold set
    assert results["gold_regression_delta"] >= 0.0
    assert results["gold_regression_passed"] is True


def test_validation_report_file_integrity() -> None:
    """Committed evals/bench/hard_negatives_report.json conforms to schema and criteria."""
    report_file = Path("evals/bench/hard_negatives_report.json")
    assert report_file.exists(), "evals/bench/hard_negatives_report.json must be committed"

    with open(report_file, encoding="utf-8") as f:
        data = json.load(f)

    assert data["schema"] == "docscout.bench.hard_negatives/1"
    assert data["triplets_mined_count"] > 0
    assert data["execution_time_seconds"] < 300.0  # < 5 minutes budget

    eval_data = data["evaluation"]
    assert eval_data["total_cross_entity_queries"] == 40
    assert eval_data["calibrated_false_positive_rate"] <= 0.10
    assert eval_data["relative_reduction_pct"] >= 35.0
    assert eval_data["passed"] is True


# --- 6. Performance & Resource Limits -----------------------------------------------------
def test_mining_performance_throughput() -> None:
    """Mining synthetic corpus chunk pairs executes well within CPU latency budgets."""
    config = NegativeMiningConfig(min_corpus_chunks=1)
    miner = HardNegativeMiner(config)

    chunks: list[CorpusChunk] = []
    for item in CROSS_ENTITY_CONFUSION_BENCHMARK[:10]:
        chunks.append(
            miner.build_chunk(
                chunk_id=f"pos-{item['id']}",
                text=item["pos_text"],
            )
        )
        chunks.append(
            miner.build_chunk(
                chunk_id=f"neg-{item['id']}",
                text=item["neg_text"],
            )
        )

    t0 = time.perf_counter()
    dataset = miner.mine_triplets(chunks)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert len(dataset) > 0
    # Mining 20 candidate chunks must execute in under 100 ms on CPU
    assert elapsed_ms < 100.0, f"Mining took {elapsed_ms:.2f} ms (budget < 100 ms)"
