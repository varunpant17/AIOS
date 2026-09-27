from pydantic import BaseModel


class LLMResponse(BaseModel):
    content: str
    provider: str | None = None
    model: str | None = None
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
