"""Tests for the gold set and its linter.

Two different things are tested here and conflating them would be a mistake.

The first is the **linter itself**: it is the thing that will be trusted to say a gold set is
valid, so each of its rules is exercised against a deliberately broken item. A linter whose
rules are never seen to fire is indistinguishable from a linter that returns an empty list.

The second is the **committed gold set**: that it satisfies every floor `EVAL_PROTOCOL.md` §2
states, and -- the check that matters most -- that its committed citation IDs still resolve
against the corpus. That last test is the one that will fail the day someone changes chunk
geometry without re-pinning, which is exactly E-7's requirement made enforceable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.evals.goldset import (
    DEFAULT_GOLDSET,
    MIN_ITEMS,
    MIN_UNANSWERABLE_SHARE,
    build_corpus_index,
    default_token_counter,
    is_unanswerable,
    lint,
    load_goldset,
    review_item,
)

GOLD = load_goldset()
METADATA = json.loads((DEFAULT_GOLDSET.parent / "metadata.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def corpus_index() -> dict[str, Any]:
    """The corpus chunked with the production chunker. Needs the tokenizer, not a database."""
    try:
        counter = default_token_counter()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"embedding model unavailable: {exc}")
    return build_corpus_index(counter)


def valid_item(**overrides: Any) -> dict[str, Any]:
    """A minimal item that passes every rule, so a test can break exactly one thing."""
    item = {
        "item_id": "t-001",
        "question": "What does the circular say?",
        "answer_type": "extractive",
        "difficulty": "easy",
        "source_docs": ["https://example.invalid/doc"],
        "evidence_quotes": ["some text"],
        "required_citation_chunk_ids": ["3a2b3d9d-69ba-5bd9-a9cd-1b5bb17e588b"],
        "expected_answer_key_points": ["a fact"],
        "canary": False,
        "forbidden_strings": [],
        "distractor_docs": [],
        "unanswerable_reason": "",
        "stable": True,
        "notes": "",
    }
    item.update(overrides)
    return item


# ---------------------------------------------------------------------------------------
# The linter's rules must actually fire
# ---------------------------------------------------------------------------------------
def test_linter_accepts_a_valid_item_set() -> None:
    """The baseline. Without this, every test below could pass for the wrong reason."""
    items = [valid_item(item_id=f"t-{n:03d}") for n in range(MIN_ITEMS)]
    items += [
        valid_item(
            item_id=f"u-{n:03d}",
            answer_type="unanswerable",
            source_docs=[],
            evidence_quotes=[],
            required_citation_chunk_ids=[],
            expected_answer_key_points=[],
            unanswerable_reason="the corpus does not cover it",
        )
        for n in range(20)
    ]
    items.append(valid_item(item_id="c-001", canary=True, forbidden_strings=["bad"]))
    assert lint(items) == []


def test_linter_rejects_a_set_below_the_size_floor() -> None:
    problems = lint([valid_item()])
    assert any("protocol floor" in p and "items" in p for p in problems)


def test_linter_rejects_duplicate_item_ids() -> None:
    problems = lint([valid_item(), valid_item()])
    assert any("duplicate item_id" in p for p in problems)


def test_linter_rejects_too_few_unanswerable_items() -> None:
    problems = lint([valid_item(item_id=f"t-{n}") for n in range(MIN_ITEMS)])
    assert any("unanswerable share" in p for p in problems)


def test_linter_rejects_a_set_with_no_canary() -> None:
    problems = lint([valid_item(item_id=f"t-{n}") for n in range(MIN_ITEMS)])
    assert any("canary" in p for p in problems)


@pytest.mark.parametrize("field", ["item_id", "question", "answer_type", "stable"])
def test_linter_rejects_a_missing_required_field(field: str) -> None:
    item = valid_item()
    del item[field]
    assert any(f"missing required field {field!r}" in p for p in lint([item]))


def test_linter_rejects_an_unknown_answer_type() -> None:
    assert any("answer_type" in p for p in lint([valid_item(answer_type="freeform")]))


def test_linter_rejects_an_unanswerable_item_that_cites_something() -> None:
    """An unanswerable item with a citation is not unanswerable; it is a mislabelled item."""
    item = valid_item(
        answer_type="unanswerable",
        source_docs=[],
        evidence_quotes=[],
        expected_answer_key_points=[],
        unanswerable_reason="nothing covers it",
    )
    problems = lint([item])
    assert any("must have empty required_citation_chunk_ids" in p for p in problems)


def test_linter_requires_a_reason_on_unanswerable_items() -> None:
    item = valid_item(
        answer_type="unanswerable",
        source_docs=[],
        evidence_quotes=[],
        required_citation_chunk_ids=[],
        expected_answer_key_points=[],
    )
    assert any("unanswerable_reason" in p for p in lint([item]))


def test_linter_rejects_an_answerable_item_with_no_citations() -> None:
    assert any("run `pin`" in p for p in lint([valid_item(required_citation_chunk_ids=[])]))


def test_linter_rejects_a_citation_that_is_not_a_version_5_uuid() -> None:
    """A v4 or v7 identifier here means something bypassed ADR-0005's derivation."""
    v7 = "01a0f888-f191-7c09-a02b-29b7c6da4b11"
    assert any("version-5" in p for p in lint([valid_item(required_citation_chunk_ids=[v7])]))


def test_linter_requires_forbidden_strings_on_a_canary() -> None:
    assert any("forbidden_strings" in p for p in lint([valid_item(canary=True)]))


# ---------------------------------------------------------------------------------------
# The committed gold set
# ---------------------------------------------------------------------------------------
def test_committed_goldset_passes_schema_lint() -> None:
    assert lint(GOLD) == []


def test_committed_goldset_meets_the_protocol_floors() -> None:
    assert len(GOLD) >= MIN_ITEMS
    share = sum(1 for i in GOLD if is_unanswerable(i)) / len(GOLD)
    assert share >= MIN_UNANSWERABLE_SHARE, f"unanswerable share {share:.1%}"
    assert sum(1 for i in GOLD if i.get("canary")) >= 1


def test_committed_goldset_covers_every_corpus_document() -> None:
    """Coverage is not a protocol floor, but a document nothing asks about is untested."""
    cited = {url for item in GOLD for url in item["source_docs"]}
    manifest = json.loads(Path("corpus/raw/manifest.json").read_text(encoding="utf-8"))
    expected = {d["url"] for d in manifest["documents"] if d.get("ok")}
    assert cited == expected, f"documents with no gold item: {sorted(expected - cited)}"


def test_every_committed_citation_resolves_against_the_corpus(
    corpus_index: dict[str, Any],
) -> None:
    """The test that enforces E-7.

    If chunk geometry changes and nobody re-pins, the committed IDs stop matching what the
    corpus resolves to, and this fails. That is the whole reason the gold set is authored
    against quotes rather than against identifiers.
    """
    assert lint(GOLD, corpus_index) == []


def test_metadata_matches_the_committed_file(corpus_index: dict[str, Any]) -> None:
    """Metadata that drifts from the artifact it describes is worse than no metadata."""
    import hashlib

    digest = hashlib.sha256(DEFAULT_GOLDSET.read_bytes()).hexdigest()
    assert METADATA["sha256_of_gold_jsonl"] == digest, (
        "metadata.json records a different gold.jsonl than the one committed; regenerate it"
    )
    assert METADATA["item_count"] == len(GOLD)
    assert METADATA["composition"]["canaries"] == sum(1 for i in GOLD if i.get("canary"))
    assert METADATA["composition"]["stable"] == sum(1 for i in GOLD if i.get("stable"))


def test_metadata_does_not_claim_inter_rater_reliability() -> None:
    """U-17 and §2.1: one author means self-agreement, and no kappa may be reported.

    This is a test because the temptation to quietly upgrade 'self-agreement' to a kappa is
    exactly the kind of flattering number the protocol exists to prevent.
    """
    labelling = METADATA["labelling"]
    assert "SELF-AGREEMENT" in labelling["disclosure"]
    blob = json.dumps(METADATA).lower()
    assert "kappa" not in blob or "no cohen's kappa is reported" in blob
    assert "cohen" not in blob or "none may be computed" in blob


def test_review_pass_grounds_key_points_in_evidence() -> None:
    """Every item except the one disclosed residual must be grounded in its own quotes."""
    flagged = [i["item_id"] for i in GOLD if review_item(i)[0] < 0.6]
    assert flagged == ["g-009"], (
        f"unexpected ungrounded items {flagged}; metadata discloses only g-009"
    )
    assert METADATA["labelling"]["residual_flagged_after_correction"] == len(flagged)


def test_canary_items_forbid_the_injected_payload() -> None:
    """The canary document's injected strings must be named by the items that retrieve it."""
    canaries = [i for i in GOLD if i.get("canary")]
    assert canaries, "no canary items"
    joined = " ".join(s for i in canaries for s in i["forbidden_strings"])
    assert "AUDIT OVERRIDE ACCEPTED" in joined
    assert "T+9" in joined
