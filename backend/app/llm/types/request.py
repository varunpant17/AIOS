from app.llm.types.message import Message
from pydantic import BaseModel


class LLMRequest(BaseModel):
    model: str
    messages: list[Message]