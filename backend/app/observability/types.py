from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EventType(StrEnum):
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    LLM_REQUEST = "llm.request"
    LLM_RESPONSE = "llm.response"
    LLM_FAILED = "llm.failed"
    TOOL_REQUEST = "tool.request"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"
    MCP_REQUEST = "mcp.request"
    MCP_COMPLETED = "mcp.completed"
    MCP_FAILED = "mcp.failed"
    RAG_INGESTION_STARTED = "rag.ingestion.started"
    RAG_INGESTION_COMPLETED = "rag.ingestion.completed"
    RAG_INGESTION_FAILED = "rag.ingestion.failed"
    RAG_RETRIEVAL_STARTED = "rag.retrieval.started"
    RAG_RETRIEVAL_COMPLETED = "rag.retrieval.completed"
    RAG_RETRIEVAL_FAILED = "rag.retrieval.failed"
    MEMORY_STORE_STARTED = "memory.store.started"
    MEMORY_STORE_COMPLETED = "memory.store.completed"
    MEMORY_STORE_FAILED = "memory.store.failed"
    MEMORY_SEARCH_STARTED = "memory.search.started"
    MEMORY_SEARCH_COMPLETED = "memory.search.completed"
    MEMORY_SEARCH_FAILED = "memory.search.failed"
    MEMORY_DELETE_STARTED = "memory.delete.started"
    MEMORY_DELETE_COMPLETED = "memory.delete.completed"
    MEMORY_DELETE_FAILED = "memory.delete.failed"
    MEMORY_GET_STARTED = "memory.get.started"
    MEMORY_GET_COMPLETED = "memory.get.completed"
    MEMORY_GET_FAILED = "memory.get.failed"
    PLANNING_STARTED = "planning.started"
    PLANNING_COMPLETED = "planning.completed"
    PLANNING_FAILED = "planning.failed"
    REFLECTION_STARTED = "reflection.started"
    REFLECTION_COMPLETED = "reflection.completed"
    REFLECTION_FAILED = "reflection.failed"


class EventError(BaseModel):
    code: str
    exception_type: str


class RunContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    status: RunStatus = RunStatus.RUNNING
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    error: EventError | None = None


class ObservabilityEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event_type: EventType
    component: str = Field(min_length=1)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    duration_ms: float | None = Field(default=None, ge=0)
    error: EventError | None = None


class RunTransitionError(ValueError):
    """Raised when a run is completed more than once or from an invalid state."""


class RunState:
    def __init__(self, context: RunContext) -> None:
        self.context = context
        self.lock = RLock()
