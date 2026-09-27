class LLMError(Exception):
    """Base class for errors exposed by the AIOS LLM boundary."""


class LLMConfigurationError(LLMError):
    pass


class LLMAuthenticationError(LLMError):
    pass


class LLMInvalidRequestError(LLMError):
    pass


class LLMProviderUnavailableError(LLMError):
    pass


class LLMTimeoutError(LLMProviderUnavailableError):
    pass


class LLMRateLimitError(LLMProviderUnavailableError):
    pass


class LLMProviderResponseError(LLMError):
    pass


class LLMUnsupportedCapabilityError(LLMError):
    pass
