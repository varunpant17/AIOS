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
