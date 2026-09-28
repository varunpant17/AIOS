from threading import RLock

from pydantic import ValidationError

from app.agents.base_agent import BaseAgent
from app.agents.types import AgentDefinition
from app.multi_agent.errors import (
    AgentNotFoundError,
    DuplicateAgentError,
    InvalidAgentDefinitionError,
)


class InMemoryAgentRegistry:
    """Thread-safe process-local registry for BaseAgent instances."""

    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}
        self._definitions: dict[str, AgentDefinition] = {}
        self._lock = RLock()

    def register(self, agent: BaseAgent) -> AgentDefinition:
        if not isinstance(agent, BaseAgent):
            raise InvalidAgentDefinitionError("Only BaseAgent instances can be registered.")
        try:
            definition = AgentDefinition.model_validate(agent.definition.model_dump())
        except (ValidationError, AttributeError, TypeError) as exc:
            raise InvalidAgentDefinitionError("Agent definition is invalid.") from exc
        with self._lock:
            if definition.agent_id in self._agents:
                raise DuplicateAgentError(f"Agent '{definition.agent_id}' is already registered.")
            self._agents[definition.agent_id] = agent
            self._definitions[definition.agent_id] = definition.model_copy(deep=True)
            return definition.model_copy(deep=True)

    def unregister(self, agent_id: str) -> None:
        self._validate_id(agent_id)
        with self._lock:
            if agent_id not in self._agents:
                raise AgentNotFoundError(f"Agent '{agent_id}' was not found.")
            del self._agents[agent_id]
            del self._definitions[agent_id]

    def get(self, agent_id: str) -> AgentDefinition:
        self._validate_id(agent_id)
        with self._lock:
            definition = self._definitions.get(agent_id)
            if definition is None:
                raise AgentNotFoundError(f"Agent '{agent_id}' was not found.")
            return definition.model_copy(deep=True)

    def get_agent(self, agent_id: str) -> BaseAgent:
        self._validate_id(agent_id)
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                raise AgentNotFoundError(f"Agent '{agent_id}' was not found.")
            try:
                current_definition = AgentDefinition.model_validate(
                    agent.definition.model_dump()
                )
            except (ValidationError, AttributeError, TypeError) as exc:
                raise InvalidAgentDefinitionError(
                    "Registered agent definition is no longer valid."
                ) from exc
            if current_definition != self._definitions[agent_id]:
                raise InvalidAgentDefinitionError(
                    "Registered agent definition changed after registration."
                )
            return agent

    def list(self) -> tuple[AgentDefinition, ...]:
        with self._lock:
            return tuple(
                self._definitions[agent_id].model_copy(deep=True)
                for agent_id in sorted(self._definitions)
            )

    def find_by_capability(self, capability: str) -> tuple[AgentDefinition, ...]:
        normalized = self._normalize_capability(capability)
        with self._lock:
            return tuple(
                self._definitions[agent_id].model_copy(deep=True)
                for agent_id in sorted(self._definitions)
                if normalized in self._definitions[agent_id].capabilities
            )

    @staticmethod
    def _validate_id(agent_id: str) -> None:
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise InvalidAgentDefinitionError("agent_id must contain non-whitespace text.")

    @staticmethod
    def _normalize_capability(capability: str) -> str:
        if not isinstance(capability, str) or not capability.strip():
            raise InvalidAgentDefinitionError("capability must contain non-whitespace text.")
        return capability.strip().casefold()
