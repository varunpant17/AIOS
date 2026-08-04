from .base_prompt import SYSTEM_PROMPT


class PromptManager:
    """Manages prompts used by AIOS."""

    def get_system_prompt(self) -> str:
        return SYSTEM_PROMPT