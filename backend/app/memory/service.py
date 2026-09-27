from typing import Any

from pydantic import ValidationError

from app.memory.errors import (
    InvalidMemoryError,
    InvalidMemoryQueryError,
    MemoryError,
    MemoryStoreError,
)
from app.memory.interfaces import MemoryStore
from app.memory.types import Memory, MemoryQuery, MemoryResult
from app.observability.interfaces import Observability
from app.observability.safe import operation_run, safe_emit
from app.observability.types import EventError, EventType


class MemoryService:
    """Application-facing memory operations over an injected persistence port."""

    def __init__(
        self,
        store: MemoryStore,
        *,
        observability: Observability | None = None,
    ) -> None:
        self._store = store
        self._observability = observability

    def remember(self, memory: Memory | dict[str, Any]) -> Memory:
        with operation_run(self._observability, "memory.store") as operation:
            self._emit(EventType.MEMORY_STORE_STARTED, operation.run_id, {})
            try:
                validated = memory if isinstance(memory, Memory) else Memory.model_validate(memory)
            except (ValidationError, TypeError, ValueError) as exc:
                error = InvalidMemoryError("Memory input is invalid.")
                self._failed(EventType.MEMORY_STORE_FAILED, operation.run_id, {}, error)
                raise error from exc
            metadata = {
                "memory_id": validated.memory_id,
                "memory_type": validated.memory_type.value,
                "scope": validated.scope.value,
            }
            try:
                stored = self._store.create(validated)
            except MemoryError as exc:
                self._failed(EventType.MEMORY_STORE_FAILED, operation.run_id, metadata, exc)
                raise
            except Exception as exc:
                error = MemoryStoreError("Memory could not be stored.")
                self._failed(EventType.MEMORY_STORE_FAILED, operation.run_id, metadata, error)
                raise error from exc
            self._emit(EventType.MEMORY_STORE_COMPLETED, operation.run_id, metadata)
            return stored

    def store(self, memory: Memory | dict[str, Any]) -> Memory:
        """Explicit create alias for callers that prefer store terminology."""
        return self.remember(memory)

    def get(self, memory_id: str) -> Memory:
        metadata = {"memory_id": memory_id if isinstance(memory_id, str) else "invalid"}
        with operation_run(self._observability, "memory.get") as operation:
            self._emit(EventType.MEMORY_GET_STARTED, operation.run_id, metadata)
            try:
                memory = self._store.get(memory_id)
            except MemoryError as exc:
                self._failed(EventType.MEMORY_GET_FAILED, operation.run_id, metadata, exc)
                raise
            except Exception as exc:
                error = MemoryStoreError("Memory could not be retrieved.")
                self._failed(EventType.MEMORY_GET_FAILED, operation.run_id, metadata, error)
                raise error from exc
            self._emit(EventType.MEMORY_GET_COMPLETED, operation.run_id, metadata)
            return memory

    def search(self, query: MemoryQuery | dict[str, Any]) -> MemoryResult:
        with operation_run(self._observability, "memory.search") as operation:
            self._emit(EventType.MEMORY_SEARCH_STARTED, operation.run_id, {})
            try:
                validated = query if isinstance(query, MemoryQuery) else MemoryQuery.model_validate(query)
            except (ValidationError, TypeError, ValueError) as exc:
                error = InvalidMemoryQueryError("Memory query is invalid.")
                self._failed(EventType.MEMORY_SEARCH_FAILED, operation.run_id, {}, error)
                raise error from exc
            telemetry = {
                "memory_type": validated.memory_type.value if validated.memory_type else None,
                "scope": validated.scope.value if validated.scope else None,
                "limit": validated.limit,
            }
            try:
                memories = self._store.search(validated)
            except MemoryError as exc:
                self._failed(EventType.MEMORY_SEARCH_FAILED, operation.run_id, telemetry, exc)
                raise
            except Exception as exc:
                error = MemoryStoreError("Memory search failed.")
                self._failed(EventType.MEMORY_SEARCH_FAILED, operation.run_id, telemetry, error)
                raise error from exc
            self._emit(
                EventType.MEMORY_SEARCH_COMPLETED,
                operation.run_id,
                {**telemetry, "result_count": len(memories)},
            )
            return MemoryResult(query=validated, memories=memories, result_count=len(memories))

    def recall(self, query: MemoryQuery | dict[str, Any]) -> MemoryResult:
        return self.search(query)

    def delete(self, memory_id: str) -> None:
        metadata = {"memory_id": memory_id if isinstance(memory_id, str) else "invalid"}
        with operation_run(self._observability, "memory.delete") as operation:
            self._emit(EventType.MEMORY_DELETE_STARTED, operation.run_id, metadata)
            try:
                self._store.delete(memory_id)
            except MemoryError as exc:
                self._failed(EventType.MEMORY_DELETE_FAILED, operation.run_id, metadata, exc)
                raise
            except Exception as exc:
                error = MemoryStoreError("Memory could not be deleted.")
                self._failed(EventType.MEMORY_DELETE_FAILED, operation.run_id, metadata, error)
                raise error from exc
            self._emit(EventType.MEMORY_DELETE_COMPLETED, operation.run_id, metadata)

    def _emit(
        self, event_type: EventType, run_id: str | None, metadata: dict[str, Any]
    ) -> None:
        safe_emit(
            self._observability,
            event_type,
            "memory",
            run_id=run_id,
            metadata=metadata,
        )

    def _failed(
        self,
        event_type: EventType,
        run_id: str | None,
        metadata: dict[str, Any],
        error: Exception,
    ) -> None:
        safe_emit(
            self._observability,
            event_type,
            "memory",
            run_id=run_id,
            metadata=metadata,
            error=EventError(code=type(error).__name__, exception_type=type(error).__name__),
        )
