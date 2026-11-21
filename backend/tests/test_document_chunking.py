import pytest

from app.services.document_chunking import chunk_text


def test_chunk_text_returns_empty_for_blank_input():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_chunk_text_returns_single_chunk_when_shorter_than_window():
    chunks = chunk_text("hello world", chunk_size=800, overlap=100)
    assert chunks == ["hello world"]


def test_chunk_text_splits_long_text_into_overlapping_windows():
    text = "A" * 50 + "B" * 50 + "C" * 50  # 150 chars
    chunks = chunk_text(text, chunk_size=60, overlap=10)
    assert len(chunks) > 1
    # every chunk must actually be a real substring of the source text
    for c in chunks:
        assert c in text
    # overlap means consecutive chunks share real text, not just coincidence
    assert chunks[0][-10:] == text[50:60]
    assert chunks[1][:10] == text[50:60]


def test_chunk_text_rejects_overlap_not_smaller_than_chunk_size():
    with pytest.raises(ValueError):
        chunk_text("some text", chunk_size=10, overlap=10)
