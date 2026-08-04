from app.agents.base_agent import BaseAgent
from app.agents.types import AgentContext
from app.core.config import settings
from app.llm.types import LLMRequest, Message, MessageRole


class LLMAgent(BaseAgent):
    """Generic LLM-powered agent."""

    def run(self, context: AgentContext) -> str:
        messages = list(context.conversation)

        messages.append(
            Message(
                role=MessageRole.USER,
                content=context.user_input,
            )
        )

        request = LLMRequest(
            model=settings.DEFAULT_LLM_MODEL,
            messages=messages,
        )

        response = self.generate(request)

        return response.content