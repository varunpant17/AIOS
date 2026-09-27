from collections.abc import Sequence
from time import perf_counter

from app.observability.interfaces import Observability
from app.observability.safe import operation_run, safe_emit
from app.observability.types import EventError, EventType
from app.rag.errors import (
    ChunkingError,
    EmbeddingError,
    InvalidChunkError,
    InvalidDocumentError,
    RAGError,
    VectorStoreError,
)
from app.rag.interfaces import Chunker, EmbeddingProvider, VectorStore
from app.rag.types import Chunk, Document


class IngestionService:
    """Chunks, embeds, and indexes a validated document through injected ports."""

    def __init__(
        self,
        chunker: Chunker,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
        *,
        observability: Observability | None = None,
    ) -> None:
        self._chunker = chunker
        self._embedding_provider = embedding_provider
        self._vector_store = vector_store
        self._observability = observability

    def ingest(self, document: Document) -> list[Chunk]:
        with operation_run(self._observability, "rag.ingestion") as operation:
            started = perf_counter()
            metadata = {"document_id": getattr(document, "document_id", "unknown")}
            safe_emit(
                self._observability,
                EventType.RAG_INGESTION_STARTED,
                "rag.ingestion",
                run_id=operation.run_id,
                metadata=metadata,
            )
            try:
                chunks = self._make_chunks(document)
                try:
                    vectors = self._embedding_provider.embed_many(
                        [chunk.text for chunk in chunks]
                    )
                    if len(vectors) != len(chunks):
                        raise EmbeddingError("Embedding provider returned an incomplete batch.")
                except EmbeddingError:
                    raise
                except Exception as exc:
                    raise EmbeddingError("Document embedding failed.") from exc
                try:
                    self._vector_store.index(chunks, vectors)
                except Exception as exc:
                    if isinstance(exc, VectorStoreError):
                        raise
                    raise VectorStoreError("Document vectors could not be indexed.") from exc
            except Exception as exc:
                safe_emit(
                    self._observability,
                    EventType.RAG_INGESTION_FAILED,
                    "rag.ingestion",
                    run_id=operation.run_id,
                    metadata=metadata,
                    duration_ms=(perf_counter() - started) * 1000,
                    error=EventError(
                        code=type(exc).__name__,
                        exception_type=type(exc).__name__,
                    ),
                )
                if isinstance(exc, RAGError):
                    raise
                raise ChunkingError("Document ingestion failed.") from exc
            safe_emit(
                self._observability,
                EventType.RAG_INGESTION_COMPLETED,
                "rag.ingestion",
                run_id=operation.run_id,
                metadata={**metadata, "chunk_count": len(chunks)},
                duration_ms=(perf_counter() - started) * 1000,
            )
            return chunks

    def _make_chunks(self, document: Document) -> list[Chunk]:
        if not isinstance(document, Document):
            raise InvalidDocumentError("Ingestion requires a validated Document.")
        try:
            chunks = list(self._chunker.chunk(document))
        except ChunkingError:
            raise
        except Exception as exc:
            raise ChunkingError("Document could not be chunked.") from exc
        if not chunks:
            raise ChunkingError("Chunker returned no chunks.")
        if any(not isinstance(chunk, Chunk) for chunk in chunks):
            raise InvalidChunkError("Chunker returned an invalid chunk contract.")
        if any(chunk.document_id != document.document_id for chunk in chunks):
            raise InvalidChunkError(
                "Chunker returned a chunk with mismatched document provenance."
            )
        if any(chunk.source != document.source for chunk in chunks):
            raise InvalidChunkError(
                "Chunker returned a chunk with mismatched source provenance."
            )
        return chunks
