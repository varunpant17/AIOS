from app.agents.types import AgentDefinition
from app.multi_agent.errors import (
    AgentNotFoundError,
    AmbiguousAgentCapabilityError,
    InvalidAgentRouteError,
    MissingAgentCapabilityError,
)
from app.multi_agent.interfaces import AgentRegistry


class AgentRouter:
    """Deterministic resolver for explicit IDs or unique capabilities."""

    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    def resolve(
        self, *, agent_id: str | None = None, capability: str | None = None
    ) -> AgentDefinition:
        if (agent_id is None) == (capability is None):
            raise InvalidAgentRouteError(
                "Provide exactly one target agent_id or capability."
            )
        if agent_id is not None:
            try:
                return self._registry.get(agent_id)
            except AgentNotFoundError as exc:
                raise AgentNotFoundError(f"Target agent '{agent_id}' was not found.") from exc
        matches = self._registry.find_by_capability(capability or "")
        if not matches:
            raise MissingAgentCapabilityError(
                f"No registered agent provides capability '{capability}'."
            )
        if len(matches) > 1:
            raise AmbiguousAgentCapabilityError(
                f"Capability '{capability}' matches multiple agents."
            )
        return matches[0]
