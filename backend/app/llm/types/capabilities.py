from enum import StrEnum


class LLMCapability(StrEnum):
    TEXT_GENERATION = "text_generation"
    STREAMING = "streaming"
    STRUCTURED_OUTPUT = "structured_output"
    TOOL_CALLING = "tool_calling"
