from app.llm.types import LLMRequest, Message, MessageRole
from app.agents.base_agent import BaseAgent
from app.core.config import settings

class ChatAgent(BaseAgent):
    """Simple conversational agent."""

    def run(self, user_input: str) -> str:
        request = LLMRequest(
            model=settings.DEFAULT_LLM_MODEL,
            messages=[
                Message(
                    role=MessageRole.USER,
                    content=user_input,
                )
            ],
        )

        response = self.generate(request)

        return response.content