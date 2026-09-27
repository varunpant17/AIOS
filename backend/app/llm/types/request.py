from typing import Any

from pydantic import BaseModel, Field

from app.llm.types.message import Message


class StructuredOutputConfig(BaseModel):
    """Provider-neutral JSON output configuration."""

    json_schema: dict[str, Any] | None = None


class LLMRequest(BaseModel):
    messages: list[Message]
    model: str
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0)
    structured_output: StructuredOutputConfig | None = None
