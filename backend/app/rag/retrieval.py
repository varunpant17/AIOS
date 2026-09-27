from time import perf_counter

from app.observability.interfaces import Observability
from app.observability.safe import operation_run, safe_emit
from app.observability.types import EventError, EventType
from app.rag.errors import (
    EmbeddingError,
    InvalidQueryError,
    InvalidTopKError,
    RetrievalError,
    VectorStoreError,
)
from app.rag.interfaces import EmbeddingProvider, VectorStore
from app.rag.types import RAGContext, RetrievedChunk


class Retriever:
    """Embeds queries and returns relevant chunks without generating answers."""

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
        *,
        top_k: int = 5,
        observability: Observability | None = None,
    ) -> None:
        self._validate_top_k(top_k)
        self._embedding_provider = embedding_provider
        self._vector_store = vector_store
        self._top_k = top_k
        self._observability = observability

    def retrieve(self, query: str, *, top_k: int | None = None) -> RAGContext:
        effective_top_k = self._top_k if top_k is None else top_k
        with operation_run(self._observability, "rag.retrieval") as operation:
            started = perf_counter()
            safe_emit(
                self._observability,
                EventType.RAG_RETRIEVAL_STARTED,
                "rag.retrieval",
                run_id=operation.run_id,
                metadata={"top_k": effective_top_k},
            )
            try:
                if not isinstance(query, str) or not query.strip():
                    raise InvalidQueryError(
                        "Retrieval query must contain non-whitespace text."
                    )
                self._validate_top_k(effective_top_k)
                try:
                    query_vector = self._embedding_provider.embed(query)
                except Exception as exc:
                    raise EmbeddingError("Query embedding failed.") from exc
                try:
                    matches = self._vector_store.search(query_vector, effective_top_k)
                except Exception as exc:
                    if isinstance(exc, VectorStoreError):
                        raise
                    raise RetrievalError("Vector search failed.") from exc
                matches = sorted(
                    matches,
                    key=lambda match: (-match.score, match.chunk.chunk_id),
                )
                retrieved = [
                    RetrievedChunk(
                        chunk=match.chunk,
                        document_id=match.chunk.document_id,
                        source=match.chunk.source,
                        score=match.score,
                        metadata=dict(match.chunk.metadata),
                    )
                    for match in matches
                ]
            except Exception as exc:
                safe_emit(
                    self._observability,
                    EventType.RAG_RETRIEVAL_FAILED,
                    "rag.retrieval",
                    run_id=operation.run_id,
                    metadata={"top_k": effective_top_k},
                    duration_ms=(perf_counter() - started) * 1000,
                    error=EventError(
                        code=type(exc).__name__, exception_type=type(exc).__name__
                    ),
                )
                if isinstance(
                    exc,
                    (
                        InvalidQueryError,
                        InvalidTopKError,
                        EmbeddingError,
                        VectorStoreError,
                        RetrievalError,
                    ),
                ):
                    raise
                raise RetrievalError("Retrieval operation failed.") from exc
            context = RAGContext(
                query=query,
                retrieved_chunks=retrieved,
                metadata={"result_count": len(retrieved)},
            )
            safe_emit(
                self._observability,
                EventType.RAG_RETRIEVAL_COMPLETED,
                "rag.retrieval",
                run_id=operation.run_id,
                metadata={"top_k": effective_top_k, "result_count": len(retrieved)},
                duration_ms=(perf_counter() - started) * 1000,
            )
            return context

    @staticmethod
    def _validate_top_k(top_k: int) -> None:
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
            raise InvalidTopKError("top_k must be a positive integer.")
