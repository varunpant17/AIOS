import os
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.core.config import Settings
from app.llm.exceptions import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMRateLimitError,
)
from app.llm.manager import LLMManager
from app.llm.providers.gemini_provider import GeminiProvider
from app.llm.registry.factory import create_provider_registry
from app.llm.registry.registry import ProviderRegistry
from app.llm.types import (
    LLMCapability,
    LLMRequest,
    LLMResponse,
    Message,
    MessageRole,
    StructuredOutputConfig,
)


def make_test_settings(**overrides):
    values = {
        "APP_NAME": "test",
        "APP_VERSION": "0",
        "APP_DESCRIPTION": "test settings",
        "DATABASE_URL": "postgresql+psycopg://test:test@localhost/test",
        "SECRET_KEY": "test-only-secret",
        "ACCESS_TOKEN_EXPIRE_MINUTES": 30,
    }
    values.update(overrides)
    return Settings(**values)


class LLMFoundationTests(unittest.TestCase):
    def setUp(self):
        self.request = LLMRequest(
            model="gemini-test",
            temperature=0.2,
            max_tokens=120,
            messages=[
                Message(role=MessageRole.SYSTEM, content="system prompt"),
                Message(role=MessageRole.USER, content="first"),
                Message(role=MessageRole.ASSISTANT, content="answer"),
                Message(role=MessageRole.USER, content="second"),
            ],
        )

    def test_manager_delegates_to_injected_provider(self):
        provider = Mock()
        provider.provider_name = "fake"
        expected = LLMResponse(content="ok", provider="fake", model="test")
        provider.generate.return_value = expected

        result = LLMManager(provider=provider).generate(self.request)

        self.assertIs(result, expected)
        provider.generate.assert_called_once_with(self.request)

    def test_registry_selects_and_caches_configured_provider(self):
        provider = Mock()
        provider.provider_name = "fake"
        registry = ProviderRegistry()
        factory = Mock(return_value=provider)
        registry.register_factory("fake", factory)
        manager = LLMManager(provider_name="fake", registry=registry)

        manager.generate(self.request)
        manager.generate(self.request)

        factory.assert_called_once_with()
        self.assertIs(registry.get("fake"), provider)

    def test_gemini_preserves_roles_and_normalizes_response(self):
        response = SimpleNamespace(
            text="normalized answer",
            model_version="gemini-version",
            candidates=[SimpleNamespace(finish_reason="STOP")],
            usage_metadata=SimpleNamespace(
                prompt_token_count=11,
                candidates_token_count=4,
                total_token_count=15,
            ),
        )
        client = Mock()
        client.models.generate_content.return_value = response
        provider = GeminiProvider(client=client)

        result = provider.generate(self.request)

        call = client.models.generate_content.call_args.kwargs
        self.assertEqual(call["config"].system_instruction, "system prompt")
        self.assertEqual(
            [content.role for content in call["contents"]],
            ["user", "model", "user"],
        )
        self.assertEqual(
            [content.parts[0].text for content in call["contents"]],
            ["first", "answer", "second"],
        )
        self.assertEqual(result.content, "normalized answer")
        self.assertEqual(result.provider, "google")
        self.assertEqual(result.model, "gemini-version")
        self.assertEqual(result.finish_reason, "stop")
        self.assertEqual(result.total_tokens, 15)
        self.assertIsInstance(result, LLMResponse)

    def test_structured_output_maps_to_gemini_configuration(self):
        client = Mock()
        client.models.generate_content.return_value = SimpleNamespace(
            text="{}", model_version=None, candidates=[], usage_metadata=None
        )
        provider = GeminiProvider(client=client)
        request = self.request.model_copy(
            update={
                "structured_output": StructuredOutputConfig(
                    json_schema={"type": "object"}
                )
            }
        )

        provider.generate(request)

        config = client.models.generate_content.call_args.kwargs["config"]
        self.assertEqual(config.response_mime_type, "application/json")
        self.assertEqual(config.response_json_schema, {"type": "object"})
        self.assertIn(LLMCapability.STRUCTURED_OUTPUT, provider.capabilities)

    def test_provider_errors_are_normalized(self):
        from google.genai.errors import APIError

        for code, expected in (
            (401, LLMAuthenticationError),
            (429, LLMRateLimitError),
        ):
            client = Mock()
            client.models.generate_content.side_effect = APIError(
                code, {"message": "provider detail"}
            )
            with self.subTest(code=code):
                with self.assertRaises(expected):
                    GeminiProvider(client=client).generate(self.request)

    def test_missing_key_fails_only_when_gemini_is_constructed(self):
        registry = create_provider_registry(make_test_settings(GEMINI_API_KEY=None))
        with self.assertRaises(LLMConfigurationError):
            registry.get("google")

        # Importing the gateway and adapter does not construct an SDK client or need a key.
        env = os.environ.copy()
        env.pop("GEMINI_API_KEY", None)
        subprocess.run(
            [
                sys.executable,
                "-c",
                "from app.llm.manager import LLMManager; "
                "from app.llm.providers.gemini_provider import GeminiProvider",
            ],
            check=True,
            env=env,
        )

    def test_contracts_contain_only_provider_neutral_values(self):
        response = LLMResponse(content="text", provider="google")
        self.assertEqual(response.model_dump()["content"], "text")
        self.assertNotIn("google.genai", repr(LLMResponse.model_fields))
        self.assertEqual(self.request.messages[2].role, MessageRole.ASSISTANT)


if __name__ == "__main__":
    unittest.main()
