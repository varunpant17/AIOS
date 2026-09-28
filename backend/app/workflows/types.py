from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import Field, JsonValue, field_validator, model_validator

from app.core.immutable import ImmutableDomainModel, freeze_json


class WorkflowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowStepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepErrorInfo(ImmutableDomainModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    exception_type: str = Field(min_length=1)

    @field_validator("code", "message", "exception_type")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("error fields must contain non-whitespace text")
        return value


class StepResult(ImmutableDomainModel):
    """Provider-neutral, normalized outcome from one execution step."""

    success: bool
    output: JsonValue | None = None
    error: StepErrorInfo | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("output")
    @classmethod
    def freeze_output(cls, value: Any) -> Any:
        return freeze_json(value) if value is not None else None

    @field_validator("metadata")
    @classmethod
    def freeze_metadata(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return freeze_json(value)

    @field_validator("timestamp")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        try:
            valid = value.tzinfo is not None and value.utcoffset() == timedelta(0)
        except (OverflowError, TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError("timestamp must be a timezone-aware UTC value")
        return value

    @model_validator(mode="after")
    def validate_outcome(self):
        if self.success == (self.error is not None):
            raise ValueError("successful results have no error; failed results require one")
        return self


class WorkflowContext(ImmutableDomainModel):
    """Immutable execution-scoped JSON context passed to step executors."""

    workflow_id: str = Field(min_length=1)
    inputs: dict[str, JsonValue] = Field(default_factory=dict)
    outputs: dict[str, JsonValue] = Field(default_factory=dict)
    variables: dict[str, JsonValue] = Field(default_factory=dict)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("workflow_id")
    @classmethod
    def reject_blank_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("workflow_id must contain non-whitespace text")
        return value

    @field_validator("inputs", "outputs", "variables", "metadata")
    @classmethod
    def freeze_values(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return freeze_json(value)


class WorkflowStep(ImmutableDomainModel):
    """Execution-specific state for one step derived from a planned step."""

    step_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    source_step_id: str = Field(min_length=1)
    position: int = Field(ge=0)
    description: str = Field(min_length=1)
    action: str = Field(min_length=1)
    status: WorkflowStepStatus = WorkflowStepStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: StepResult | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("step_id", "source_step_id", "description", "action")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("workflow step identifiers and text must be nonblank")
        return value

    @field_validator("metadata")
    @classmethod
    def freeze_metadata(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return freeze_json(value)

    @field_validator("started_at", "completed_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        try:
            valid = value.tzinfo is not None and value.utcoffset() == timedelta(0)
        except (OverflowError, TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError("timestamps must be timezone-aware UTC values")
        return value

    @model_validator(mode="after")
    def validate_lifecycle(self):
        if self.started_at is not None and self.completed_at is not None:
            if self.completed_at < self.started_at:
                raise ValueError("completed_at cannot be earlier than started_at")
        if self.status == WorkflowStepStatus.PENDING:
            valid = self.started_at is None and self.completed_at is None and self.result is None
        elif self.status == WorkflowStepStatus.RUNNING:
            valid = self.started_at is not None and self.completed_at is None and self.result is None
        elif self.status == WorkflowStepStatus.COMPLETED:
            valid = (
                self.started_at is not None
                and self.completed_at is not None
                and self.result is not None
                and self.result.success
            )
        elif self.status == WorkflowStepStatus.FAILED:
            valid = (
                self.started_at is not None
                and self.completed_at is not None
                and self.result is not None
                and not self.result.success
            )
        else:
            valid = self.completed_at is not None and self.result is None
        if not valid:
            raise ValueError("workflow step fields do not match its lifecycle status")
        return self


class Workflow(ImmutableDomainModel):
    """One execution instance of an immutable planning intention."""

    workflow_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    version: int = Field(default=0, ge=0)
    plan_id: str = Field(min_length=1)
    steps: tuple[WorkflowStep, ...] = Field(min_length=1)
    status: WorkflowStatus = WorkflowStatus.PENDING
    start_event_emitted: bool = False
    current_step_id: str | None = None
    current_step_position: int | None = None
    context: WorkflowContext
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("workflow_id", "plan_id")
    @classmethod
    def reject_blank_ids(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("workflow identifiers must contain non-whitespace text")
        return value

    @field_validator("created_at", "started_at", "completed_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        try:
            valid = value.tzinfo is not None and value.utcoffset() == timedelta(0)
        except (OverflowError, TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError("timestamps must be timezone-aware UTC values")
        return value

    @field_validator("metadata")
    @classmethod
    def freeze_metadata(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return freeze_json(value)

    @model_validator(mode="after")
    def validate_workflow(self):
        if self.context.workflow_id != self.workflow_id:
            raise ValueError("context workflow_id must match workflow_id")
        if tuple(step.position for step in self.steps) != tuple(range(len(self.steps))):
            raise ValueError("workflow steps must have contiguous ordered positions")
        if len({step.step_id for step in self.steps}) != len(self.steps):
            raise ValueError("workflow step IDs must be unique")
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("started_at cannot be earlier than created_at")
        if self.completed_at is not None:
            lower_bound = self.started_at or self.created_at
            if self.completed_at < lower_bound:
                raise ValueError("completed_at cannot be earlier than started_at or created_at")
        if self.current_step_id is None:
            if self.current_step_position is not None:
                raise ValueError("current_step_position requires current_step_id")
        else:
            matches = [step for step in self.steps if step.step_id == self.current_step_id]
            if not matches or matches[0].position != self.current_step_position:
                raise ValueError("current step fields must identify an existing workflow step")
        if self.status == WorkflowStatus.PENDING:
            valid = (
                self.started_at is None
                and self.completed_at is None
                and not self.start_event_emitted
                and all(step.status == WorkflowStepStatus.PENDING for step in self.steps)
            )
        elif self.status in {WorkflowStatus.RUNNING, WorkflowStatus.CANCELLING}:
            running = [step for step in self.steps if step.status == WorkflowStepStatus.RUNNING]
            valid = (
                self.started_at is not None
                and self.completed_at is None
                and len(running) <= 1
                and (not running or running[0].step_id == self.current_step_id)
                and (self.current_step_id is None or bool(running))
            )
        elif self.status == WorkflowStatus.COMPLETED:
            valid = (
                self.completed_at is not None
                and all(step.status == WorkflowStepStatus.COMPLETED for step in self.steps)
            )
        elif self.status == WorkflowStatus.FAILED:
            valid = (
                self.completed_at is not None
                and any(step.status == WorkflowStepStatus.FAILED for step in self.steps)
                and not any(step.status == WorkflowStepStatus.RUNNING for step in self.steps)
            )
        elif self.status == WorkflowStatus.CANCELLED:
            valid = (
                self.completed_at is not None
                and not any(
                    step.status in {WorkflowStepStatus.PENDING, WorkflowStepStatus.RUNNING}
                    for step in self.steps
                )
            )
        else:
            valid = False
        if not valid:
            raise ValueError("workflow timestamps do not match its lifecycle status")
        return self
