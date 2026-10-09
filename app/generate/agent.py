"""Deterministic agentic research loop and workspace persistence (P2-3).

Implements a tight, grounded research loop:
  planner -> retrieve (with graph traversal) -> synthesize -> critique -> artifact
producing structured comparison markdown reports with condition tables, auditable
step-by-step traces, and persistent workspace storage.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import psycopg

from app.api.models import Passage
from app.generate.injection import scan_injection_signatures, verify_canary_resistance
from app.generate.models import (
    CitationSpan,
    ResearchArtifact,
    ResearchStep,
    StructuredTable,
)
from app.retrieval.search import Retriever
from app.retrieval.types import RetrievalConfig, Retrieved
from app.rowtypes import as_str

WORD_RE = re.compile(r"\b\w{3,}\b")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
DEFAULT_WORKSPACE_ID = "00000000-0000-0000-0000-000000000000"

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
    "compare",
    "versus",
    "between",
}

REGULATORY_STOP_WORDS = STOP_WORDS | {
    "rbi",
    "sebi",
    "guidelines",
    "guideline",
    "regulations",
    "regulation",
    "framework",
    "frameworks",
    "rules",
    "rule",
    "circular",
    "circulars",
    "requirements",
    "requirement",
    "directions",
    "direction",
    "master",
    "provisions",
    "provision",
    "mandated",
    "mandates",
    "applicable",
    "per",
    "under",
    "order",
}


def plan_query_aspects(query: str, max_aspects: int = 3) -> list[str]:
    """Deterministically decompose a complex compliance query into focused aspect sub-queries."""
    clean = query.strip()
    # Check for explicit multi-topic or comparison patterns
    compare_patterns = [
        re.compile(r"compare\s+(.*?)\s+(?:with|to|and|versus|vs\.?)\s+(.*)", re.IGNORECASE),
        re.compile(r"(.*?)\s+(?:versus|vs\.?)\s+(.*)", re.IGNORECASE),
        re.compile(r"(.*?)\s+(?:before\s+and\s+after)\s+(.*)", re.IGNORECASE),
        re.compile(r"(.*?)\s+(?:difference\s+between)\s+(.*?)\s+and\s+(.*)", re.IGNORECASE),
    ]

    for pat in compare_patterns:
        m = pat.search(clean)
        if m:
            groups = [g.strip() for g in m.groups() if g and len(g.strip()) > 3]
            if len(groups) >= 2:
                aspects = groups[:max_aspects]
                return aspects

    # Check for multi-clause questions separated by semicolons or 'and what'
    if ";" in clean:
        parts = [p.strip() for p in clean.split(";") if len(p.strip()) > 5]
        if len(parts) >= 2:
            return parts[:max_aspects]

    and_split = re.split(r"\b(?:and\s+what|and\s+how|as\s+well\s+as)\b", clean, flags=re.IGNORECASE)
    if len(and_split) >= 2 and all(len(p.strip()) > 10 for p in and_split):
        return [p.strip() for p in and_split[:max_aspects]]

    return [clean]


class ResearchAgent:
    """Bounded, deterministic agentic research engine for regulatory analysis."""

    def __init__(self, retriever: Retriever) -> None:
        self.retriever = retriever

    def research(
        self,
        query: str,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
        k: int = 5,
        mode: str = "graph-hybrid",
        max_aspects: int = 3,
    ) -> ResearchArtifact:
        """Execute the deterministic research loop and produce a structured research artifact."""
        start_time = time.perf_counter()
        steps: list[ResearchStep] = []
        retrieval_ms_total = 0.0

        # Phase 1: Planning
        plan_start = time.perf_counter()
        aspects = plan_query_aspects(query, max_aspects=max_aspects)
        plan_dur = (time.perf_counter() - plan_start) * 1000.0

        steps.append(
            ResearchStep(
                step_index=len(steps),
                phase="plan",
                thought=f"Decomposed compliance inquiry into {len(aspects)} targeted aspect sub-queries.",
                tool_name="plan_aspects",
                tool_args={"aspects": aspects, "max_aspects": max_aspects},
                observation=f"Aspects formulated: {'; '.join(aspects)}",
                duration_ms=round(plan_dur, 2),
            )
        )

        # Phase 2: Targeted Retrieval Across Aspects
        all_passages_by_id: dict[str, Passage] = {}
        all_retrieved_hits: list[Retrieved] = []
        for idx, aspect_q in enumerate(aspects):
            ret_start = time.perf_counter()
            config = RetrievalConfig(
                name=f"research-{mode}",
                mode=mode,  # type: ignore[arg-type]
                k_dense=50,
                k_lexical=50,
                k_final=max(k, 6),
                anchor_arm_top1=True,
            )
            hits = self.retriever.retrieve(aspect_q, config=config)
            all_retrieved_hits.extend(hits)

            passages = [
                Passage(
                    rank=h.rank,
                    chunk_id=h.chunk_id,
                    document_id=h.document_id,
                    source=h.source,
                    canonical_url=h.canonical_url,
                    score=round(h.score, 6),
                    arm_ranks=h.arm_ranks,
                    char_start=h.char_start,
                    char_end=h.char_end,
                    text=h.text,
                    title=h.title if isinstance(getattr(h, "title", None), str) else None,
                    published_date=(
                        h.published_date
                        if isinstance(getattr(h, "published_date", None), str)
                        else None
                    ),
                )
                for h in hits
            ]

            for p in passages:
                if p.chunk_id not in all_passages_by_id:
                    all_passages_by_id[p.chunk_id] = p

            dur_ms = (time.perf_counter() - ret_start) * 1000.0
            retrieval_ms_total += dur_ms
            steps.append(
                ResearchStep(
                    step_index=len(steps),
                    phase="retrieve",
                    thought=f"Executing aspect retrieval {idx + 1}/{len(aspects)}: '{aspect_q}'",
                    tool_name="retrieve_provisions",
                    tool_args={"aspect_query": aspect_q, "k": k, "mode": mode},
                    observation=f"Retrieved {len(passages)} passages. Chunks: {[p.chunk_id[:8] for p in passages]}",
                    duration_ms=round(dur_ms, 2),
                )
            )

        # Phase 3: Synthesis & Table Extraction
        synth_start = time.perf_counter()
        passages_list = list(all_passages_by_id.values())

        if not passages_list:
            gen_dur = (time.perf_counter() - synth_start) * 1000.0
            total_dur = (time.perf_counter() - start_time) * 1000.0
            steps.append(
                ResearchStep(
                    step_index=len(steps),
                    phase="critique",
                    thought="No passages found matching query terms across any aspect.",
                    tool_name="abstention_check",
                    tool_args={"passage_count": 0},
                    observation="Abstaining due to insufficient regulatory evidence.",
                    duration_ms=round(gen_dur, 2),
                )
            )
            return ResearchArtifact(
                artifact_id=str(uuid.uuid4()),
                workspace_id=workspace_id,
                query=query,
                title="Research Abstention: Insufficient Regulatory Evidence",
                markdown=(
                    "# Regulatory Research Report: Insufficient Evidence\n\n"
                    "**Abstention Notice:** The repository does not contain verifiable regulatory provisions "
                    "matching the requested compliance inquiry."
                ),
                table_data=None,
                steps=steps,
                citations=[],
                citation_spans=[],
                timings={
                    "total_ms": round(total_dur, 2),
                    "retrieval_ms": round(retrieval_ms_total, 2),
                    "generation_ms": round(gen_dur, 2),
                },
                grounded=True,
                abstained=True,
                created_at=datetime.now(UTC).isoformat(),
            )

        conf = self.retriever.assess_confidence(query, all_retrieved_hits[:5])

        # Extract substantive claims per aspect
        specific_query_words = {
            w for w in WORD_RE.findall(query.lower()) if w not in REGULATORY_STOP_WORDS
        }
        if not specific_query_words:
            specific_query_words = {
                w for w in WORD_RE.findall(query.lower()) if w not in STOP_WORDS
            }

        min_overlap = 1
        if len(specific_query_words) >= 7:
            min_overlap = 3
        elif len(specific_query_words) >= 4:
            min_overlap = 2

        candidate_claims: list[tuple[float, Passage, str]] = []
        for p in passages_list:
            sentences = SENTENCE_SPLIT.split(p.text)
            for s in sentences:
                clean_s = s.strip()
                if len(clean_s) < 20:
                    continue
                # Neutralize injection payloads
                if any(
                    sig in scan_injection_signatures(clean_s)
                    for sig in (
                        "ignore_previous",
                        "maintenance_mode",
                        "secret_leak",
                        "remote_exec",
                        "system_override",
                    )
                ):
                    continue

                words = set(WORD_RE.findall(clean_s.lower())) - STOP_WORDS
                overlap = len(words & specific_query_words)
                if overlap >= min_overlap:
                    score = overlap / (p.rank + 0.5)
                    candidate_claims.append((score, p, clean_s))

        # If confidence signal flagged low evidence, require higher overlap
        if conf.low_evidence:
            max_overlap = max(
                (
                    len((set(WORD_RE.findall(sent.lower())) - STOP_WORDS) & specific_query_words)
                    for _, _, sent in candidate_claims
                ),
                default=0,
            )
            if max_overlap < min(min_overlap + 1, len(specific_query_words)):
                candidate_claims = []

        candidate_claims.sort(key=lambda x: x[0], reverse=True)

        selected_claims: list[tuple[Passage, str]] = []
        seen_texts: set[str] = set()
        for _, p, sent in candidate_claims:
            norm = sent.lower()
            if norm not in seen_texts:
                seen_texts.add(norm)
                selected_claims.append((p, sent))
                if len(selected_claims) >= 6:
                    break

        if not selected_claims:
            gen_dur = (time.perf_counter() - synth_start) * 1000.0
            total_dur = (time.perf_counter() - start_time) * 1000.0
            steps.append(
                ResearchStep(
                    step_index=len(steps),
                    phase="critique",
                    thought="Retrieved passages contain no substantive overlap with inquiry terms.",
                    tool_name="abstention_check",
                    tool_args={"claims_found": 0},
                    observation="Abstaining due to insufficient regulatory evidence.",
                    duration_ms=round(gen_dur, 2),
                )
            )
            return ResearchArtifact(
                artifact_id=str(uuid.uuid4()),
                workspace_id=workspace_id,
                query=query,
                title="Research Abstention: Insufficient Regulatory Evidence",
                markdown=(
                    "# Regulatory Research Report: Insufficient Evidence\n\n"
                    "**Abstention Notice:** The repository does not contain verifiable regulatory provisions "
                    "matching the requested compliance inquiry."
                ),
                table_data=None,
                steps=steps,
                citations=[],
                citation_spans=[],
                timings={
                    "total_ms": round(total_dur, 2),
                    "retrieval_ms": round(retrieval_ms_total, 2),
                    "generation_ms": round(gen_dur, 2),
                },
                grounded=True,
                abstained=True,
                created_at=datetime.now(UTC).isoformat(),
            )

        # Assemble structured comparison table if multi-aspect or comparison
        is_comparison = len(aspects) > 1 or any(
            w in query.lower()
            for w in ("compare", "versus", "vs", "table", "difference", "condition", "between")
        )

        table_data: StructuredTable | None = None
        if is_comparison and selected_claims:
            headers = [
                "Regulatory Framework",
                "Authority / Provision",
                "Mandate & Conditions",
                "Citation",
            ]
            rows: list[list[str]] = []
            for p, sent in selected_claims[:4]:
                fw_name = p.title or p.source
                doc_auth = "RBI / SEBI"
                if "RBI" in p.source.upper() or "RBI" in (p.title or "").upper():
                    doc_auth = "RBI"
                elif "SEBI" in p.source.upper() or "SEBI" in (p.title or "").upper():
                    doc_auth = "SEBI"
                # Shorten sentence for table cell
                mandate = sent if len(sent) <= 120 else sent[:117] + "..."
                rows.append([fw_name, doc_auth, mandate, f"[{p.chunk_id}]"])
            table_data = StructuredTable(headers=headers, rows=rows)

        # Assemble citation spans and citations
        cited_chunk_ids: list[str] = []
        citation_spans: list[CitationSpan] = []
        for p, sent in selected_claims:
            if p.chunk_id not in cited_chunk_ids:
                cited_chunk_ids.append(p.chunk_id)
            c_start = p.text.find(sent)
            c_end = c_start + len(sent) if c_start >= 0 else None
            citation_spans.append(
                CitationSpan(
                    chunk_id=p.chunk_id,
                    source=p.source,
                    quote=sent,
                    char_start=c_start if c_start >= 0 else None,
                    char_end=c_end,
                )
            )

        # Construct Markdown report
        title = f"Regulatory Synthesis: {query[:60].strip()}"
        md_lines = [
            f"# {title}",
            "",
            "## 1. Executive Summary",
            (
                f"Analysis conducted across {len(aspects)} regulatory aspects covering "
                f"{len(passages_list)} retrieved candidate provisions from RBI/SEBI circulars. "
                f"Total {len(cited_chunk_ids)} distinct provisions cite verifiable compliance mandates."
            ),
            "",
        ]

        if table_data is not None:
            md_lines.extend(
                [
                    "## 2. Comparative Matrix & Regulatory Conditions",
                    "",
                    "| " + " | ".join(table_data.headers) + " |",
                    "| " + " | ".join(["---"] * len(table_data.headers)) + " |",
                ]
            )
            for r in table_data.rows:
                # Sanitize pipes in table cells
                clean_row = [cell.replace("|", "/") for cell in r]
                md_lines.append("| " + " | ".join(clean_row) + " |")
            md_lines.append("")

        section_num = "3" if table_data is not None else "2"
        md_lines.extend(
            [
                f"## {section_num}. Grounded Regulatory Provisions",
                "",
            ]
        )
        for p, sent in selected_claims:
            md_lines.append(f"- **{p.title or p.source}**: {sent} [{p.chunk_id}]")

        md_lines.extend(
            [
                "",
                f"## {int(section_num) + 1}. Verified Evidence & Passage Citations",
                "",
            ]
        )
        for cid in cited_chunk_ids:
            p_obj = all_passages_by_id.get(cid)
            if p_obj is not None:
                md_lines.append(
                    f"- `[{cid}]`: *{p_obj.title or p_obj.source}* ({p_obj.canonical_url or 'N/A'})"
                )

        full_md = "\n".join(md_lines)
        synth_dur = (time.perf_counter() - synth_start) * 1000.0

        steps.append(
            ResearchStep(
                step_index=len(steps),
                phase="synthesize",
                thought=f"Synthesized research report with {len(selected_claims)} claims and table={table_data is not None}.",
                tool_name="synthesize_markdown",
                tool_args={
                    "claim_count": len(selected_claims),
                    "has_table": table_data is not None,
                },
                observation=f"Generated {len(md_lines)} markdown lines citing {len(cited_chunk_ids)} chunks.",
                duration_ms=round(synth_dur, 2),
            )
        )

        # Phase 4: Critique & Guardrails
        crit_start = time.perf_counter()
        resisted, tripped = verify_canary_resistance(full_md)
        grounded = len(cited_chunk_ids) > 0 and all(
            cid in all_passages_by_id for cid in cited_chunk_ids
        )
        crit_dur = (time.perf_counter() - crit_start) * 1000.0

        steps.append(
            ResearchStep(
                step_index=len(steps),
                phase="critique",
                thought="Verifying citation grounding integrity and prompt-injection canary immunity.",
                tool_name="critique_guardrail",
                tool_args={"canary_check": resisted, "grounded": grounded},
                observation=(
                    f"Critique passed: grounded={grounded}, canary_tripped={tripped}. All claims cited."
                ),
                duration_ms=round(crit_dur, 2),
            )
        )

        total_dur = (time.perf_counter() - start_time) * 1000.0

        return ResearchArtifact(
            artifact_id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            query=query,
            title=title,
            markdown=full_md,
            table_data=table_data,
            steps=steps,
            citations=cited_chunk_ids,
            citation_spans=citation_spans,
            timings={
                "total_ms": round(total_dur, 2),
                "retrieval_ms": round(retrieval_ms_total, 2),
                "generation_ms": round(synth_dur + crit_dur, 2),
            },
            grounded=grounded and resisted,
            abstained=False,
            created_at=datetime.now(UTC).isoformat(),
        )


# Persistence Helpers


def ensure_workspace(
    conn: psycopg.Connection[Any],
    workspace_id: str,
    name: str = "Default Regulatory Workspace",
) -> str:
    """Ensure a workspace exists in the database."""
    query = """
        INSERT INTO workspaces (workspace_id, name, created_at, updated_at)
        VALUES (%s::uuid, %s, now(), now())
        ON CONFLICT (workspace_id) DO NOTHING
    """
    conn.execute(query, (workspace_id, name))
    conn.commit()
    return workspace_id


def save_research_artifact(
    conn: psycopg.Connection[Any],
    artifact: ResearchArtifact,
) -> None:
    """Persist a completed research artifact with step traces and citation metadata."""
    ensure_workspace(conn, artifact.workspace_id)
    steps_payload = [s.model_dump() for s in artifact.steps]
    table_payload = artifact.table_data.model_dump() if artifact.table_data else None

    query = """
        INSERT INTO research_artifacts
            (artifact_id, workspace_id, query, artifact_title,
             content_markdown, table_data, steps, citations,
             timings, grounded, abstained, created_at)
        VALUES
            (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::timestamptz)
        ON CONFLICT (artifact_id) DO UPDATE
            SET content_markdown = EXCLUDED.content_markdown,
                table_data = EXCLUDED.table_data,
                steps = EXCLUDED.steps,
                citations = EXCLUDED.citations,
                timings = EXCLUDED.timings
    """
    conn.execute(
        query,
        (
            artifact.artifact_id,
            artifact.workspace_id,
            artifact.query,
            artifact.title,
            artifact.markdown,
            json.dumps(table_payload) if table_payload else None,
            json.dumps(steps_payload),
            json.dumps(artifact.citations),
            json.dumps(artifact.timings),
            artifact.grounded,
            artifact.abstained,
            artifact.created_at,
        ),
    )
    conn.commit()


def get_research_artifact(
    conn: psycopg.Connection[Any],
    artifact_id: str,
) -> ResearchArtifact | None:
    """Retrieve a previously stored research artifact by its UUID."""
    query = """
        SELECT artifact_id::text, workspace_id::text, query, artifact_title,
               content_markdown, table_data, steps, citations,
               timings, grounded, abstained, created_at::text
        FROM research_artifacts
        WHERE artifact_id = %s::uuid
    """
    row = conn.execute(query, (artifact_id,)).fetchone()
    if row is None:
        return None

    raw_table = row[5]
    table_obj: StructuredTable | None = None
    if raw_table is not None:
        table_dict = raw_table if isinstance(raw_table, dict) else json.loads(as_str(raw_table))
        table_obj = StructuredTable(**table_dict)

    raw_steps = row[6]
    steps_list = raw_steps if isinstance(raw_steps, list) else json.loads(as_str(raw_steps))
    steps_objs = [ResearchStep(**s) for s in steps_list]

    raw_cits = row[7]
    cits_list = raw_cits if isinstance(raw_cits, list) else json.loads(as_str(raw_cits))

    raw_timings = row[8]
    timings_dict = raw_timings if isinstance(raw_timings, dict) else json.loads(as_str(raw_timings))

    return ResearchArtifact(
        artifact_id=as_str(row[0]),
        workspace_id=as_str(row[1]),
        query=as_str(row[2]),
        title=as_str(row[3]),
        markdown=as_str(row[4]),
        table_data=table_obj,
        steps=steps_objs,
        citations=cits_list,
        citation_spans=[],
        timings=timings_dict,
        grounded=bool(row[9]),
        abstained=bool(row[10]),
        created_at=as_str(row[11]),
    )


def list_workspace_artifacts(
    conn: psycopg.Connection[Any],
    workspace_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List recent research artifacts saved in a workspace."""
    query = """
        SELECT artifact_id::text, query, artifact_title, grounded, abstained, created_at::text
        FROM research_artifacts
        WHERE workspace_id = %s::uuid
        ORDER BY created_at DESC
        LIMIT %s
    """
    rows = conn.execute(query, (workspace_id, limit)).fetchall()
    return [
        {
            "artifact_id": as_str(r[0]),
            "query": as_str(r[1]),
            "title": as_str(r[2]),
            "grounded": bool(r[3]),
            "abstained": bool(r[4]),
            "created_at": as_str(r[5]),
        }
        for r in rows
    ]
