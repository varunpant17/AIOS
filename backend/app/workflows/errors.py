class WorkflowError(Exception):
    """Base class for normalized workflow boundary failures."""


class InvalidWorkflowError(WorkflowError):
    pass


class WorkflowNotFoundError(WorkflowError):
    pass


class DuplicateWorkflowError(WorkflowError):
    pass


class WorkflowExecutionError(WorkflowError):
    pass


class WorkflowConcurrencyError(WorkflowError):
    """Raised when a workflow update is based on a stale stored version."""


class InvalidWorkflowTransitionError(WorkflowError):
    """Raised when a requested store update skips or reverses lifecycle state."""


class WorkflowCancelledError(WorkflowError):
    pass


class StepExecutionError(WorkflowError):
    pass


class WorkflowStoreError(WorkflowError):
    pass
