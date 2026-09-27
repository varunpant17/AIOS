"""Provider-neutral retrieval-augmented generation foundations."""

from app.rag.chunking import FixedSizeChunker
from app.rag.embeddings import DeterministicHashEmbeddingProvider
from app.rag.errors import (
    ChunkingError,
    EmbeddingError,
    InvalidChunkError,
    InvalidDocumentError,
    InvalidQueryError,
    InvalidTopKError,
    RAGError,
    RetrievalError,
    VectorDimensionError,
    VectorStoreError,
)
from app.rag.ingestion import IngestionService
from app.rag.interfaces import Chunker, EmbeddingProvider, VectorStore
from app.rag.retrieval import Retriever
from app.rag.types import (
    Chunk,
    Document,
    RAGContext,
    RetrievedChunk,
    VectorSearchResult,
)
from app.rag.vector_store import InMemoryVectorStore

__all__ = [
    "Chunk",
    "Chunker",
    "ChunkingError",
    "DeterministicHashEmbeddingProvider",
    "Document",
    "EmbeddingError",
    "EmbeddingProvider",
    "FixedSizeChunker",
    "InMemoryVectorStore",
    "IngestionService",
    "InvalidChunkError",
    "InvalidDocumentError",
    "InvalidQueryError",
    "InvalidTopKError",
    "RAGContext",
    "RAGError",
    "RetrievedChunk",
    "RetrievalError",
    "Retriever",
    "VectorDimensionError",
    "VectorSearchResult",
    "VectorStore",
    "VectorStoreError",
]
