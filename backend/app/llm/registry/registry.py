from collections.abc import Callable

from app.llm.exceptions import LLMConfigurationError
from app.llm.interfaces.base_provider import LLMProvider


class ProviderRegistry:
    """Registry for LLM providers."""

    def __init__(self):
        self._providers: dict[str, LLMProvider] = {}
        self._factories: dict[str, Callable[[], LLMProvider]] = {}

    def register(self, provider: LLMProvider) -> None:
        self._providers[provider.provider_name] = provider

    def register_factory(
        self, provider_name: str, factory: Callable[[], LLMProvider]
    ) -> None:
        self._factories[provider_name] = factory

    def get(self, provider_name: str) -> LLMProvider:
        if provider_name not in self._providers and provider_name in self._factories:
            provider = self._factories[provider_name]()
            if provider.provider_name != provider_name:
                raise LLMConfigurationError(
                    f"Provider factory for '{provider_name}' returned "
                    f"'{provider.provider_name}'."
                )
            self.register(provider)
        if provider_name not in self._providers:
            raise LLMConfigurationError(
                f"Provider '{provider_name}' is not configured."
            )

        return self._providers[provider_name]
