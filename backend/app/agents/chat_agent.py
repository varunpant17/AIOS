from app.agents.base_agent import BaseAgent
from app.agents.types import AgentContext
from app.core.config import settings
from app.llm.types import LLMRequest, Message, MessageRole


class ChatAgent(BaseAgent):
    """Simple conversational agent."""

    def run(self, context: AgentContext) -> str:
        request = LLMRequest(
            model=settings.DEFAULT_LLM_MODEL,
            messages=[
                Message(
                    role=MessageRole.USER,
                    content=context.user_input,
                )
            ],
        )

        response = self.generate(request)

        return response.content