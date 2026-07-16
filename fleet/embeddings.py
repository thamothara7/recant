"""LangChain adapter over the Embedder protocol (W3 plan section 3).

The fleet's working memory embeds TEXT via the configured embedder; custody
rows keep their controlled story vectors. Selection is env-driven so Titan
lands under U3 by setting RECANT_EMBEDDER=titan with zero fleet changes.
"""

from __future__ import annotations

from langchain_core.embeddings import Embeddings

from services.common.embedder import Embedder, select_embedder

__all__ = ["Embedder", "LangChainEmbedder", "select_embedder"]


class LangChainEmbedder(Embeddings):
    """Embeddings facade delegating to the Embedder protocol."""

    def __init__(self, inner: Embedder | None = None):
        self.inner = inner if inner is not None else select_embedder()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.inner.embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.inner.embed(text)
