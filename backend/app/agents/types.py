from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from app.core.immutable import ImmutableDomainModel
from app.llm.types import Message


class AgentDefinition(BaseModel):
    """Provider-neutral identity and execution defaults for an agent."""

    agent_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    model: str | None = None
    system_instructions: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)
    capabilities: tuple[str, ...] = ()

    @field_validator("agent_id", "name")
    @classmethod
    def reject_blank_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("agent identity fields must contain non-whitespace text")
        return value

    @field_validator("capabilities")
    @classmethod
    def normalize_capabilities(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted(capability.strip().casefold() for capability in value))
        if any(not capability for capability in normalized):
            raise ValueError("agent capabilities must contain non-whitespace text")
        if len(set(normalized)) != len(normalized):
            raise ValueError("agent capabilities must be unique")
        return normalized

class AgentContext(BaseModel):
    """Execution-scoped input and context; this is not persistent memory."""

    user_input: str
    goal: str | None = None
    conversation: list[Message] = Field(default_factory=list)
    request_id: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)


class AgentExecutionStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentErrorInfo(ImmutableDomainModel):
    code: str
    message: str
    exception_type: str
    cause_type: str | None = None


class AgentEventType(StrEnum):
    EXECUTION_STARTED = "execution_started"
    LLM_INVOKED = "llm_invoked"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"
    EXECUTION_CANCELLED = "execution_cancelled"


class AgentEvent(BaseModel):
    type: AgentEventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, str] = Field(default_factory=dict)


class AgentState(BaseModel):
    """Mutable state for one in-process agent execution."""

    execution_id: str = Field(default_factory=lambda: str(uuid4()))
    agent_id: str
    status: AgentExecutionStatus = AgentExecutionStatus.CREATED
    iteration: int = 0
    messages: list[Message] = Field(default_factory=list)
    result: str | None = None
    error: AgentErrorInfo | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    events: list[AgentEvent] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def transition(self, status: AgentExecutionStatus) -> None:
        allowed = {
            AgentExecutionStatus.CREATED: {AgentExecutionStatus.RUNNING},
            AgentExecutionStatus.RUNNING: {
                AgentExecutionStatus.COMPLETED,
                AgentExecutionStatus.FAILED,
                AgentExecutionStatus.CANCELLED,
            },
        }
        if status not in allowed.get(self.status, set()):
            from app.agents.exceptions import AgentStateTransitionError

            raise AgentStateTransitionError(
                f"Cannot transition execution from {self.status} to {status}."
            )
        self.status = status
        self.updated_at = datetime.now(UTC)


class AgentResult(BaseModel):
    """Stable output contract returned to callers of the runtime."""

    execution_id: str
    agent_id: str
    status: AgentExecutionStatus
    output: str | None = None
    error: AgentErrorInfo | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    started_at: datetime
    completed_at: datetime
