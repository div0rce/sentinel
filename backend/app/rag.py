"""Citation-grounded RAG: retrieve → prompt → answer-or-refuse.

The :func:`answer_query` orchestrator returns a :class:`RagAnswer` whose ``status``
is either ``"answered"`` (with at least one valid in-corpus citation) or
``"refused"`` (with a ``reason``). This is the M3 implementation of the
**citation-or-refuse** guardrail: an answer that cannot point to retrieved corpus
content is not returned to the caller.

Refusal triggers:

* ``no_support`` — top retrieval score is below
  :attr:`backend.app.config.Settings.retrieval_min_score`.
* ``uncited`` — the LLM produced text but did not include any ``[chunk:N]`` citation
  whose ``N`` matches a retrieved chunk id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.orm import Session

from backend.app.config import Settings, get_settings
from backend.app.embeddings import EmbeddingProvider
from backend.app.llm import LLMClient
from backend.app.retrieval import ChunkScore, cosine_top_k

# Inline citation marker that the LLM is instructed to use. Using a token unlikely to
# appear in source text keeps parsing robust without sophisticated NLP.
CITATION_PATTERN = re.compile(r"\[chunk:(\d+)\]")

REFUSAL_TEXT = "I cannot answer based on the provided context."


SYSTEM_PROMPT = (
    "You are an assistant that answers questions strictly from a provided "
    "internal corpus.\n"
    "RULES:\n"
    "1. Use ONLY the supplied context. Do not rely on outside knowledge.\n"
    "2. For every factual claim, append an inline citation in the form [chunk:N], "
    "where N is the integer id of the supporting chunk listed in the context.\n"
    "3. If the context is insufficient or does not contain the answer, reply with "
    f"exactly this sentence and nothing else: {REFUSAL_TEXT}\n"
    "4. Do not fabricate chunk ids."
)


RagStatus = Literal["answered", "refused"]


@dataclass(frozen=True, slots=True)
class Citation:
    """A citation parsed out of the LLM's answer and resolved against retrieved chunks."""

    chunk_id: int
    document_id: int
    score: float
    text: str


@dataclass(frozen=True, slots=True)
class RagAnswer:
    """Result of :func:`answer_query`. ``citations`` is empty when ``status='refused'``."""

    status: RagStatus
    answer: str
    citations: list[Citation] = field(default_factory=list)
    reason: str | None = None
    retrieved: list[ChunkScore] = field(default_factory=list)


def _build_user_prompt(question: str, hits: list[ChunkScore]) -> str:
    parts: list[str] = ["Context:"]
    for hit in hits:
        parts.append(f"[chunk:{hit.chunk.id}] {hit.chunk.text}")
    parts.append("")
    parts.append(f"Question: {question}")
    return "\n".join(parts)


def _parse_citations(text: str, retrieved: list[ChunkScore]) -> list[Citation]:
    by_id: dict[int, ChunkScore] = {hit.chunk.id: hit for hit in retrieved}
    seen: set[int] = set()
    citations: list[Citation] = []
    for match in CITATION_PATTERN.finditer(text):
        cid = int(match.group(1))
        if cid in seen:
            continue
        hit = by_id.get(cid)
        if hit is None:
            # The model cited a chunk we did not supply. Drop it; the caller's
            # uncited-answer check below will refuse if no valid citations remain.
            continue
        seen.add(cid)
        citations.append(
            Citation(
                chunk_id=cid,
                document_id=hit.chunk.document_id,
                score=hit.score,
                text=hit.chunk.text,
            )
        )
    return citations


def answer_query(
    session: Session,
    *,
    query: str,
    embedder: EmbeddingProvider,
    llm: LLMClient,
    settings: Settings | None = None,
) -> RagAnswer:
    """Answer ``query`` against the corpus, or refuse if no support is found."""
    settings = settings or get_settings()
    if not query.strip():
        return RagAnswer(status="refused", answer=REFUSAL_TEXT, reason="empty_query")

    [query_vec] = embedder.embed([query])

    hits = cosine_top_k(session, query_vec=query_vec, k=settings.retrieval_top_k)
    if not hits:
        return RagAnswer(
            status="refused",
            answer=REFUSAL_TEXT,
            reason="no_support",
            retrieved=hits,
        )

    top_score = max(hit.score for hit in hits)
    if top_score < settings.retrieval_min_score:
        return RagAnswer(
            status="refused",
            answer=REFUSAL_TEXT,
            reason="no_support",
            retrieved=hits,
        )

    user_prompt = _build_user_prompt(query, hits)
    response = llm.complete(
        system=SYSTEM_PROMPT,
        user=user_prompt,
        max_tokens=settings.llm_max_tokens,
        temperature=settings.llm_temperature,
    )
    citations = _parse_citations(response.text, hits)
    if not citations:
        return RagAnswer(
            status="refused",
            answer=REFUSAL_TEXT,
            reason="uncited",
            retrieved=hits,
        )

    return RagAnswer(
        status="answered",
        answer=response.text,
        citations=citations,
        retrieved=hits,
    )
