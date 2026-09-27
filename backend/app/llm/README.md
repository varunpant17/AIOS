# LLM Foundation

The LLM layer is the infrastructure boundary between AIOS code and provider SDKs. Application and agent code submit normalized requests to `LLMManager`; they do not call Gemini directly.

```text
AIOS caller -> LLMManager -> ProviderRegistry -> LLMProvider adapter -> external model
```

`LLMRequest`, `Message`, `MessageRole`, and `LLMResponse` are provider-neutral Pydantic contracts. Requests preserve system, user, and assistant roles and support common generation controls plus optional JSON schema output. Responses contain text and optional provider/model, finish-reason, and token-usage metadata.

`LLMProvider` defines the adapter contract and a minimal `LLMCapability` set. An adapter advertises only capabilities implemented by its AIOS contract. The current Gemini adapter supports text generation and structured output; streaming and tool calling are not implemented here.

`create_provider_registry()` is the central default provider construction point. The registry stores factories and constructs the configured adapter only when selected. `LLMManager` uses `DEFAULT_LLM_PROVIDER` and permits direct provider or registry injection for tests. Gemini reads `GEMINI_API_KEY` from centralized settings and creates its SDK client only when constructed; importing the adapter does not create a client.

Provider errors are translated into the `LLMError` hierarchy at the adapter boundary. Callers should handle AIOS errors rather than provider-specific exceptions. No agent loop, tool execution, streaming, or multi-provider implementation is included in this phase.
