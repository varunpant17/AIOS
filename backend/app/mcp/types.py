from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MCPConnectionState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    FAILED = "failed"
    CLOSED = "closed"


class MCPServerConfig(BaseModel):
    """Explicit stdio server configuration; the command is never shell-expanded."""

    model_config = ConfigDict(extra="forbid")

    server_name: str = Field(min_length=1, pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]*$")
    transport: Literal["stdio"] = "stdio"
    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    connect_timeout_seconds: float = Field(default=15, gt=0)
    request_timeout_seconds: float = Field(default=30, gt=0)


class MCPToolSpec(BaseModel):
    """SDK-independent description of an MCP tool discovered on a server."""

    name: str = Field(min_length=1)
    description: str = ""
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_object_schema(self):
        if self.input_schema.get("type") != "object":
            raise ValueError("MCP tool inputSchema must declare an object")
        return self


class MCPCallResult(BaseModel):
    """Provider-neutral subset of an MCP call result."""

    is_error: bool = False
    output: Any = None
    error_type: str | None = None
