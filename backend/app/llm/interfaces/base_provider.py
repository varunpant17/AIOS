from abc import ABC, abstractmethod

from app.llm.types import LLMRequest, LLMResponse


class BaseLLMProvider(ABC):
    """Base interface for all LLM providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name."""
        pass

    @abstractmethod
    def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate a response from the language model."""
        pass