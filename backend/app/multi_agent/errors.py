class MultiAgentError(Exception):
    """Base class for normalized multi-agent boundary failures."""


class InvalidAgentDefinitionError(MultiAgentError):
    pass


class DuplicateAgentError(MultiAgentError):
    pass


class AgentNotFoundError(MultiAgentError):
    pass


class AgentRoutingError(MultiAgentError):
    pass


class InvalidAgentRouteError(AgentRoutingError):
    pass


class MissingAgentCapabilityError(AgentRoutingError):
    pass


class AmbiguousAgentCapabilityError(AgentRoutingError):
    pass


class InvalidAgentTaskError(MultiAgentError):
    pass


class AgentTaskError(MultiAgentError):
    pass


class AgentTaskNotFoundError(AgentTaskError):
    pass


class InvalidAgentMessageError(MultiAgentError):
    pass


class A2ACommunicationError(MultiAgentError):
    pass
