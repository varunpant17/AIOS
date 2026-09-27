from app.core.config import Settings, settings
from app.llm.providers.gemini_provider import GeminiProvider
from app.llm.registry.registry import ProviderRegistry


def create_provider_registry(config: Settings = settings) -> ProviderRegistry:
    """Build the configured provider catalog without creating SDK clients."""
    registry = ProviderRegistry()
    registry.register_factory(
        "google",
        lambda: GeminiProvider(api_key=config.GEMINI_API_KEY),
    )
    return registry
