from collections.abc import Callable

from app.agents.base_agent import BaseAgent
from app.agents.types import AgentContext, AgentDefinition, AgentEventType
from app.llm.manager import LLMManager
from app.llm.prompts import PromptManager
from app.llm.types import LLMRequest, Message, MessageRole


class LLMAgent(BaseAgent):
    """Single-call LLM agent using the provider-neutral LLM gateway."""

    def __init__(
        self,
        definition: AgentDefinition,
        llm_manager: LLMManager,
    ) -> None:
        super().__init__(definition)
        self._llm_manager = llm_manager
        self._prompt_manager = PromptManager()

    def run(
        self,
        context: AgentContext,
        *,
        event_sink: Callable[[AgentEventType], None] | None = None,
    ) -> str:
        system_instructions = (
            self.definition.system_instructions
            or self._prompt_manager.get_system_prompt()
        )
        messages = [
            Message(role=MessageRole.SYSTEM, content=system_instructions)
        ]
        if context.goal:
            messages.append(
                Message(
                    role=MessageRole.SYSTEM,
                    content=f"Execution goal: {context.goal}",
                )
            )
        messages.extend(context.conversation)
        messages.append(Message(role=MessageRole.USER, content=context.user_input))

        model = self.definition.model
        if model is None:
            from app.core.config import settings

            model = settings.DEFAULT_LLM_MODEL

        if event_sink is not None:
            event_sink(AgentEventType.LLM_INVOKED)
        response = self._llm_manager.generate(
            LLMRequest(model=model, messages=messages)
        )
        return response.content
