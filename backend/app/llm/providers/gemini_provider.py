from google import genai

from app.core.config import settings
from app.llm.interfaces.base_provider import LLMProvider
from app.llm.types import LLMRequest, LLMResponse


class GeminiProvider(LLMProvider):
    """Google Gemini provider implementation."""

    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)

    @property
    def provider_name(self) -> str:
        return "google"

    def generate(self, request: LLMRequest) -> LLMResponse:
        contents = [
            message.content
            for message in request.messages
        ]

        response = self._client.models.generate_content(
            model=request.model,
            contents=contents,
        )

        return LLMResponse(
            content=response.text or "",
        )