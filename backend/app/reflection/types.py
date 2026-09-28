from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import Field, JsonValue, field_validator

from app.core.immutable import ImmutableDomainModel, freeze_json


class ReflectionOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ReflectionResult(ImmutableDomainModel):
    """Structured assessment of an already-produced result; contains no execution logic."""

    reflection_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    assessment: str = Field(min_length=1)
    outcome: ReflectionOutcome
    observations: tuple[str, ...] = Field(default_factory=tuple)
    recommendations: tuple[str, ...] = Field(default_factory=tuple)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("reflection_id", "assessment")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must contain non-whitespace text")
        return value

    @field_validator("observations", "recommendations")
    @classmethod
    def validate_text_items(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("reflection observations and recommendations must be nonblank")
        return values

    @field_validator("metadata")
    @classmethod
    def freeze_metadata(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return freeze_json(value)

    @field_validator("timestamp")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        try:
            is_utc = value.tzinfo is not None and value.utcoffset() == timedelta(0)
        except (OverflowError, TypeError, ValueError):
            is_utc = False
        if not is_utc:
            raise ValueError("timestamp must be a timezone-aware UTC value")
        return value
