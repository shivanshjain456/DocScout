"""Conversational Multi-Turn Chat API with Coreference Resolution (FEAT-017).

Provides the `/v1/chat` endpoint and an in-memory thread-safe LRU session store
for conversational follow-up questions over Indian banking and securities regulations.
"""

from __future__ import annotations

from collections import OrderedDict
from threading import Lock
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from app.api.models import Confidence, Passage
from app.api.security import require_api_key
from app.retrieval import RetrievalConfig, Retriever
from app.retrieval.coreference import (
    CIRCULAR_ID_REGEX,
    ChatMessage,
    CoreferenceResolution,
    get_default_coreference_resolver,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/v1/chat", tags=["chat"])


class ChatRequest(BaseModel):
    """Payload for multi-turn conversational chat query."""

    message: str = Field(min_length=1, max_length=512)
    history: list[ChatMessage] = Field(default_factory=list, max_length=10)
    session_id: str | None = Field(default=None, max_length=128)
    auto_resolve_coreference: bool = True
    k: int = Field(default=5, ge=1, le=50)
    mode: Literal["hybrid", "dense", "bm25"] = "hybrid"


class ChatResponse(BaseModel):
    """Response containing rewritten query, coreference resolution, and retrieved evidence."""

    message: str
    rewritten_query: str
    resolution: CoreferenceResolution
    passages: list[Passage] = Field(default_factory=list)
    confidence: Confidence | None = None
    session_id: str | None = None
    turns_in_session: int = 0


class SessionStore:
    """Thread-safe in-memory LRU session store with strict memory bounding."""

    def __init__(self, max_sessions: int = 1000, max_turns: int = 5) -> None:
        self._max_sessions = max_sessions
        self._max_turns = max_turns
        self._sessions: OrderedDict[str, list[ChatMessage]] = OrderedDict()
        self._lock = Lock()

    def get_history(self, session_id: str) -> list[ChatMessage]:
        with self._lock:
            if session_id in self._sessions:
                self._sessions.move_to_end(session_id)
                return list(self._sessions[session_id])
            return []

    def add_turn(self, session_id: str, message: ChatMessage) -> None:
        with self._lock:
            if session_id in self._sessions:
                turns = self._sessions[session_id]
                turns.append(message)
                if len(turns) > self._max_turns:
                    del turns[: len(turns) - self._max_turns]
                self._sessions.move_to_end(session_id)
            else:
                if len(self._sessions) >= self._max_sessions:
                    self._sessions.popitem(last=False)
                self._sessions[session_id] = [message]

    def clear_session(self, session_id: str) -> bool:
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False

    def session_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def estimate_session_bytes(self, session_id: str) -> int:
        """Estimate memory size in bytes for a session to verify <= 10 KB budget."""
        with self._lock:
            turns = self._sessions.get(session_id, [])
            return sum(
                len(t.content.encode("utf-8"))
                + sum(len(c.encode("utf-8")) for c in t.circular_ids)
                + sum(len(e.encode("utf-8")) for e in t.entities)
                + 256  # object header overhead
                for t in turns
            )


_DEFAULT_SESSION_STORE = SessionStore()


def get_default_session_store() -> SessionStore:
    return _DEFAULT_SESSION_STORE


@router.post(
    "",
    response_model=ChatResponse,
    responses={
        401: {"description": "missing or invalid API key"},
        422: {"description": "invalid request"},
    },
)
def chat_turn(
    payload: ChatRequest,
    request: Request,
    fingerprint: str = Depends(require_api_key),
) -> ChatResponse:
    """Submit a conversational query, resolve coreferences, and retrieve grounded evidence."""
    store = get_default_session_store()
    resolver = get_default_coreference_resolver()

    # Determine history: explicit payload history takes precedence over session store
    if payload.history:
        active_history = payload.history
    elif payload.session_id:
        active_history = store.get_history(payload.session_id)
    else:
        active_history = []

    # Resolve coreference
    if payload.auto_resolve_coreference:
        resolution = resolver.resolve(payload.message, active_history)
    else:
        resolution = CoreferenceResolution(rewritten_query=payload.message)

    query_to_search = resolution.rewritten_query or payload.message
    logger.info(
        "chat.query",
        original_message=payload.message,
        rewritten_query=query_to_search,
        was_rewritten=resolution.was_rewritten,
        session_id=payload.session_id,
        history_turns=len(active_history),
    )

    passages: list[Passage] = []
    confidence: Confidence | None = None

    # Retrieve if app state has pool and embedder
    state = getattr(request.app, "state", None)
    pool = getattr(state, "pool", None) if state else None
    embedder = getattr(state, "embedder", None) if state else None
    bm25 = getattr(state, "bm25", None) if state else None

    if pool is not None and embedder is not None and bm25 is not None:
        try:
            with pool.connection() as conn:
                retriever = Retriever(conn, embedder=embedder, bm25=bm25)
                retrieval_config = RetrievalConfig(
                    name=f"chat-{payload.mode}",
                    mode=payload.mode,
                    k_final=payload.k,
                )
                hits = retriever.retrieve(query_to_search, retrieval_config)
                assessed = retriever.assess_confidence(query_to_search, hits)

                passages = [
                    Passage(
                        rank=hit.rank,
                        chunk_id=hit.chunk_id,
                        document_id=hit.document_id,
                        source=hit.source,
                        canonical_url=hit.canonical_url,
                        score=round(hit.score, 6),
                        arm_ranks=hit.arm_ranks,
                        char_start=hit.char_start,
                        char_end=hit.char_end,
                        text=hit.text,
                        title=hit.title if isinstance(getattr(hit, "title", None), str) else None,
                        published_date=(
                            hit.published_date
                            if isinstance(getattr(hit, "published_date", None), str)
                            else None
                        ),
                        matching_relationships=hit.matching_relationships,
                        centrality_boost=round(hit.centrality_boost, 6),
                        presentation_rank=hit.presentation_rank,
                    )
                    for hit in hits
                ]
                confidence = Confidence(**assessed.as_dict())  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            logger.warning("chat.retrieval_failed", error=str(exc))

    # Update session store if session_id provided
    turns_in_session = 0
    if payload.session_id:
        # Extract circular IDs from message & passages for downstream context
        extracted_cids = list(resolution.referenced_circular_ids)
        for p in passages:
            for match in CIRCULAR_ID_REGEX.finditer(p.text):
                cid = match.group(0).strip()
                if cid and cid not in extracted_cids:
                    extracted_cids.append(cid)

        user_turn = ChatMessage(
            role="user",
            content=payload.message,
            circular_ids=resolution.referenced_circular_ids,
            entities=resolution.resolved_entities,
        )
        store.add_turn(payload.session_id, user_turn)

        if passages:
            assistant_content = f"Found {len(passages)} passages on {query_to_search}."
            assistant_turn = ChatMessage(
                role="assistant",
                content=assistant_content,
                circular_ids=extracted_cids[:3],
                entities=resolution.resolved_entities,
            )
            store.add_turn(payload.session_id, assistant_turn)

        turns_in_session = len(store.get_history(payload.session_id))

    return ChatResponse(
        message=payload.message,
        rewritten_query=query_to_search,
        resolution=resolution,
        passages=passages,
        confidence=confidence,
        session_id=payload.session_id,
        turns_in_session=turns_in_session,
    )


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_200_OK,
    responses={401: {"description": "missing or invalid API key"}},
)
def clear_session(
    session_id: str,
    fingerprint: str = Depends(require_api_key),
) -> dict[str, object]:
    """Wipe session history on session termination to enforce data isolation."""
    store = get_default_session_store()
    cleared = store.clear_session(session_id)
    logger.info("chat.session_cleared", session_id=session_id, cleared=cleared)
    return {"cleared": cleared, "session_id": session_id}
