from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import Field, JsonValue, field_validator, model_validator

from app.agents.types import AgentErrorInfo
from app.core.immutable import ImmutableDomainModel, freeze_json


class AgentTaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentMessageType(StrEnum):
    TASK_REQUEST = "task.request"


class AgentTask(ImmutableDomainModel):
    """Immutable state snapshot for one bounded delegated agent invocation."""

    task_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    requester_agent_id: str = Field(min_length=1)
    assignee_agent_id: str = Field(min_length=1)
    conversation_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    status: AgentTaskStatus = AgentTaskStatus.PENDING
    payload: dict[str, JsonValue]
    result: dict[str, JsonValue] | None = None
    error: AgentErrorInfo | None = None
    version: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @field_validator("task_id", "requester_agent_id", "assignee_agent_id", "conversation_id")
    @classmethod
    def reject_blank_ids(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("task and agent identifiers must contain non-whitespace text")
        return value

    @field_validator("payload", "result")
    @classmethod
    def freeze_json_fields(cls, value: Any) -> Any:
        return freeze_json(value) if value is not None else None

    @field_validator("created_at", "started_at", "completed_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        try:
            is_utc = value.tzinfo is not None and value.utcoffset() == timedelta(0)
        except (OverflowError, TypeError, ValueError):
            is_utc = False
        if not is_utc:
            raise ValueError("timestamps must be timezone-aware UTC values")
        return value

    @model_validator(mode="after")
    def validate_lifecycle(self):
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("started_at cannot be earlier than created_at")
        if self.completed_at is not None:
            lower_bound = self.started_at or self.created_at
            if self.completed_at < lower_bound:
                raise ValueError("completed_at cannot precede the prior lifecycle timestamp")
        if self.status == AgentTaskStatus.PENDING:
            valid = (
                self.version == 0
                and self.started_at is None
                and self.completed_at is None
                and self.result is None
                and self.error is None
            )
        elif self.status == AgentTaskStatus.RUNNING:
            valid = (
                self.version == 1
                and self.started_at is not None
                and self.completed_at is None
                and self.result is None
                and self.error is None
            )
        elif self.status == AgentTaskStatus.COMPLETED:
            valid = (
                self.version == 2
                and self.started_at is not None
                and self.completed_at is not None
                and self.result is not None
                and self.error is None
            )
        else:
            valid = (
                self.version == 2
                and self.started_at is not None
                and self.completed_at is not None
                and self.error is not None
            )
        if not valid:
            raise ValueError("agent task fields do not match its lifecycle status")
        return self

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> "AgentTask":
        if update and "status" in update:
            next_status = AgentTaskStatus(update["status"])
            allowed = {
                AgentTaskStatus.PENDING: {
                    AgentTaskStatus.PENDING,
                    AgentTaskStatus.RUNNING,
                },
                AgentTaskStatus.RUNNING: {
                    AgentTaskStatus.RUNNING,
                    AgentTaskStatus.COMPLETED,
                    AgentTaskStatus.FAILED,
                },
                AgentTaskStatus.COMPLETED: {AgentTaskStatus.COMPLETED},
                AgentTaskStatus.FAILED: {AgentTaskStatus.FAILED},
            }
            if next_status not in allowed[self.status]:
                raise ValueError(
                    f"Cannot transition task from {self.status.value} to {next_status.value}."
                )
        return super().model_copy(update=update, deep=deep)


class AgentMessage(ImmutableDomainModel):
    """Provider-neutral communication envelope; it does not execute work."""

    message_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    sender_agent_id: str = Field(min_length=1)
    recipient_agent_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    message_type: AgentMessageType
    payload: dict[str, JsonValue]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator(
        "message_id", "sender_agent_id", "recipient_agent_id", "conversation_id", "task_id"
    )
    @classmethod
    def reject_blank_ids(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message and agent identifiers must contain non-whitespace text")
        return value

    @field_validator("payload")
    @classmethod
    def freeze_payload(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return freeze_json(value)

    @field_validator("created_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        try:
            is_utc = value.tzinfo is not None and value.utcoffset() == timedelta(0)
        except (OverflowError, TypeError, ValueError):
            is_utc = False
        if not is_utc:
            raise ValueError("created_at must be timezone-aware UTC")
        return value
