from abc import ABC, abstractmethod

from app.agents.types import AgentContext
from app.llm.manager import LLMManager
from app.llm.types import LLMRequest, LLMResponse


class BaseAgent(ABC):
    """Base class for all AIOS agents."""

    def __init__(self) -> None:
        self._llm = LLMManager()

    def generate(self, request: LLMRequest) -> LLMResponse:
        return self._llm.generate(request)

    @abstractmethod
    def run(self, context: AgentContext):
        """Execute the agent."""
        ...