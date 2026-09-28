from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import uuid4

from pydantic import Field, JsonValue, field_validator, model_validator

from app.core.immutable import ImmutableDomainModel, freeze_json


class PlanStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class PlanStepStatus(StrEnum):
    PLANNED = "planned"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class PlanStepSpec(ImmutableDomainModel):
    """Explicit input for a planned step; it describes work without executing it."""

    description: str = Field(min_length=1)
    action: str = Field(min_length=1)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("description", "action")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must contain non-whitespace text")
        return value

    @field_validator("metadata")
    @classmethod
    def freeze_metadata(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return freeze_json(value)


class PlanStep(ImmutableDomainModel):

    step_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    position: int = Field(ge=0)
    description: str = Field(min_length=1)
    action: str = Field(min_length=1)
    status: PlanStepStatus = PlanStepStatus.PLANNED
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("step_id", "description", "action")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must contain non-whitespace text")
        return value

    @field_validator("metadata")
    @classmethod
    def freeze_metadata(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return freeze_json(value)


class Plan(ImmutableDomainModel):

    plan_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    goal: str = Field(min_length=1)
    steps: tuple[PlanStep, ...] = Field(min_length=1)
    status: PlanStatus = PlanStatus.DRAFT
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("plan_id", "goal")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must contain non-whitespace text")
        return value

    @field_validator("metadata")
    @classmethod
    def freeze_metadata(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return freeze_json(value)

    @field_validator("created_at", "updated_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        try:
            is_utc = value.tzinfo is not None and value.utcoffset() == timedelta(0)
        except (OverflowError, TypeError, ValueError):
            is_utc = False
        if not is_utc:
            raise ValueError("timestamps must be timezone-aware UTC values")
        return value

    @model_validator(mode="after")
    def validate_plan_invariants(self):
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")
        positions = tuple(step.position for step in self.steps)
        if positions != tuple(range(len(self.steps))):
            raise ValueError("plan steps must be ordered with contiguous positions from zero")
        identifiers = tuple(step.step_id for step in self.steps)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("plan step IDs must be unique")
        return self
