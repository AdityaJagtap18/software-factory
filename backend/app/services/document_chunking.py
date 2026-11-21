"""Real document chunking for the RAG pipeline (P4-2) -- a plain,
deterministic character-window splitter. No ML involved here; chunking is a
mechanical text-splitting step, not a modeling step, so there is nothing to
"fabricate" -- the only design choices are window size and overlap, both
explicit below.
"""

DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 100


def chunk_text(
    text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP
) -> list[str]:
    """Splits `text` into overlapping character windows, trimmed of
    surrounding whitespace, dropping any window that is empty after
    trimming (e.g. trailing whitespace-only tail). `overlap` must be
    smaller than `chunk_size` or this would never advance."""
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    text = text.strip()
    if not text:
        return []

    chunks: list[str] = []
    start = 0
    length = len(text)
    step = chunk_size - overlap
    while start < length:
        window = text[start : start + chunk_size].strip()
        if window:
            chunks.append(window)
        start += step
    return chunks
