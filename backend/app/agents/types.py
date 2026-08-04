from pydantic import BaseModel, Field

from app.llm.types import Message


class AgentContext(BaseModel):
    user_input: str
    conversation: list[Message] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)