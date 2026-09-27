from copy import deepcopy
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


class _FrozenDict(dict):
    def _immutable(self, *args, **kwargs):
        raise TypeError("Memory metadata is immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = (
        _immutable
    )

    def __deepcopy__(self, memo):
        return _freeze_json(
            {
                deepcopy(key, memo): deepcopy(value, memo)
                for key, value in dict.items(self)
            }
        )


class _FrozenList(list):
    def _immutable(self, *args, **kwargs):
        raise TypeError("Memory metadata is immutable")

    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = (
        reverse
    ) = sort = __iadd__ = __imul__ = _immutable

    def __deepcopy__(self, memo):
        return _freeze_json([deepcopy(value, memo) for value in list.__iter__(self)])


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        frozen = _FrozenDict()
        dict.update(frozen, {key: _freeze_json(item) for key, item in value.items()})
        return frozen
    if isinstance(value, list):
        frozen = _FrozenList()
        list.extend(frozen, [_freeze_json(item) for item in value])
        return frozen
    return value


class MemoryType(StrEnum):
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"


class MemoryScope(StrEnum):
    GLOBAL = "global"
    USER = "user"
    AGENT = "agent"
    SESSION = "session"
    TASK = "task"


class Memory(BaseModel):
    """An intentionally retained fact or experience, not a conversation message."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always"
    )

    memory_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    content: str = Field(min_length=1)
    memory_type: MemoryType
    scope: MemoryScope
    scope_id: str | None = Field(default=None, min_length=1)
    source: str = Field(min_length=1)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("memory_id", "content", "source")
    @classmethod
    def reject_whitespace_only(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must contain non-whitespace text")
        return value

    @field_validator("scope_id")
    @classmethod
    def reject_empty_scope_id(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("scope_id must contain non-whitespace text")
        return value

    @field_validator("metadata")
    @classmethod
    def freeze_metadata(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return _freeze_json(value)

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
    def validate_scope_and_timestamps(self):
        if self.scope == MemoryScope.GLOBAL and self.scope_id is not None:
            raise ValueError("GLOBAL memory cannot have a scope_id")
        if self.scope != MemoryScope.GLOBAL and self.scope_id is None:
            raise ValueError(f"{self.scope.value} memory requires a scope_id")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")
        return self


class MemoryQuery(BaseModel):
    """Simple deterministic substring and scope/type filters for recall."""

    model_config = ConfigDict(extra="forbid")

    text: str | None = None
    memory_type: MemoryType | None = None
    scope: MemoryScope | None = None
    scope_id: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=10, gt=0)

    @field_validator("text", "scope_id")
    @classmethod
    def reject_blank_optional_filters(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("filter values must contain non-whitespace text")
        return value

    @model_validator(mode="after")
    def validate_scope_filter(self):
        if self.scope == MemoryScope.GLOBAL and self.scope_id is not None:
            raise ValueError("GLOBAL query cannot have a scope_id")
        return self


class MemoryResult(BaseModel):
    query: MemoryQuery
    memories: list[Memory] = Field(default_factory=list)
    result_count: int = Field(ge=0)
