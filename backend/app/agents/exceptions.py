class AgentRuntimeError(Exception):
    """Base class for normalized agent runtime failures."""


class AgentInputError(AgentRuntimeError):
    pass


class AgentExecutionError(AgentRuntimeError):
    pass


class AgentLLMError(AgentExecutionError):
    pass


class AgentStateTransitionError(AgentRuntimeError):
    pass
