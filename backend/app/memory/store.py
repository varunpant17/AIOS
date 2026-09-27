from threading import RLock

from pydantic import ValidationError

from app.memory.errors import (
    DuplicateMemoryError,
    InvalidMemoryError,
    InvalidMemoryQueryError,
    MemoryNotFoundError,
)
from app.memory.interfaces import MemoryStore
from app.memory.types import Memory, MemoryQuery


class InMemoryMemoryStore:
    """Thread-safe in-process store with case-insensitive substring search."""

    def __init__(self) -> None:
        self._memories: dict[str, Memory] = {}
        self._lock = RLock()

    def create(self, memory: Memory) -> Memory:
        if not isinstance(memory, Memory):
            raise InvalidMemoryError("MemoryStore accepts validated Memory objects.")
        try:
            memory = Memory.model_validate(memory)
        except ValidationError as exc:
            raise InvalidMemoryError("Memory object no longer satisfies its contract.") from exc
        with self._lock:
            if memory.memory_id in self._memories:
                raise DuplicateMemoryError(
                    f"Memory '{memory.memory_id}' already exists."
                )
            stored = memory.model_copy(deep=True)
            self._memories[memory.memory_id] = stored
            return stored.model_copy(deep=True)

    def get(self, memory_id: str) -> Memory:
        self._validate_id(memory_id)
        with self._lock:
            memory = self._memories.get(memory_id)
            if memory is None:
                raise MemoryNotFoundError(f"Memory '{memory_id}' was not found.")
            return memory.model_copy(deep=True)

    def delete(self, memory_id: str) -> None:
        self._validate_id(memory_id)
        with self._lock:
            if memory_id not in self._memories:
                raise MemoryNotFoundError(f"Memory '{memory_id}' was not found.")
            del self._memories[memory_id]

    def search(self, query: MemoryQuery) -> list[Memory]:
        if not isinstance(query, MemoryQuery):
            raise InvalidMemoryQueryError("MemoryStore requires a validated MemoryQuery.")
        text = query.text.casefold() if query.text is not None else None
        with self._lock:
            matches = [
                memory
                for memory in self._memories.values()
                if (text is None or text in memory.content.casefold())
                and (query.memory_type is None or memory.memory_type == query.memory_type)
                and (query.scope is None or memory.scope == query.scope)
                and (query.scope_id is None or memory.scope_id == query.scope_id)
            ]
            matches.sort(key=lambda item: (item.created_at, item.memory_id))
            return [item.model_copy(deep=True) for item in matches[: query.limit]]

    @staticmethod
    def _validate_id(memory_id: str) -> None:
        if not isinstance(memory_id, str) or not memory_id.strip():
            raise InvalidMemoryError("memory_id must contain non-whitespace text.")
