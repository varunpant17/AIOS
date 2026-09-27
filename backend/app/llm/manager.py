from time import perf_counter

from app.llm.exceptions import LLMConfigurationError
from app.llm.interfaces.base_provider import LLMProvider
from app.llm.registry.registry import ProviderRegistry
from app.llm.types import LLMRequest, LLMResponse
from app.observability.interfaces import Observability
from app.observability.safe import operation_run, safe_emit
from app.observability.types import EventType


class LLMManager:
    """Configured AIOS gateway for normalized LLM requests."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        *,
        provider_name: str | None = None,
        registry: ProviderRegistry | None = None,
        observability: Observability | None = None,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._provider_name = provider_name
        self._observability = observability

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
        with operation_run(self._observability, "llm") as operation:
            run_id = operation.run_id
            started = perf_counter()
            metadata = {"model": request.model}
            safe_emit(
                self._observability,
                EventType.LLM_REQUEST,
                "llm",
                run_id=run_id,
                metadata=metadata,
            )
            try:
                if self._provider is not None:
                    response = self._provider.generate(request)
                elif self._registry is None or self._provider_name is None:
                    raise LLMConfigurationError("No LLM provider is configured.")
                else:
                    response = self._registry.get(self._provider_name).generate(request)
            except Exception as exc:
                safe_emit(
                    self._observability,
                    EventType.LLM_FAILED,
                    "llm",
                    run_id=run_id,
                    metadata=metadata,
                    duration_ms=(perf_counter() - started) * 1000,
                    error=exc,
                )
                raise
            safe_emit(
                self._observability,
                EventType.LLM_RESPONSE,
                "llm",
                run_id=run_id,
                metadata={
                    **metadata,
                    "provider": response.provider or self._provider_name or "unknown",
                    "response_model": response.model or request.model,
                    "prompt_tokens": response.prompt_tokens,
                    "completion_tokens": response.completion_tokens,
                    "total_tokens": response.total_tokens,
                },
                duration_ms=(perf_counter() - started) * 1000,
            )
            return response
