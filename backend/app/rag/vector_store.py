import math
from collections.abc import Sequence
from threading import RLock

from app.rag.errors import (
    InvalidChunkError,
    InvalidTopKError,
    VectorDimensionError,
    VectorStoreError,
)
from app.rag.types import Chunk, VectorSearchResult


class InMemoryVectorStore:
    """Thread-safe in-memory cosine index for tests and local development."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[Chunk, tuple[float, ...]]] = {}
        self._dimensions: int | None = None
        self._lock = RLock()

    def index(
        self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]
    ) -> None:
        if len(chunks) != len(vectors):
            raise VectorStoreError("Each chunk must have exactly one embedding vector.")
        if not chunks:
            raise InvalidChunkError("Cannot index an empty chunk batch.")
        prepared: list[tuple[Chunk, tuple[float, ...]]] = []
        batch_dimensions: int | None = None
        batch_ids: set[str] = set()
        for chunk, vector in zip(chunks, vectors, strict=True):
            if not isinstance(chunk, Chunk):
                raise InvalidChunkError("Vector store accepts validated Chunk objects.")
            normalized = self._validate_vector(vector)
            if batch_dimensions is None:
                batch_dimensions = len(normalized)
            elif len(normalized) != batch_dimensions:
                raise VectorDimensionError(
                    "Embedding batch contains inconsistent dimensions."
                )
            if chunk.chunk_id in batch_ids:
                raise VectorStoreError(
                    f"Duplicate chunk id '{chunk.chunk_id}' in index batch."
                )
            batch_ids.add(chunk.chunk_id)
            prepared.append((chunk.model_copy(deep=True), normalized))

        with self._lock:
            if self._dimensions is not None and batch_dimensions != self._dimensions:
                raise VectorDimensionError(
                    f"Expected {self._dimensions}-dimensional vectors; got {batch_dimensions}."
                )
            duplicate = next(
                (
                    chunk.chunk_id
                    for chunk, _ in prepared
                    if chunk.chunk_id in self._items
                ),
                None,
            )
            if duplicate is not None:
                raise VectorStoreError(f"Chunk '{duplicate}' is already indexed.")
            if self._dimensions is None:
                self._dimensions = batch_dimensions
            self._items.update(
                (chunk.chunk_id, (chunk, vector)) for chunk, vector in prepared
            )

    def search(
        self, query_vector: Sequence[float], top_k: int
    ) -> list[VectorSearchResult]:
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
            raise InvalidTopKError("top_k must be a positive integer.")
        query = self._validate_vector(query_vector)
        with self._lock:
            if not self._items:
                return []
            if len(query) != self._dimensions:
                raise VectorDimensionError(
                    f"Expected a {self._dimensions}-dimensional query vector; got {len(query)}."
                )
            scored = [
                (self._cosine(query, vector), chunk)
                for chunk, vector in self._items.values()
            ]
        scored.sort(key=lambda pair: (-pair[0], pair[1].chunk_id))
        return [
            VectorSearchResult(chunk=chunk.model_copy(deep=True), score=score)
            for score, chunk in scored[:top_k]
        ]

    @staticmethod
    def _validate_vector(vector: Sequence[float]) -> tuple[float, ...]:
        if isinstance(vector, (str, bytes)) or not vector:
            raise VectorDimensionError("Vectors must contain at least one numeric value.")
        try:
            values = tuple(float(value) for value in vector)
        except (TypeError, ValueError) as exc:
            raise VectorStoreError("Vectors must contain numeric values.") from exc
        if any(not math.isfinite(value) for value in values):
            raise VectorStoreError("Vectors must contain only finite values.")
        return values

    @staticmethod
    def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if not left_norm or not right_norm:
            return 0.0
        return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)
