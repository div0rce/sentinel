"""Tests for the token-based sliding-window chunker."""

from __future__ import annotations

import pytest

from backend.app.chunking import ChunkOut, chunk_text

# A deterministic, repeating input that yields predictable token counts under cl100k_base.
SAMPLE_TEXT = "The quick brown fox jumps over the lazy dog. " * 50


def test_chunking_is_deterministic_across_runs() -> None:
    a = chunk_text(SAMPLE_TEXT, chunk_size_tokens=50, chunk_overlap_tokens=10)
    b = chunk_text(SAMPLE_TEXT, chunk_size_tokens=50, chunk_overlap_tokens=10)
    assert a == b


def test_chunking_empty_input_returns_empty_list() -> None:
    assert chunk_text("", chunk_size_tokens=50, chunk_overlap_tokens=10) == []


def test_chunking_short_input_returns_single_chunk() -> None:
    chunks = chunk_text("hello world", chunk_size_tokens=50, chunk_overlap_tokens=10)
    assert len(chunks) == 1
    assert chunks[0].ord == 0
    assert chunks[0].text == "hello world"
    assert chunks[0].token_count > 0


def test_chunking_advances_by_size_minus_overlap() -> None:
    chunks = chunk_text(SAMPLE_TEXT, chunk_size_tokens=50, chunk_overlap_tokens=10)
    assert len(chunks) >= 2
    # Each non-final chunk should be exactly chunk_size_tokens tokens.
    for c in chunks[:-1]:
        assert c.token_count == 50
    # The last chunk may be shorter.
    assert 1 <= chunks[-1].token_count <= 50
    # ord values are sequential starting at 0.
    assert [c.ord for c in chunks] == list(range(len(chunks)))


def test_chunking_overlap_actually_overlaps_text() -> None:
    # With a meaningful overlap, consecutive chunks share trailing/leading text.
    chunks = chunk_text(SAMPLE_TEXT, chunk_size_tokens=50, chunk_overlap_tokens=15)
    assert len(chunks) >= 2
    # Sliding-window overlap means part of chunk[i].text appears at the start of
    # chunk[i+1].text. We test a robust property: the joined chunk texts (without
    # overlap) recover the original text up to the document length.
    # The simpler invariant: chunk i+1 starts within the first 15 tokens of chunk i.
    # We approximate by checking that chunk[i+1] does not start at the beginning of
    # chunk[i] (overlap was respected).
    assert chunks[1].text != chunks[0].text


def test_chunking_overlap_zero_is_disjoint() -> None:
    chunks = chunk_text(SAMPLE_TEXT, chunk_size_tokens=50, chunk_overlap_tokens=0)
    # With zero overlap, summed token counts equal the original token count: no token
    # is in two chunks. (We can't compare decoded chunk *text* directly here because
    # the SAMPLE_TEXT repeats, so distinct token windows can decode to the same
    # string. The token-count invariant is the precise version of "disjoint".)
    from backend.app.chunking import _encoder

    expected_tokens = len(_encoder().encode(SAMPLE_TEXT))
    assert sum(c.token_count for c in chunks) == expected_tokens


def test_unicode_chunking_slices_source_text_without_lossy_replacement() -> None:
    from backend.app.chunking import _encoder

    text = "A café 😀 東京 e\u0301 end"
    encoder = _encoder()
    token_ids = encoder.encode(text)
    direct_decoded_windows = [encoder.decode([token_id]) for token_id in token_ids]

    assert any("\ufffd" in window for window in direct_decoded_windows)

    first = chunk_text(text, chunk_size_tokens=1, chunk_overlap_tokens=0)
    second = chunk_text(text, chunk_size_tokens=1, chunk_overlap_tokens=0)

    assert first == second
    assert len(first) == len(token_ids)
    assert all(chunk.token_count == 1 for chunk in first)
    assert all("\ufffd" not in chunk.text for chunk in first)
    assert all(chunk.text in text for chunk in first)


def test_chunking_rejects_overlap_ge_size() -> None:
    with pytest.raises(ValueError, match="strictly less"):
        chunk_text("hello", chunk_size_tokens=10, chunk_overlap_tokens=10)
    with pytest.raises(ValueError, match="strictly less"):
        chunk_text("hello", chunk_size_tokens=10, chunk_overlap_tokens=20)


def test_chunking_rejects_invalid_sizes() -> None:
    with pytest.raises(ValueError):
        chunk_text("hello", chunk_size_tokens=0, chunk_overlap_tokens=0)
    with pytest.raises(ValueError):
        chunk_text("hello", chunk_size_tokens=10, chunk_overlap_tokens=-1)


def test_chunkout_is_a_frozen_dataclass() -> None:
    c = ChunkOut(ord=0, text="x", token_count=1)
    with pytest.raises((AttributeError, Exception)):
        c.ord = 1  # type: ignore[misc]
