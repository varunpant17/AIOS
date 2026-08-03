from abc import ABC, abstractmethod

from app.llm.types import LLMRequest, LLMResponse


class LLMProvider(ABC):
    """Contract that every LLM provider must implement."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name."""
        ...

    @abstractmethod
    def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate a response from the language model."""
        ...