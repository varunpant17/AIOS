from app.core.config import settings
from app.llm.providers import GeminiProvider
from app.llm.registry.registry import ProviderRegistry
from app.llm.types import LLMRequest, LLMResponse


class LLMManager:
    """Manages LLM providers and request execution."""

    def __init__(self) -> None:
        self._registry = ProviderRegistry()

        self._registry.register(
            GeminiProvider()
        )

    def generate(self, request: LLMRequest) -> LLMResponse:
        provider = self._registry.get(
            settings.DEFAULT_LLM_PROVIDER
        )

        return provider.generate(request)