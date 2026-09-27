from collections.abc import Sequence
from typing import Protocol

from app.rag.types import Chunk, Document, VectorSearchResult


class EmbeddingProvider(Protocol):
    """Provider-neutral single and batch text embedding contract."""

    def embed(self, text: str) -> list[float]: ...

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]: ...


class VectorStore(Protocol):
    """Search returns highest-is-most-relevant scores in descending order."""

    def index(
        self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]
    ) -> None: ...

    def search(
        self, query_vector: Sequence[float], top_k: int
    ) -> list[VectorSearchResult]: ...


class Chunker(Protocol):
    """Replaceable document-to-chunks boundary."""

    def chunk(self, document: Document) -> list[Chunk]: ...
