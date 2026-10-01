"""The gold set: loading, pinning citation IDs, and refusing to let it rot.

`EVAL_PROTOCOL.md` calls the gold set the crown-jewel artifact, and §2.1 makes
`required_citation_chunk_ids` one of its fields. Those identifiers are foreign keys into a
corpus that is re-chunked whenever ADR-0003's geometry changes, so a gold set that merely
*contains* them is a gold set that will quietly stop resolving. E-7 says as much.

So no item in this gold set is authored against a chunk ID. Every answerable item is
authored against one or more **verbatim quotes** from its source documents, and the chunk IDs
are *derived* from those quotes by `pin()`. That inversion is what makes the artifact durable:

* Re-chunking changes which chunk contains a quote, but not the quote. `pin` recomputes the
  IDs and `lint` fails loudly if the committed ones are stale, which is E-7's re-pinning
  requirement turned into a command instead of a note.
* A human reviewing an item can check it against the quote. Nobody can review a UUID.
* Resolution needs the corpus and the chunker, and **no database** -- which is what makes the
  committed IDs correct on a machine that has never run `make ingest`.

The obvious alternative, storing only the quotes and resolving at eval time, was rejected: the
committed file would then not contain the thing the protocol says it contains, every eval run
would pay the resolution cost, and a quote that stopped resolving would surface as a confusing
runtime error rather than as a lint failure on the commit that caused it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from app.ingest.ids import chunk_id
from app.ingest.pipeline import chunk_source_document
from app.ingest.source import iter_manifest_documents

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLDSET = REPO_ROOT / "evals" / "gold" / "v1" / "gold.jsonl"

# EVAL_PROTOCOL.md §2. These are the floors the protocol commits to, restated as numbers the
# linter can enforce; changing one here without changing the protocol is itself a defect.
MIN_ITEMS = 120
MIN_UNANSWERABLE_SHARE = 0.10
MIN_CANARIES = 1

ANSWER_TYPES = {"extractive", "numeric", "multi-hop", "unanswerable"}
DIFFICULTIES = {"easy", "medium", "hard"}

REQUIRED_FIELDS = (
    "item_id",
    "question",
    "answer_type",
    "difficulty",
    "source_docs",
    "evidence_quotes",
    "required_citation_chunk_ids",
    "expected_answer_key_points",
    "stable",
)


# ---------------------------------------------------------------------------------------
# The corpus side: every chunk of every document, with the identifier the ingester would give
# it. Built from the manifest and the fetched payloads only.
# ---------------------------------------------------------------------------------------
@dataclass(frozen=True)
class IndexedChunk:
    """One chunk, with the identity the ingester would store for it."""

    chunk_id: UUID
    ordinal: int
    char_start: int
    char_end: int
    text: str


@dataclass(frozen=True)
class IndexedDocument:
    """A document's canonical text and the chunks cut from it."""

    url: str
    sha256: str
    text: str
    chunks: tuple[IndexedChunk, ...]

    def chunks_containing(self, quote: str) -> tuple[IndexedChunk, ...]:
        """Every chunk whose stored text contains `quote`.

        Plural on purpose. ADR-0003 overlaps adjacent chunks by 150 characters, so a short
        quote near a boundary genuinely lives in two chunks and either is a correct citation.
        Collapsing that to one would silently mark a correct citation wrong.
        """
        return tuple(c for c in self.chunks if quote in c.text)


def build_corpus_index(
    count_tokens: Callable[[str], int], *, limit: int | None = None
) -> dict[str, IndexedDocument]:
    """Chunk every manifest document and give each chunk the ID the ingester would give it.

    Uses `chunk_source_document`, the same function the ingester calls, so the gold set can
    never be pinned against a chunker that differs from the shipped one.
    """
    index: dict[str, IndexedDocument] = {}
    for document in iter_manifest_documents(limit=limit):
        cut = chunk_source_document(document, count_tokens)
        chunks = tuple(
            IndexedChunk(
                chunk_id=chunk_id(document.sha256, c.char_start, c.char_end),
                ordinal=c.ordinal,
                char_start=c.char_start,
                char_end=c.char_end,
                text=c.text,
            )
            for c in cut.chunks
        )
        index[document.url] = IndexedDocument(
            url=document.url, sha256=document.sha256, text=cut.text, chunks=chunks
        )
    return index


def default_token_counter() -> Callable[[str], int]:
    """The production tokenizer, loaded lazily.

    Imported inside the function because loading the embedding model costs about thirteen
    seconds and downloads weights; `lint --no-resolve` and the pure schema checks must stay
    usable without paying that.
    """
    from app.ingest.embed import Embedder

    return Embedder().count_tokens


# ---------------------------------------------------------------------------------------
# The gold set side
# ---------------------------------------------------------------------------------------
def load_goldset(path: Path = DEFAULT_GOLDSET) -> list[dict[str, Any]]:
    """Read the JSONL gold set, reporting the line number of a malformed record."""
    items: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: {exc}") from exc
            if not isinstance(item, dict):
                raise ValueError(f"{path}:{lineno}: expected a JSON object")
            items.append(item)
    return items


def write_goldset(items: Iterable[dict[str, Any]], path: Path = DEFAULT_GOLDSET) -> None:
    """Write the gold set back, one compact JSON object per line, key order preserved."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def is_unanswerable(item: dict[str, Any]) -> bool:
    return item.get("answer_type") == "unanswerable"


def resolve_item(
    item: dict[str, Any], index: dict[str, IndexedDocument]
) -> tuple[list[str], list[str]]:
    """Return (chunk ids, problems) for one item, resolved from its quotes.

    Order is deterministic: documents in the order `source_docs` lists them, chunks in
    ordinal order, duplicates removed. A gold set whose IDs reshuffle between runs would
    produce spurious diffs and make review meaningless.
    """
    problems: list[str] = []
    resolved: list[str] = []
    seen: set[str] = set()

    for url in item.get("source_docs", []):
        document = index.get(url)
        if document is None:
            problems.append(f"source_doc not in corpus manifest: {url}")

    for quote in item.get("evidence_quotes", []):
        hits: list[IndexedChunk] = []
        for url in item.get("source_docs", []):
            document = index.get(url)
            if document is None:
                continue
            hits.extend(document.chunks_containing(quote))
        if not hits:
            problems.append(f"evidence quote not found in any source_doc: {quote[:80]!r}")
            continue
        for hit in sorted(hits, key=lambda c: c.ordinal):
            key = str(hit.chunk_id)
            if key not in seen:
                seen.add(key)
                resolved.append(key)

    return resolved, problems


def pin(
    items: list[dict[str, Any]], index: dict[str, IndexedDocument]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fill `required_citation_chunk_ids` from each item's quotes. Returns (items, problems)."""
    problems: list[str] = []
    for item in items:
        if is_unanswerable(item):
            item["required_citation_chunk_ids"] = []
            continue
        resolved, item_problems = resolve_item(item, index)
        problems.extend(f"{item.get('item_id', '?')}: {p}" for p in item_problems)
        item["required_citation_chunk_ids"] = resolved
    return items, problems


# ---------------------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------------------
def lint(items: list[dict[str, Any]], index: dict[str, IndexedDocument] | None = None) -> list[str]:
    """Every rule `EVAL_PROTOCOL.md` §2 states, plus the ones its traps imply.

    Returns a list of problems; empty means the gold set is valid. Resolution-dependent
    checks are skipped when `index` is None, and the caller is told so.
    """
    problems: list[str] = []

    # --- set-level floors (§2) -----------------------------------------------------------
    if len(items) < MIN_ITEMS:
        problems.append(f"gold set has {len(items)} items, protocol floor is {MIN_ITEMS}")

    ids = [item.get("item_id") for item in items]
    duplicates = [key for key, n in Counter(ids).items() if n > 1]
    if duplicates:
        problems.append(f"duplicate item_id(s): {sorted(map(str, duplicates))}")

    unanswerable = [i for i in items if is_unanswerable(i)]
    share = len(unanswerable) / len(items) if items else 0.0
    if share < MIN_UNANSWERABLE_SHARE:
        problems.append(
            f"unanswerable share is {share:.1%}, protocol floor is "
            f"{MIN_UNANSWERABLE_SHARE:.0%} ({len(unanswerable)} of {len(items)})"
        )

    canaries = [i for i in items if i.get("canary")]
    if len(canaries) < MIN_CANARIES:
        problems.append(f"{len(canaries)} canary items, protocol floor is {MIN_CANARIES}")

    # --- item-level schema (§2.1) --------------------------------------------------------
    for item in items:
        key = item.get("item_id", "<no item_id>")

        for field in REQUIRED_FIELDS:
            if field not in item:
                problems.append(f"{key}: missing required field {field!r}")

        if item.get("answer_type") not in ANSWER_TYPES:
            problems.append(f"{key}: answer_type {item.get('answer_type')!r} not in {ANSWER_TYPES}")
        if item.get("difficulty") not in DIFFICULTIES:
            problems.append(f"{key}: difficulty {item.get('difficulty')!r} not in {DIFFICULTIES}")
        if not str(item.get("question", "")).strip():
            problems.append(f"{key}: empty question")
        if not isinstance(item.get("stable"), bool):
            problems.append(f"{key}: 'stable' must be a boolean")

        if is_unanswerable(item):
            # An unanswerable item that cites something is not unanswerable.
            for field in (
                "source_docs",
                "evidence_quotes",
                "required_citation_chunk_ids",
                "expected_answer_key_points",
            ):
                if item.get(field):
                    problems.append(f"{key}: unanswerable item must have empty {field}")
            if not str(item.get("unanswerable_reason", "")).strip():
                problems.append(
                    f"{key}: unanswerable item needs an 'unanswerable_reason' saying why the "
                    "corpus cannot answer it, or it cannot be reviewed"
                )
        else:
            for field in ("source_docs", "evidence_quotes", "expected_answer_key_points"):
                if not item.get(field):
                    problems.append(f"{key}: answerable item has empty {field}")
            if not item.get("required_citation_chunk_ids"):
                problems.append(f"{key}: no required_citation_chunk_ids (run `pin`)")

        for raw in item.get("required_citation_chunk_ids", []):
            try:
                if UUID(str(raw)).version != 5:
                    problems.append(f"{key}: citation {raw} is not a version-5 UUID (ADR-0005)")
            except ValueError:
                problems.append(f"{key}: citation {raw!r} is not a UUID")

        if item.get("canary") and not item.get("forbidden_strings"):
            problems.append(
                f"{key}: a canary item needs 'forbidden_strings', or nothing distinguishes "
                "resisting the injection from complying with it"
            )

    # --- resolution-dependent checks -----------------------------------------------------
    if index is None:
        return problems

    known_urls = set(index)
    for item in items:
        key = item.get("item_id", "<no item_id>")
        if is_unanswerable(item):
            # Distractors are claims about the corpus too, so they must exist in it.
            for url in item.get("distractor_docs", []):
                if url not in known_urls:
                    problems.append(f"{key}: distractor_doc not in corpus manifest: {url}")
            continue

        resolved, item_problems = resolve_item(item, index)
        problems.extend(f"{key}: {p}" for p in item_problems)

        committed = list(item.get("required_citation_chunk_ids", []))
        if committed != resolved and resolved:
            problems.append(
                f"{key}: committed citation IDs are stale. Committed {committed}, "
                f"corpus resolves to {resolved}. Re-pin (EVAL_PROTOCOL E-7)."
            )

        # E-5: an item must not be answerable from outside its declared source_docs. A
        # verbatim quote appearing in another document means the question is ambiguous --
        # usually boilerplate that the author mistook for evidence.
        for quote in item.get("evidence_quotes", []):
            leaked = [
                url
                for url, document in index.items()
                if url not in item.get("source_docs", []) and quote in document.text
            ]
            if leaked:
                problems.append(
                    f"{key}: evidence quote also appears in {len(leaked)} document(s) outside "
                    f"source_docs ({leaked[0]}...): the quote is not evidence for this item (E-5)"
                )

    return problems


# ---------------------------------------------------------------------------------------
# E-6: the second labelling pass
# ---------------------------------------------------------------------------------------
# Spelled-out quantities that regulatory drafting prefers, mapped to the digits a key point
# is likely to use. Without this, "within sixty days" and "60 days" look like a disagreement.
_NUMBER_WORDS = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "twelve": "12",
    "fifteen": "15",
    "twenty": "20",
    "twentyfive": "25",
    "thirty": "30",
    "forty": "40",
    "fortyfive": "45",
    "fifty": "50",
    "sixty": "60",
    "seventyfive": "75",
    "ninety": "90",
    "hundred": "100",
}

_STOPWORDS = frozenset(
    """a an and are as at be been by для for from has have in into is it its must not of on or
    per shall than that the their there these this to under upon was were which with within
    only also any such each both may can will would should""".split()
)


def _salient_tokens(text: str) -> set[str]:
    """Tokens a reviewer would actually check: digit runs and content words."""
    lowered = text.lower().replace("-", "").replace(",", "")
    tokens: set[str] = set()
    for raw in re.findall(r"[a-z]+|\d+", lowered):
        if raw.isdigit():
            tokens.add(raw.lstrip("0") or "0")
        elif raw in _NUMBER_WORDS:
            tokens.add(_NUMBER_WORDS[raw])
        elif len(raw) >= 4 and raw not in _STOPWORDS:
            # Crude singularisation so "units" in a quote grounds "unit" in a key point.
            # Not stemming: a wrong stem would hide a real disagreement, which is the one
            # thing this pass exists to surface.
            tokens.add(raw[:-1] if len(raw) >= 5 and raw.endswith("s") else raw)
    return tokens


def review_item(item: dict[str, Any]) -> tuple[float, list[str]]:
    """Score how far an item's key points are grounded in its own evidence quotes.

    This is the second pass required by E-6, and it is deliberately NOT a re-reading. One
    agent re-reading its own work agrees with itself by construction; the resulting number
    would be self-agreement dressed up as review. Instead the pass is mechanical and can
    genuinely disagree: it asks whether every salient token of every key point -- each
    number, amount, date part and content word -- actually occurs in the text the item cites
    as its evidence. An item whose key point asserts something its own quote does not contain
    is either mis-labelled or under-quoted, and both are defects worth catching.

    Returns (grounding ratio, unsupported tokens). It cannot detect a key point that is
    wrong in a way the quote happens to share, which is why §2.1's disclosure about
    self-agreement still applies in full.
    """
    if is_unanswerable(item):
        return 1.0, []
    evidence = _salient_tokens(" ".join(item.get("evidence_quotes", [])))
    claimed: set[str] = set()
    for point in item.get("expected_answer_key_points", []):
        claimed |= _salient_tokens(point)
    if not claimed:
        return 0.0, []
    missing = sorted(claimed - evidence)
    return (len(claimed) - len(missing)) / len(claimed), missing


def review(items: list[dict[str, Any]], *, threshold: float = 0.6) -> list[str]:
    """Report every item whose key points are not sufficiently grounded in its quotes."""
    flagged: list[str] = []
    for item in items:
        ratio, missing = review_item(item)
        if ratio < threshold:
            flagged.append(
                f"{item.get('item_id')}: grounding {ratio:.0%} -- key-point tokens absent from "
                f"the evidence quote: {missing}"
            )
    return flagged


def summarise(items: list[dict[str, Any]]) -> str:
    by_type = Counter(str(i.get("answer_type")) for i in items)
    by_diff = Counter(str(i.get("difficulty")) for i in items)
    citations = [
        len(i.get("required_citation_chunk_ids", [])) for i in items if not is_unanswerable(i)
    ]
    docs = Counter(url for i in items for url in i.get("source_docs", []))
    lines = [
        f"items                 {len(items)}",
        f"  by answer_type      {dict(sorted(by_type.items()))}",
        f"  by difficulty       {dict(sorted(by_diff.items()))}",
        f"  canaries            {sum(1 for i in items if i.get('canary'))}",
        f"  stable              {sum(1 for i in items if i.get('stable'))} of {len(items)}",
        f"unanswerable share    {sum(1 for i in items if is_unanswerable(i)) / max(len(items), 1):.1%}",
        f"documents covered     {len(docs)}",
        f"citations per item    min {min(citations, default=0)} / max {max(citations, default=0)}"
        f" / total {sum(citations)}",
    ]
    return "\n".join("  " + line for line in lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.evals.goldset")
    parser.add_argument("command", choices=["pin", "lint", "stats", "review"])
    parser.add_argument("--path", type=Path, default=DEFAULT_GOLDSET)
    parser.add_argument(
        "--no-resolve",
        action="store_true",
        help="skip corpus resolution (schema checks only; no model load, no corpus read)",
    )
    args = parser.parse_args(argv)

    items = load_goldset(args.path)

    if args.command == "stats":
        print(summarise(items))
        return 0

    if args.command == "review":
        flagged = review(items)
        for problem in flagged:
            print(f"  REVIEW  {problem}")
        answerable = [i for i in items if not is_unanswerable(i)]
        rate = len(flagged) / max(len(answerable), 1)
        print(
            f"\n  pass-2 grounding check: {len(flagged)} of {len(answerable)} answerable items "
            f"flagged ({rate:.1%} disagreement with pass 1)"
        )
        return 0

    index: dict[str, IndexedDocument] | None = None
    if not args.no_resolve:
        index = build_corpus_index(default_token_counter())

    if args.command == "pin":
        if index is None:
            print("pin cannot run with --no-resolve", file=sys.stderr)
            return 2
        items, problems = pin(items, index)
        write_goldset(items, args.path)
        for problem in problems:
            print(f"  PROBLEM  {problem}", file=sys.stderr)
        pinned = sum(len(i.get("required_citation_chunk_ids", [])) for i in items)
        print(f"  pinned {pinned} citation IDs across {len(items)} items -> {args.path}")
        return 1 if problems else 0

    problems = lint(items, index)
    for problem in problems:
        print(f"  FAIL  {problem}", file=sys.stderr)
    if problems:
        print(f"\n  {len(problems)} problem(s)", file=sys.stderr)
        return 1
    scope = "schema only (--no-resolve)" if index is None else "schema + corpus resolution"
    print(f"  gold set OK: {len(items)} items, {scope}")
    print(summarise(items))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
