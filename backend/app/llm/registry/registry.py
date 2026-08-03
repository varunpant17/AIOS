from app.llm.interfaces.base_provider import LLMProvider


class ProviderRegistry:
    """Registry for LLM providers."""

    def __init__(self):
        self._providers: dict[str, LLMProvider] = {}

    def register(self, provider: LLMProvider) -> None:
        self._providers[provider.provider_name] = provider

    def get(self, provider_name: str) -> LLMProvider:
        if provider_name not in self._providers:
            raise ValueError(f"Provider '{provider_name}' is not registered.")

        return self._providers[provider_name]