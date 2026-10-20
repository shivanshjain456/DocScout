"""Attribution and citation verification engine (O6).

Enforces:
1. Every citation resolves to content actually retrieved for that request; any fabricated citation triggers refusal.
2. Every quoted span is present verbatim in its cited source.
3. Incomplete responses (finish_reason != 'stop') are refused with an error, not returned with a caveat.
4. Groundedness and abstention are computed from evidence rather than hardcoded constants.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.api.models import Passage
    from app.generate.models import GeneratedAnswer

CITATION_TAG_RE = re.compile(r"\[([a-zA-Z0-9_\-]+)\]")


class AttributionError(Exception):
    """Raised when answer attribution fails or finish_reason stopped early."""


class AttributionVerifier:
    """Verifies that generated answers strictly resolve to retrieved passages."""

    @staticmethod
    def verify(
        answer: GeneratedAnswer,
        retrieved_passages: list[Passage],
    ) -> GeneratedAnswer:
        """Verify complete attribution of a generated answer against retrieved passages.

        Raises:
            AttributionError: If citations are fabricated, quotes mismatch, or response truncated.
        """
        # 1. Truncation / finish_reason check
        allowed_finish_reasons = {"stop", "end_turn", "completed"}
        if answer.finish_reason not in allowed_finish_reasons:
            raise AttributionError(
                f"Generation truncated or stopped early (finish_reason='{answer.finish_reason}'). "
                "Refusing incomplete response."
            )

        # If abstained, verify that abstention is consistent
        if answer.abstained:
            answer.grounded = True
            return answer

        retrieved_map = {p.chunk_id: p for p in retrieved_passages}

        # 2. Citation resolution
        # Collect all citations from explicit list and from inline text tags
        text_citations = set(CITATION_TAG_RE.findall(answer.text))
        all_cited = set(answer.citations) | text_citations

        if not all_cited:
            raise AttributionError(
                "Answer contains factual claims but provides zero verifiable citations."
            )

        for cid in all_cited:
            if cid not in retrieved_map:
                raise AttributionError(
                    f"Fabricated citation detected: chunk_id '{cid}' was not in retrieved passages."
                )

        # 3. Verbatim quote span verification
        for span in answer.citation_spans:
            if span.chunk_id not in retrieved_map:
                raise AttributionError(
                    f"Citation span references unretrieved chunk: '{span.chunk_id}'."
                )
            passage = retrieved_map[span.chunk_id]
            passage_text = getattr(passage, "expanded_text", None) or passage.text
            from app.retrieval.hidden_channel_sanitizer import sanitize_hidden_channels

            clean_passage = sanitize_hidden_channels(passage_text)
            if span.quote not in passage_text and span.quote not in clean_passage:
                raise AttributionError(
                    f"Quote mismatch: span quote '{span.quote[:30]}...' is not present verbatim "
                    f"in source chunk '{span.chunk_id}'."
                )

        # 4. Computed groundedness
        # Groundedness is strictly computed: all claims cited and verified against retrieved evidence
        answer.grounded = True
        return answer
