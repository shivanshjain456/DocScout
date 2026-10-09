"""Generation engine for citation-grounded regulatory question answering.

Provides a deterministic offline local generator that executes on CPU with zero credentials,
as well as hosted provider integrations (OpenAI, Anthropic) when credentials are provided.
"""

from __future__ import annotations

import os
import re
import time
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.api.models import Passage

from app.generate.injection import scan_injection_signatures
from app.generate.models import CitationSpan, GeneratedAnswer, GenerationConfig
from app.generate.prompt import build_generation_prompt

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
WORD_RE = re.compile(r"\b\w{3,}\b")


STOP_WORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "by",
    "from",
    "as",
    "is",
    "was",
    "are",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "what",
    "which",
    "who",
    "whom",
    "this",
    "that",
    "these",
    "those",
    "am",
    "it",
    "its",
    "can",
    "could",
    "shall",
    "should",
    "will",
    "would",
    "may",
    "might",
    "must",
    "how",
    "many",
    "when",
    "where",
    "why",
}


class BaseGenerator(Protocol):
    """Protocol for generating citation-grounded answers from retrieved passages."""

    def generate(
        self,
        query: str,
        passages: list[Passage],
        config: GenerationConfig | None = None,
    ) -> GeneratedAnswer: ...


class DeterministicLocalGenerator:
    """Offline, deterministic CPU generator for regulatory text.

    Synthesizes answers exclusively from retrieved chunks without external API dependencies,
    binds explicit chunk citations, filters prompt injection payloads, and abstains
    when evidence is insufficient.
    """

    def __init__(self, model_id: str = "docscout-local-deterministic/1") -> None:
        self.model_id = model_id

    def generate(
        self,
        query: str,
        passages: list[Passage],
        config: GenerationConfig | None = None,
    ) -> GeneratedAnswer:
        start_t = time.perf_counter()
        _ = config

        if not passages:
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            return GeneratedAnswer(
                text="Insufficient evidence: the provided regulatory documents do not contain sufficient evidence to answer this question.",
                citations=[],
                citation_spans=[],
                grounded=True,
                abstained=True,
                abstention_reason="No relevant passages retrieved from corpus.",
                model_id=self.model_id,
                latency_ms=elapsed_ms,
            )

        # Extract substantive query keywords (excluding stop words)
        query_words = {w for w in WORD_RE.findall(query.lower()) if w not in STOP_WORDS}
        if not query_words:
            query_words = set(WORD_RE.findall(query.lower()))

        candidate_claims: list[tuple[float, Passage, str]] = []
        for passage in passages:
            # Check for direct prompt injection in chunk
            sentences = SENTENCE_SPLIT.split(passage.text)
            for sentence in sentences:
                clean_s = sentence.strip()
                if len(clean_s) < 15:
                    continue
                # If sentence contains direct injection instructions, skip it to prevent payload execution
                if any(
                    sig in scan_injection_signatures(clean_s)
                    for sig in ("ignore_previous", "maintenance_mode", "secret_leak", "remote_exec")
                ):
                    continue
                words = set(WORD_RE.findall(clean_s.lower()))
                overlap = len(words & query_words)
                if overlap > 0:
                    # Weight by rank and overlap
                    score = overlap / (passage.rank + 0.5)
                    candidate_claims.append((score, passage, clean_s))

        # Check if we have sufficient evidence
        if not candidate_claims:
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            return GeneratedAnswer(
                text="Insufficient evidence: the provided regulatory documents do not contain sufficient evidence to answer this question.",
                citations=[],
                citation_spans=[],
                grounded=True,
                abstained=True,
                abstention_reason="Retrieved passages do not contain substantive answers to query terms.",
                model_id=self.model_id,
                latency_ms=elapsed_ms,
            )

        # Sort candidate claims by score descending
        candidate_claims.sort(key=lambda x: x[0], reverse=True)

        # Select top non-redundant claims
        selected: list[tuple[Passage, str]] = []
        seen_texts: set[str] = set()
        for _, passage, sent in candidate_claims:
            norm = sent.lower()
            if norm not in seen_texts:
                seen_texts.add(norm)
                selected.append((passage, sent))
                if len(selected) >= 3:
                    break

        # Assemble answer text and citation spans
        answer_parts: list[str] = []
        cited_chunk_ids: list[str] = []
        spans: list[CitationSpan] = []

        for passage, sent in selected:
            # Form citation tag
            cite_tag = f"[{passage.chunk_id}]"
            answer_parts.append(f"{sent} {cite_tag}")
            if passage.chunk_id not in cited_chunk_ids:
                cited_chunk_ids.append(passage.chunk_id)

            char_start = passage.text.find(sent)
            char_end = char_start + len(sent) if char_start >= 0 else None
            spans.append(
                CitationSpan(
                    chunk_id=passage.chunk_id,
                    source=passage.source,
                    quote=sent,
                    char_start=char_start if char_start >= 0 else None,
                    char_end=char_end,
                )
            )

        full_answer = " ".join(answer_parts)
        elapsed_ms = (time.perf_counter() - start_t) * 1000.0

        return GeneratedAnswer(
            text=full_answer,
            citations=cited_chunk_ids,
            citation_spans=spans,
            grounded=True,
            abstained=False,
            model_id=self.model_id,
            latency_ms=elapsed_ms,
        )


class HostedGenerator:
    """Hosted LLM generator calling external providers (OpenAI or Anthropic)."""

    def __init__(
        self,
        provider: str = "openai",
        model_id: str | None = None,
    ) -> None:
        self.provider = provider
        self.model_id = model_id or (
            "gpt-4o-mini" if provider == "openai" else "claude-3-5-haiku-20241022"
        )

    def generate(
        self,
        query: str,
        passages: list[Passage],
        config: GenerationConfig | None = None,
    ) -> GeneratedAnswer:
        start_t = time.perf_counter()
        cfg = config or GenerationConfig(model_id=self.model_id)
        sys_prompt, user_prompt = build_generation_prompt(query, passages)

        raw_text: str = ""
        finish_reason: str = "stop"

        if self.provider == "openai":
            import openai

            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY environment variable not configured")
            openai_client = openai.OpenAI(api_key=api_key)
            resp = openai_client.chat.completions.create(
                model=self.model_id,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            )
            raw_text = resp.choices[0].message.content or ""
            finish_reason = str(resp.choices[0].finish_reason or "stop")
        elif self.provider == "anthropic":
            import anthropic

            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY environment variable not configured")
            anthropic_client = anthropic.Anthropic(api_key=api_key)
            a_resp = anthropic_client.messages.create(
                model=self.model_id,
                system=sys_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=cfg.max_tokens,
            )
            raw_text = "".join(b.text for b in a_resp.content if hasattr(b, "text"))
            finish_reason = str(a_resp.stop_reason or "stop")
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

        # Extract cited chunk IDs: [uuid]
        cited_ids = re.findall(
            r"\[([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\]",
            raw_text,
        )
        valid_chunk_ids = {p.chunk_id for p in passages}
        filtered_cites = [cid for cid in cited_ids if cid in valid_chunk_ids]

        abstained = "insufficient evidence" in raw_text.lower() or not raw_text.strip()
        elapsed_ms = (time.perf_counter() - start_t) * 1000.0

        return GeneratedAnswer(
            text=raw_text.strip(),
            citations=filtered_cites,
            citation_spans=[],
            grounded=True,
            abstained=abstained,
            model_id=self.model_id,
            finish_reason=finish_reason,
            latency_ms=elapsed_ms,
        )


def get_generator(config: GenerationConfig | None = None) -> BaseGenerator:
    """Return the active generator based on environment and availability."""
    provider = os.environ.get("DOCSCOUT_GENERATOR_PROVIDER", "local").lower()
    if provider in ("openai", "anthropic"):
        model_id = os.environ.get("DOCSCOUT_GENERATOR_MODEL")
        return HostedGenerator(provider=provider, model_id=model_id)
    return DeterministicLocalGenerator()
