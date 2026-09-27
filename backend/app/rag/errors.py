class RAGError(Exception):
    """Base class for normalized AIOS RAG boundary errors."""


class InvalidDocumentError(RAGError):
    pass


class InvalidChunkError(RAGError):
    pass


class InvalidQueryError(RAGError):
    pass


class InvalidTopKError(RAGError):
    pass


class ChunkingError(RAGError):
    pass


class EmbeddingError(RAGError):
    pass


class VectorStoreError(RAGError):
    pass


class VectorDimensionError(VectorStoreError):
    pass


class RetrievalError(RAGError):
    pass
