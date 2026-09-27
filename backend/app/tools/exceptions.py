class ToolSystemError(Exception):
    """Base class for tool catalog errors."""


class ToolRegistrationError(ToolSystemError):
    pass


class DuplicateToolError(ToolRegistrationError):
    pass


class ToolNotFoundError(ToolSystemError):
    pass
