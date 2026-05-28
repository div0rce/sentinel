"""``POST /query`` — citation-grounded RAG endpoint."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.db import get_session
from backend.app.embeddings import EmbeddingProvider, get_embedder
from backend.app.llm import LLMClient, get_llm
from backend.app.rag import RagAnswer, answer_query

router = APIRouter(prefix="/query", tags=["query"])


# --- request / response schemas -------------------------------------------------------


class QueryRequest(BaseModel):
    """Body for ``POST /query``."""

    query: str = Field(..., min_length=1, max_length=4000)


class CitationOut(BaseModel):
    """A citation resolved against a retrieved chunk."""

    chunk_id: int
    document_id: int
    score: float
    text: str


class QueryResponse(BaseModel):
    """Result returned to the caller."""

    status: Literal["answered", "refused"]
    answer: str
    citations: list[CitationOut] = Field(default_factory=list)
    reason: str | None = None


# --- dependencies (kept as separate callables so tests can override them) -----------


def _embedder_dependency() -> EmbeddingProvider:
    return get_embedder()


def _llm_dependency() -> LLMClient:
    return get_llm()


# --- handler --------------------------------------------------------------------------


def _to_response(result: RagAnswer) -> QueryResponse:
    return QueryResponse(
        status=result.status,
        answer=result.answer,
        citations=[
            CitationOut(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                score=c.score,
                text=c.text,
            )
            for c in result.citations
        ],
        reason=result.reason,
    )


@router.post("", response_model=QueryResponse)
def post_query(
    body: QueryRequest,
    session: Annotated[Session, Depends(get_session)],
    embedder: Annotated[EmbeddingProvider, Depends(_embedder_dependency)],
    llm: Annotated[LLMClient, Depends(_llm_dependency)],
) -> QueryResponse:
    """Answer ``body.query`` against the indexed corpus, or refuse with a reason."""
    result = answer_query(session, query=body.query, embedder=embedder, llm=llm)
    return _to_response(result)
