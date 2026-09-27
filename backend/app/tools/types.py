from enum import StrEnum
from threading import Lock
from typing import Any

from pydantic import BaseModel, Field, JsonValue, PrivateAttr, model_validator


class ToolErrorCode(StrEnum):
    TOOL_NOT_FOUND = "tool_not_found"
    INVALID_INPUT = "invalid_input"
    FORBIDDEN = "forbidden"
    TIMEOUT = "timeout"
    EXECUTION_FAILED = "execution_failed"
    INVOCATION_LIMIT = "invocation_limit"
    UNSUPPORTED_OPERATION = "unsupported_operation"
    MCP_CONNECTION_FAILED = "mcp_connection_failed"
    MCP_DISCOVERY_FAILED = "mcp_discovery_failed"
    MCP_INVOCATION_FAILED = "mcp_invocation_failed"
    INVALID_MCP_RESPONSE = "invalid_mcp_response"


class ToolDefinition(BaseModel):
    """Provider-neutral tool metadata and JSON schemas."""

    name: str = Field(min_length=1, pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]*$")
    description: str = Field(min_length=1)
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class ToolErrorInfo(BaseModel):
    code: ToolErrorCode
    message: str
    cause_type: str | None = None


class ToolResult(BaseModel):
    """JSON-safe normalized outcome of one tool invocation."""

    success: bool
    output: JsonValue = None
    error: ToolErrorInfo | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_outcome(self):
        if self.success == (self.error is not None):
            raise ValueError("successful results omit error; failures include it")
        return self

    @classmethod
    def succeeded(
        cls,
        output: JsonValue,
        *,
        metadata: dict[str, JsonValue] | None = None,
    ):
        return cls(success=True, output=output, metadata=metadata or {})

    @classmethod
    def failed(
        cls,
        code: ToolErrorCode,
        message: str,
        *,
        cause_type: str | None = None,
        metadata: dict[str, JsonValue] | None = None,
    ):
        return cls(
            success=False,
            error=ToolErrorInfo(code=code, message=message, cause_type=cause_type),
            metadata=metadata or {},
        )


class ToolExecutionContext(BaseModel):
    """Identity and metadata scoped to one execution's tool calls."""

    agent_id: str
    execution_id: str
    user_id: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    _invocation_count: int = PrivateAttr(default=0)
    _counter_lock: Lock = PrivateAttr(default_factory=Lock)

    def reserve_invocation(self, limit: int) -> bool:
        with self._counter_lock:
            if self._invocation_count >= limit:
                return False
            self._invocation_count += 1
            return True
