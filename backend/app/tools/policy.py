from typing import Protocol

from app.tools.types import ToolDefinition, ToolExecutionContext


class ToolPolicy(Protocol):
    """Authorization boundary consulted before every tool execution."""

    def is_allowed(
        self,
        definition: ToolDefinition,
        context: ToolExecutionContext,
    ) -> bool: ...


class AllowListToolPolicy:
    """Deny by default unless both tool and optional agent are allowlisted."""

    def __init__(
        self,
        allowed_tools: set[str] | frozenset[str],
        *,
        allowed_agents: set[str] | frozenset[str] | None = None,
    ) -> None:
        self._allowed_tools = frozenset(allowed_tools)
        self._allowed_agents = (
            frozenset(allowed_agents) if allowed_agents is not None else None
        )

    def is_allowed(
        self,
        definition: ToolDefinition,
        context: ToolExecutionContext,
    ) -> bool:
        return definition.name in self._allowed_tools and (
            self._allowed_agents is None or context.agent_id in self._allowed_agents
        )
