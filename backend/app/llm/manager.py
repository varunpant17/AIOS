from app.llm.exceptions import LLMConfigurationError
from app.llm.interfaces.base_provider import LLMProvider
from app.llm.registry.registry import ProviderRegistry
from app.llm.types import LLMRequest, LLMResponse


class LLMManager:
    """Configured AIOS gateway for normalized LLM requests."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        *,
        provider_name: str | None = None,
        registry: ProviderRegistry | None = None,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._provider_name = provider_name

        if provider is not None:
            if provider_name is not None and provider_name != provider.provider_name:
                raise LLMConfigurationError(
                    "Injected provider does not match the requested provider name."
                )
            self._provider_name = provider.provider_name
            return

        if self._registry is None:
            from app.core.config import settings
            from app.llm.registry.factory import create_provider_registry

            self._registry = create_provider_registry(settings)
            self._provider_name = provider_name or settings.DEFAULT_LLM_PROVIDER
        elif self._provider_name is None:
            raise LLMConfigurationError(
                "provider_name is required when a registry is injected."
            )

    def generate(self, request: LLMRequest) -> LLMResponse:
        if self._provider is not None:
            return self._provider.generate(request)
        if self._registry is None or self._provider_name is None:
            raise LLMConfigurationError("No LLM provider is configured.")
        return self._registry.get(self._provider_name).generate(request)
