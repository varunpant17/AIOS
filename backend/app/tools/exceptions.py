from app.tools.types import ToolErrorCode


class ToolSystemError(Exception):
    """Base class for tool catalog errors."""


class ToolRegistrationError(ToolSystemError):
    pass


class DuplicateToolError(ToolRegistrationError):
    pass


class ToolNotFoundError(ToolSystemError):
    pass


class ToolInputValidationError(ToolSystemError):
    pass


class ToolInvocationError(ToolSystemError):
    def __init__(
        self,
        code: ToolErrorCode,
        message: str,
        *,
        cause_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.cause_type = cause_type
