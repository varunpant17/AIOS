from datetime import UTC, datetime
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)


class Document(BaseModel):
    """Provider-neutral source document supplied to the ingestion boundary."""

    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    content: str = Field(min_length=1)
    source: str = Field(min_length=1)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("document_id")
    @classmethod
    def reject_empty_document_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("document_id must contain non-whitespace text")
        return value

    @field_validator("content", "source")
    @classmethod
    def reject_whitespace_only(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must contain non-whitespace text")
        return value


class Chunk(BaseModel):
    """A deterministic span of a document with source provenance."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    position: int = Field(ge=0)
    source: str = Field(min_length=1)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("chunk_id", "document_id")
    @classmethod
    def reject_empty_identifiers(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("identifiers must contain non-whitespace text")
        return value

    @field_validator("text", "source")
    @classmethod
    def reject_whitespace_only(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must contain non-whitespace text")
        return value


class VectorSearchResult(BaseModel):
    chunk: Chunk
    score: float = Field(allow_inf_nan=False)


class RetrievedChunk(BaseModel):
    """A chunk plus explicit document provenance and its relevance score."""

    chunk: Chunk
    document_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    score: float = Field(allow_inf_nan=False)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def provenance_matches_chunk(self):
        if self.document_id != self.chunk.document_id:
            raise ValueError("document_id must match the referenced chunk")
        if self.source != self.chunk.source:
            raise ValueError("source must match the referenced chunk")
        return self


class RAGContext(BaseModel):
    """Retrieval output suitable for a later generation layer; it calls no LLM."""

    query: str = Field(min_length=1)
    retrieved_chunks: list[RetrievedChunk] = Field(default_factory=list)
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("query")
    @classmethod
    def reject_whitespace_only(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must contain non-whitespace text")
        return value
