"""Token-based sliding-window text chunker.

We tokenize with ``tiktoken``'s ``cl100k_base`` encoding — the same one OpenAI's
``text-embedding-3-*`` models use — so chunk boundaries align with what the embedder
will see. Chunks overlap by a configurable number of tokens to preserve cross-boundary
context for retrieval.

The chunker is intentionally pure: ``chunk_text(text, ...)`` is a deterministic
function of ``text`` and the configuration, with no I/O, no random state, and no
hidden globals beyond the cached encoder. Determinism is exercised in tests.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache

import tiktoken

# cl100k_base is the encoder used by text-embedding-3-* and gpt-4*. We pin it
# explicitly so the chunker's behaviour is provider-agnostic and stable.
ENCODING_NAME = "cl100k_base"


@dataclass(frozen=True, slots=True)
class ChunkOut:
    """A single chunk produced by :func:`chunk_text`."""

    ord: int
    text: str
    token_count: int


@lru_cache(maxsize=1)
def _encoder() -> tiktoken.Encoding:
    return tiktoken.get_encoding(ENCODING_NAME)


def chunk_text(
    text: str,
    *,
    chunk_size_tokens: int,
    chunk_overlap_tokens: int,
) -> list[ChunkOut]:
    """Split ``text`` into overlapping token-windowed chunks.

    Returns chunks numbered from 0 in document order; each chunk's text is the
    original source span covered by the token window. Returns an empty list for
    empty input.
    """
    if chunk_size_tokens < 1:
        raise ValueError(f"chunk_size_tokens must be >= 1, got {chunk_size_tokens}")
    if chunk_overlap_tokens < 0:
        raise ValueError(f"chunk_overlap_tokens must be >= 0, got {chunk_overlap_tokens}")
    if chunk_overlap_tokens >= chunk_size_tokens:
        raise ValueError(
            f"chunk_overlap_tokens ({chunk_overlap_tokens}) must be strictly less than "
            f"chunk_size_tokens ({chunk_size_tokens}) so the window advances."
        )

    if not text:
        return []

    encoder = _encoder()
    token_ids = encoder.encode(text)
    if not token_ids:
        return []

    decoded_text, offsets = encoder.decode_with_offsets(token_ids)
    if decoded_text != text:
        raise ValueError("token offsets did not round-trip the source text")
    if len(offsets) != len(token_ids):
        raise ValueError("token offsets must contain one entry per token")

    return list(_window(text, token_ids, offsets, chunk_size_tokens, chunk_overlap_tokens))


def _window(
    source_text: str,
    token_ids: list[int],
    offsets: list[int],
    size: int,
    overlap: int,
) -> Iterator[ChunkOut]:
    step = size - overlap
    ord_index = 0
    start = 0
    n = len(token_ids)
    while start < n:
        end = min(start + size, n)
        start_char = offsets[start]
        end_char = offsets[end] if end < n else len(source_text)
        text = source_text[start_char:end_char]
        yield ChunkOut(ord=ord_index, text=text, token_count=end - start)
        if end == n:
            return
        ord_index += 1
        start += step
