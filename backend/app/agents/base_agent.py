from abc import ABC, abstractmethod
from collections.abc import Callable

from app.agents.types import AgentContext, AgentDefinition, AgentEventType


class BaseAgent(ABC):
    """Execution contract for an AIOS agent, independent of its provider."""

    def __init__(self, definition: AgentDefinition) -> None:
        self.definition = definition

    @abstractmethod
    def run(
        self,
        context: AgentContext,
        *,
        event_sink: Callable[[AgentEventType], None] | None = None,
    ) -> str:
        """Run one bounded execution and return its textual output."""
        ...
