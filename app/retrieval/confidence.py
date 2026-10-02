"""Evidence coverage: a measured signal for when the corpus probably cannot answer.

Knowing when *not* to answer is a first-class property of a retrieval system over
regulatory text. A compliance tool that returns ten confident-looking passages for a
question its corpus cannot answer is worse than one that says so, because the passages are
real, on-topic and misleading.

**Why not the retrieval score.** The obvious signal is "the top result scored low", and on
this corpus it does not work. Measured over the gold set's 131 answerable and 22
unanswerable questions, ranked by how well each signal separates the two (AUC; 0.5 is
chance):

    rrf_top        0.467   the serving configuration's own score -- worse than chance
    dense_margin   0.461   no signal, and pointing the wrong way
    dense_top      0.574   weak
    bm25_top       0.655   weak
    cover_top5     0.730   this one

RRF scores by rank, so the top result's score is nearly constant regardless of whether
anything relevant was found -- it cannot carry this information even in principle. The
gold set makes the problem harder on purpose: several unanswerable items note that the
near-miss text "retrieves strongly, which is what makes the question dangerous".

**What this measures instead.** The fraction of the question's analyzed terms that appear
anywhere in the retrieved passages. An unanswerable question is usually unanswerable
because of one specific term -- "penalty", "interest rate", "fees" -- that the corpus never
uses, even though the rest of the question retrieves its topic perfectly. Coverage notices
the missing term; a score that rewards the matching topic cannot.

Terms come from Postgres's own analyzer via the BM25 index, so this uses exactly the
stemming and stopword list the lexical arm uses. No second tokenizer to drift.

**It is a flag, not a refusal.** At the shipped threshold it catches about a quarter of
unanswerable questions while mislabelling 3% of answerable ones, so it is reported
alongside the passages rather than used to withhold them. Over-refusal is a documented
failure mode of abstention systems, and a signal this weak has no business making the
decision for a caller. The numbers behind the threshold are in
`docs/verification/0002-abstention-signal.md`.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Passages whose terms count toward coverage. Five rather than the full ten because the
#: signal degrades as the tail fills with loosely related text: at depth 5 the separation
#: is AUC 0.730, and widening it dilutes the coverage of a genuinely unanswerable question
#: toward the answerable distribution.
COVERAGE_DEPTH = 5

#: Below this fraction of query terms found, the response is flagged `low_evidence`.
#:
#: Chosen from the measured trade-off rather than picked round: on the gold set 0.65 flags
#: 6 of 22 unanswerable questions (27%) against 4 of 131 answerable ones (3%), for a
#: refusal precision of 0.60. The next step up, 0.70, catches 41% but mislabels 8% of
#: answerable questions -- too expensive for a flag a caller is meant to trust.
LOW_EVIDENCE_THRESHOLD = 0.65


@dataclass(frozen=True)
class Confidence:
    """How much of the question the retrieved evidence actually covers."""

    #: Fraction of the query's analyzed terms present in the top `COVERAGE_DEPTH` passages.
    evidence_coverage: float
    #: Terms from the question that appear in none of them. The actionable part: these are
    #: usually the exact words that make the question unanswerable.
    missing_terms: list[str]
    #: True when coverage is below `LOW_EVIDENCE_THRESHOLD`.
    low_evidence: bool
    #: How many passages were examined, so the number is interpretable.
    passages_considered: int

    def as_dict(self) -> dict[str, object]:
        return {
            "evidence_coverage": round(self.evidence_coverage, 4),
            "missing_terms": self.missing_terms,
            "low_evidence": self.low_evidence,
            "passages_considered": self.passages_considered,
        }


def assess(
    query_terms: list[str],
    passage_terms: list[set[str]],
    *,
    depth: int = COVERAGE_DEPTH,
    threshold: float = LOW_EVIDENCE_THRESHOLD,
) -> Confidence:
    """Score how much of the question the top passages cover.

    Pure: the caller supplies already-analyzed terms, so this is testable without a
    database and cannot drift from the analyzer by accident.

    A query with no analyzable terms -- punctuation, or only stopwords -- yields coverage
    0.0 and is flagged. That is the correct answer rather than a degenerate one: nothing
    about such a query has been matched, so nothing supports whatever came back.
    """
    considered = passage_terms[:depth]
    found: set[str] = set()
    for terms in considered:
        found |= terms

    unique_query_terms = set(query_terms)
    if not unique_query_terms:
        return Confidence(
            evidence_coverage=0.0,
            missing_terms=[],
            low_evidence=True,
            passages_considered=len(considered),
        )

    covered = unique_query_terms & found
    coverage = len(covered) / len(unique_query_terms)
    return Confidence(
        evidence_coverage=coverage,
        missing_terms=sorted(unique_query_terms - found),
        low_evidence=coverage < threshold,
        passages_considered=len(considered),
    )
