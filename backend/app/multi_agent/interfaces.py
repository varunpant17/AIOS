from typing import Protocol

from app.agents.base_agent import BaseAgent
from app.agents.types import AgentDefinition
from app.multi_agent.types import AgentMessage


class AgentRegistry(Protocol):
    """Provider-neutral discovery and runtime resolution for registered agents."""

    def register(self, agent: BaseAgent) -> AgentDefinition: ...

    def unregister(self, agent_id: str) -> None: ...

    def get(self, agent_id: str) -> AgentDefinition: ...

    def get_agent(self, agent_id: str) -> BaseAgent: ...

    def list(self) -> tuple[AgentDefinition, ...]: ...

    def find_by_capability(self, capability: str) -> tuple[AgentDefinition, ...]: ...


class A2AChannel(Protocol):
    """Provider-neutral delivery contract between registered agents."""

    def send(self, message: AgentMessage) -> None: ...

    def receive(self, recipient_agent_id: str, *, task_id: str) -> AgentMessage: ...
