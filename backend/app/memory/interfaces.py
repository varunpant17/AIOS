from typing import Protocol

from app.memory.types import Memory, MemoryQuery


class MemoryStore(Protocol):
    """Provider-neutral persistence port for retained memories."""

    def create(self, memory: Memory) -> Memory: ...

    def get(self, memory_id: str) -> Memory: ...

    def delete(self, memory_id: str) -> None: ...

    def search(self, query: MemoryQuery) -> list[Memory]: ...
