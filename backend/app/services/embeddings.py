"""Real text embeddings for the RAG pipeline (P4-3), via this project's own
local Ollama instance (the same `OLLAMA_HOST` the Qwen adapter already
targets -- see `agent_runtime/adapters.py`) running the `nomic-embed-text`
model. No API key, no external network call, no fabricated/random vectors:
if Ollama or the model isn't available, this raises `EmbeddingError` honestly
rather than returning a placeholder embedding.
"""

import os

import httpx

_OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
_EMBEDDING_MODEL = "nomic-embed-text"
_TIMEOUT_SECONDS = 30


class EmbeddingError(Exception):
    pass


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Returns one real embedding vector per input string, in order. Raises
    `EmbeddingError` if the local embedding model can't be reached -- never
    silently substitutes a zero/random vector."""
    if not texts:
        return []
    try:
        resp = httpx.post(
            f"{_OLLAMA_URL}/api/embed",
            json={"model": _EMBEDDING_MODEL, "input": texts},
            timeout=_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise EmbeddingError(
            f"Could not reach the local embedding model '{_EMBEDDING_MODEL}' at {_OLLAMA_URL}: {exc}"
        ) from exc

    data = resp.json()
    embeddings = data.get("embeddings")
    if not embeddings or len(embeddings) != len(texts):
        raise EmbeddingError(
            f"Embedding provider returned an unexpected response shape for {len(texts)} input(s)."
        )
    return embeddings


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]
