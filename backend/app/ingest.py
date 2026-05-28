"""Idempotent document ingestion pipeline.

The pipeline is keyed by a SHA-256 hash of the document's canonical content. Re-ingesting
the same content is a no-op:

1. Compute ``hash = sha256(canonical_text)``.
2. If a :class:`Document` already exists with that hash → return ``status="skipped"``.
3. Otherwise insert the document, chunk the text, embed each chunk, and bulk-insert
   the chunks. Returns ``status="ingested"``.

All in a single SQLAlchemy session that the caller owns; the CLI commits after every
file so a partial failure mid-corpus does not lose completed documents.

The CLI walks a directory, ingests every file matching the supported suffixes (``.txt``
and ``.md`` for now), and prints a per-file summary plus a totals line. Wired up by
``make seed`` for the synthetic corpus.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy.orm import Session

from backend.app.chunking import chunk_text
from backend.app.config import Settings, get_settings
from backend.app.db import get_session_factory
from backend.app.embeddings import EmbeddingProvider, get_embedder
from backend.app.repositories import chunks as chunks_repo
from backend.app.repositories import documents as documents_repo

SUPPORTED_SUFFIXES: frozenset[str] = frozenset({".txt", ".md"})

IngestStatus = Literal["ingested", "skipped"]


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Summary of a single document's ingestion outcome."""

    document_id: int
    hash: str
    source: str
    status: IngestStatus
    chunk_count: int


def canonical_hash(text: str) -> str:
    """Return the SHA-256 hex digest of the canonical UTF-8 form of ``text``.

    Idempotency is content-keyed: an identical text body always hashes to the same
    digest regardless of filename, mtime, or path. We do *not* normalize whitespace
    here — two documents that differ by a single space are different documents.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ingest_document(
    session: Session,
    *,
    text: str,
    source: str,
    title: str | None = None,
    mime_type: str | None = None,
    embedder: EmbeddingProvider,
    settings: Settings | None = None,
) -> IngestResult:
    """Ingest a single document. Idempotent on the SHA-256 of ``text``."""
    settings = settings or get_settings()

    content_hash = canonical_hash(text)
    existing = documents_repo.get_by_hash(session, content_hash)
    if existing is not None:
        return IngestResult(
            document_id=existing.id,
            hash=content_hash,
            source=source,
            status="skipped",
            chunk_count=0,
        )

    document = documents_repo.create(
        session,
        hash=content_hash,
        source=source,
        title=title,
        mime_type=mime_type,
    )

    chunks = chunk_text(
        text,
        chunk_size_tokens=settings.chunk_size_tokens,
        chunk_overlap_tokens=settings.chunk_overlap_tokens,
    )
    chunk_count = 0
    if chunks:
        embeddings = embedder.embed([c.text for c in chunks])
        chunks_repo.bulk_insert(
            session,
            document_id=document.id,
            chunks=[
                {
                    "ord": c.ord,
                    "text": c.text,
                    "token_count": c.token_count,
                    "embedding": embeddings[i],
                }
                for i, c in enumerate(chunks)
            ],
        )
        chunk_count = len(chunks)

    return IngestResult(
        document_id=document.id,
        hash=content_hash,
        source=source,
        status="ingested",
        chunk_count=chunk_count,
    )


def _iter_corpus_files(root: Path) -> Iterable[Path]:
    """Yield supported files under ``root`` in deterministic (sorted) order."""
    if root.is_file():
        if root.suffix.lower() in SUPPORTED_SUFFIXES:
            yield root
        return
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            yield path


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def ingest_path(
    path: Path,
    *,
    embedder: EmbeddingProvider,
    settings: Settings | None = None,
) -> list[IngestResult]:
    """Ingest every supported file under ``path``. Commits after each file."""
    settings = settings or get_settings()
    factory = get_session_factory()
    results: list[IngestResult] = []
    for file_path in _iter_corpus_files(path):
        text = _read_text(file_path)
        with factory() as session:
            result = ingest_document(
                session,
                text=text,
                source=str(file_path.resolve()),
                title=file_path.stem,
                mime_type="text/markdown" if file_path.suffix.lower() == ".md" else "text/plain",
                embedder=embedder,
                settings=settings,
            )
            session.commit()
        results.append(result)
    return results


# --- CLI -----------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.app.ingest",
        description="Ingest a directory of synthetic documents into Sentinel.",
    )
    parser.add_argument(
        "--path",
        type=Path,
        required=True,
        help="File or directory of supported text documents (.txt, .md).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.path.exists():
        print(f"error: path does not exist: {args.path}", file=sys.stderr)
        return 2

    settings = get_settings()
    embedder = get_embedder(settings)
    print(f"ingest: provider={settings.embeddings_provider} dim={embedder.dim} path={args.path}")

    results = ingest_path(args.path, embedder=embedder, settings=settings)

    ingested = sum(1 for r in results if r.status == "ingested")
    skipped = sum(1 for r in results if r.status == "skipped")
    total_chunks = sum(r.chunk_count for r in results)
    for r in results:
        flag = "+" if r.status == "ingested" else "="
        print(f"  {flag} {r.source} (doc#{r.document_id}, chunks={r.chunk_count})")
    print(
        f"ingest: done. files={len(results)} ingested={ingested} skipped={skipped} "
        f"chunks_added={total_chunks}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
