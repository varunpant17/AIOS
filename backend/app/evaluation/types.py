from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from math import isfinite
from typing import Any

from pydantic import Field, JsonValue, field_validator, model_validator

from app.core.immutable import ImmutableDomainModel, freeze_json


def _require_utc(value: datetime) -> datetime:
    try:
        valid = value.tzinfo is not None and value.utcoffset() == timedelta(0)
    except (OverflowError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("timestamps must be timezone-aware UTC values")
    return value


class EvaluationCase(ImmutableDomainModel):
    """One stable, caller-identified input/expected-output example."""

    case_id: str = Field(min_length=1)
    input: JsonValue
    expected: JsonValue
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    tags: tuple[str, ...] = ()

    @field_validator("case_id")
    @classmethod
    def validate_case_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("case_id must contain non-whitespace text")
        return value

    @field_validator("input", "expected")
    @classmethod
    def freeze_json_value(cls, value: Any) -> Any:
        return freeze_json(value)

    @field_validator("metadata")
    @classmethod
    def freeze_metadata(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return freeze_json(value)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted({tag.strip() for tag in value}))
        if any(not tag for tag in normalized):
            raise ValueError("tags must contain non-whitespace text")
        return normalized


class EvaluationDataset(ImmutableDomainModel):
    """Immutable, non-empty dataset ordered canonically by case_id."""

    dataset_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    cases: tuple[EvaluationCase, ...] = Field(min_length=1)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("dataset_id", "name")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("dataset identity fields must contain non-whitespace text")
        return value

    @field_validator("cases")
    @classmethod
    def validate_cases(cls, value: tuple[EvaluationCase, ...]) -> tuple[EvaluationCase, ...]:
        cases = tuple(
            case if isinstance(case, EvaluationCase) else EvaluationCase.model_validate(case)
            for case in value
        )
        ids = [case.case_id for case in cases]
        if len(ids) != len(set(ids)):
            raise ValueError("dataset case IDs must be unique")
        return tuple(sorted(cases, key=lambda case: case.case_id))

    @field_validator("metadata")
    @classmethod
    def freeze_metadata(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return freeze_json(value)


class EvaluationResult(ImmutableDomainModel):
    """One normalized judgment; scores use the inclusive [0, 1] range."""

    case_id: str = Field(min_length=1)
    evaluator_id: str = Field(min_length=1)
    passed: bool = Field(strict=True)
    score: float = Field(ge=0.0, le=1.0)
    explanation: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("case_id", "evaluator_id")
    @classmethod
    def validate_ids(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("identifiers must contain non-whitespace text")
        return value

    @field_validator("score", mode="before")
    @classmethod
    def validate_finite_score(cls, value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("score must be a numeric value, not a boolean")
        if not isfinite(value):
            raise ValueError("score must be finite")
        return float(value)

    @field_validator("evaluated_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @field_validator("metadata")
    @classmethod
    def freeze_metadata(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return freeze_json(value)

    @model_validator(mode="after")
    def validate_pass_threshold(self):
        if self.passed != (self.score >= 0.5):
            raise ValueError("passed must be true exactly when score is at least 0.5")
        return self


class EvaluationSummary(ImmutableDomainModel):
    total_cases: int = Field(ge=0)
    passed_cases: int = Field(ge=0)
    failed_cases: int = Field(ge=0)
    pass_rate: float = Field(ge=0.0, le=1.0)
    average_score: float = Field(ge=0.0, le=1.0)

    @field_validator("pass_rate", "average_score")
    @classmethod
    def validate_finite_metrics(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("metrics must be finite")
        return value

    @model_validator(mode="after")
    def validate_counts(self):
        if self.passed_cases + self.failed_cases != self.total_cases:
            raise ValueError("passed and failed counts must sum to total_cases")
        expected_rate = self.passed_cases / self.total_cases if self.total_cases else 0.0
        if self.pass_rate != expected_rate:
            raise ValueError("pass_rate does not match case counts")
        if not self.total_cases and self.average_score != 0.0:
            raise ValueError("average_score must be zero when there are no results")
        return self


class EvaluationRunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EvaluationErrorInfo(ImmutableDomainModel):
    code: str = Field(min_length=1)
    exception_type: str = Field(min_length=1)
    case_id: str | None = None


class EvaluationRun(ImmutableDomainModel):
    """Immutable snapshot for one sequential execution of a dataset."""

    run_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    status: EvaluationRunStatus = EvaluationRunStatus.CREATED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    results: tuple[EvaluationResult, ...] = ()
    summary: EvaluationSummary | None = None
    error: EvaluationErrorInfo | None = None
    version: int = Field(default=0, ge=0)

    @field_validator("run_id", "dataset_id")
    @classmethod
    def validate_ids(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("identifiers must contain non-whitespace text")
        return value

    @field_validator("created_at", "started_at", "completed_at")
    @classmethod
    def validate_timestamps(cls, value: datetime | None) -> datetime | None:
        return _require_utc(value) if value is not None else None

    @field_validator("results")
    @classmethod
    def validate_results(cls, value: tuple[EvaluationResult, ...]) -> tuple[EvaluationResult, ...]:
        results = tuple(
            result if isinstance(result, EvaluationResult) else EvaluationResult.model_validate(result)
            for result in value
        )
        ids = [result.case_id for result in results]
        if len(ids) != len(set(ids)):
            raise ValueError("evaluation run result case IDs must be unique")
        return results

    @model_validator(mode="after")
    def validate_lifecycle(self):
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("started_at cannot precede created_at")
        if self.completed_at is not None:
            lower = self.started_at or self.created_at
            if self.completed_at < lower:
                raise ValueError("completed_at cannot precede started_at")
        if self.status == EvaluationRunStatus.CREATED:
            valid = (self.version == 0 and self.started_at is None and self.completed_at is None
                     and not self.results and self.summary is None and self.error is None)
        elif self.status == EvaluationRunStatus.RUNNING:
            valid = (self.version >= 0 and self.started_at is not None and self.completed_at is None
                     and self.summary is None and self.error is None)
        elif self.status == EvaluationRunStatus.COMPLETED:
            valid = (self.version >= 0 and self.started_at is not None and self.completed_at is not None
                     and self.summary is not None and self.error is None)
        else:
            valid = (self.version >= 0 and self.started_at is not None and self.completed_at is not None
                     and self.summary is not None and self.error is not None)
        if not valid:
            raise ValueError("evaluation run fields do not match its lifecycle status")
        if self.summary is not None and self.summary.total_cases != len(self.results):
            raise ValueError("summary counts must match stored evaluation results")
        if self.summary is not None:
            passed = sum(result.passed for result in self.results)
            failed = len(self.results) - passed
            pass_rate = passed / len(self.results) if self.results else 0.0
            average_score = (
                sum(result.score for result in self.results) / len(self.results)
                if self.results else 0.0
            )
            if (self.summary.passed_cases != passed or self.summary.failed_cases != failed
                    or self.summary.pass_rate != pass_rate
                    or self.summary.average_score != average_score):
                raise ValueError("summary metrics do not match stored results")
        return self

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False):
        if update and self.status in {EvaluationRunStatus.COMPLETED, EvaluationRunStatus.FAILED}:
            raise ValueError("Terminal evaluation runs cannot be copied with updates.")
        if update and "status" in update:
            next_status = EvaluationRunStatus(update["status"])
            allowed = {
                EvaluationRunStatus.CREATED: {EvaluationRunStatus.CREATED, EvaluationRunStatus.RUNNING},
                EvaluationRunStatus.RUNNING: {EvaluationRunStatus.RUNNING, EvaluationRunStatus.COMPLETED,
                                              EvaluationRunStatus.FAILED},
                EvaluationRunStatus.COMPLETED: {EvaluationRunStatus.COMPLETED},
                EvaluationRunStatus.FAILED: {EvaluationRunStatus.FAILED},
            }
            if next_status not in allowed[self.status]:
                raise ValueError(f"Cannot transition run from {self.status.value} to {next_status.value}.")
        return super().model_copy(update=update, deep=deep)
