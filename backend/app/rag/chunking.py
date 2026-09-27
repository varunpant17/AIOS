from uuid import NAMESPACE_URL, uuid5

from app.rag.errors import ChunkingError
from app.rag.types import Chunk, Document


class FixedSizeChunker:
    """Deterministic character-window chunker; not token-aware."""

    def __init__(self, chunk_size: int = 800, overlap: int = 0) -> None:
        if (
            not isinstance(chunk_size, int)
            or isinstance(chunk_size, bool)
            or chunk_size < 1
        ):
            raise ValueError("chunk_size must be positive")
        if (
            not isinstance(overlap, int)
            or isinstance(overlap, bool)
            or overlap < 0
            or overlap >= chunk_size
        ):
            raise ValueError("overlap must be nonnegative and smaller than chunk_size")
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, document: Document) -> list[Chunk]:
        if not isinstance(document, Document):
            raise ChunkingError("Chunker requires a validated Document.")
        chunks: list[Chunk] = []
        start = 0
        while start < len(document.content):
            end = min(start + self.chunk_size, len(document.content))
            text = document.content[start:end].strip()
            if text:
                position = len(chunks)
                chunk_id = str(
                    uuid5(
                        NAMESPACE_URL,
                        f"aios-rag:{document.document_id}:{position}:{start}:{end}",
                    )
                )
                chunks.append(
                    Chunk(
                        chunk_id=chunk_id,
                        document_id=document.document_id,
                        text=text,
                        position=position,
                        source=document.source,
                        metadata={
                            **document.metadata,
                            "start_char": start,
                            "end_char": end,
                        },
                    )
                )
            if end == len(document.content):
                break
            start = end - self.overlap
        if not chunks:
            raise ChunkingError("Document content produced no non-empty chunks.")
        return chunks
