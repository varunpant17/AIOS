from app.agents.base_agent import BaseAgent
from app.agents.types import AgentContext
from app.core.config import settings
from app.llm.prompts import PromptManager
from app.llm.types import (
    LLMRequest,
    Message,
    MessageRole,
)


class LLMAgent(BaseAgent):
    """Generic LLM-powered agent."""

    def __init__(self) -> None:
        super().__init__()
        self._prompt_manager = PromptManager()

    def run(self, context: AgentContext) -> str:
        messages = [
            Message(
                role=MessageRole.SYSTEM,
                content=self._prompt_manager.get_system_prompt(),
            )
        ]

        messages.extend(context.conversation)

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