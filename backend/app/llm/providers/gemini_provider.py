from typing import Any

from google import genai
from google.genai import errors, types

from app.llm.exceptions import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMInvalidRequestError,
    LLMProviderResponseError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.llm.interfaces.base_provider import LLMProvider
from app.llm.types import LLMCapability, LLMRequest, LLMResponse, MessageRole


class GeminiProvider(LLMProvider):
    """Translate AIOS contracts to and from the Google GenAI API."""

    def __init__(self, api_key: str | None = None, client: Any | None = None) -> None:
        if client is None:
            if not api_key:
                raise LLMConfigurationError("GEMINI_API_KEY is required for Gemini.")
            client = genai.Client(api_key=api_key)
        self._client = client

    @property
    def provider_name(self) -> str:
        return "google"

    @property
    def capabilities(self) -> frozenset[LLMCapability]:
        return frozenset(
            {LLMCapability.TEXT_GENERATION, LLMCapability.STRUCTURED_OUTPUT}
        )

    def generate(self, request: LLMRequest) -> LLMResponse:
        system_parts = [
            message.content
            for message in request.messages
            if message.role == MessageRole.SYSTEM
        ]
        contents = [
            types.Content(
                role="model" if message.role == MessageRole.ASSISTANT else "user",
                parts=[types.Part.from_text(text=message.content)],
            )
            for message in request.messages
            if message.role != MessageRole.SYSTEM
        ]

        config_values: dict[str, Any] = {}
        if system_parts:
            config_values["system_instruction"] = "\n\n".join(system_parts)
        if request.temperature is not None:
            config_values["temperature"] = request.temperature
        if request.max_tokens is not None:
            config_values["max_output_tokens"] = request.max_tokens
        if request.structured_output is not None:
            config_values["response_mime_type"] = "application/json"
            if request.structured_output.json_schema is not None:
                config_values["response_json_schema"] = (
                    request.structured_output.json_schema
                )

        try:
            response = self._client.models.generate_content(
                model=request.model,
                contents=contents,
                config=types.GenerateContentConfig(**config_values),
            )
        except errors.APIError as exc:
            raise self._normalize_api_error(exc) from exc
        except TimeoutError as exc:
            raise LLMTimeoutError("Gemini request timed out.") from exc
        except Exception as exc:
            # Network/transport errors from the SDK are not all APIError subclasses.
            if isinstance(exc, (ConnectionError,)) or "timeout" in type(exc).__name__.lower():
                raise LLMProviderUnavailableError("Gemini is unavailable.") from exc
            raise LLMProviderResponseError("Gemini request failed.") from exc

        try:
            usage = getattr(response, "usage_metadata", None)
            candidate = response.candidates[0] if response.candidates else None
            finish_reason = candidate.finish_reason if candidate else None
            return LLMResponse(
                content=response.text or "",
                provider=self.provider_name,
                model=getattr(response, "model_version", None) or request.model,
                finish_reason=self._enum_value(finish_reason),
                prompt_tokens=getattr(usage, "prompt_token_count", None),
                completion_tokens=getattr(usage, "candidates_token_count", None),
                total_tokens=getattr(usage, "total_token_count", None),
            )
        except Exception as exc:
            raise LLMProviderResponseError(
                "Gemini returned a response AIOS could not normalize."
            ) from exc

    @staticmethod
    def _enum_value(value: Any) -> str | None:
        if value is None:
            return None
        return str(getattr(value, "name", value)).lower()

    @staticmethod
    def _normalize_api_error(exc: errors.APIError):
        code = getattr(exc, "code", None)
        if code in (401, 403):
            return LLMAuthenticationError("Gemini rejected the configured credentials.")
        if code == 400:
            return LLMInvalidRequestError("Gemini rejected the generation request.")
        if code == 429:
            return LLMRateLimitError("Gemini rate limit exceeded.")
        if code == 504:
            return LLMTimeoutError("Gemini request timed out.")
        if code is not None and code >= 500:
            return LLMProviderUnavailableError("Gemini is temporarily unavailable.")
        return LLMProviderResponseError("Gemini returned an API error.")
