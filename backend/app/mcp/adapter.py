import re
from typing import Any

from jsonschema import ValidationError as JSONSchemaValidationError
from jsonschema.validators import validator_for
from pydantic import BaseModel, RootModel

from app.mcp.client import MCPClientPort
from app.mcp.errors import (
    MCPClientError,
    MCPConnectionFailure,
    MCPDiscoveryFailure,
    MCPInvalidResponseFailure,
    MCPInvocationFailure,
    MCPTimeoutFailure,
)
from app.mcp.types import MCPCallResult, MCPToolSpec
from app.tools.base_tool import BaseTool
from app.tools.exceptions import ToolInputValidationError, ToolInvocationError
from app.tools.types import ToolDefinition, ToolErrorCode, ToolExecutionContext


class MCPArguments(RootModel[dict[str, Any]]):
    """Pydantic envelope for arguments additionally checked against MCP JSON Schema."""


class MCPToolAdapter(BaseTool):
    """Expose one discovered remote MCP tool as an ordinary AIOS BaseTool."""

    def __init__(
        self,
        server_name: str,
        tool: MCPToolSpec,
        client: MCPClientPort,
    ) -> None:
        self._server_name = server_name
        self._remote_tool = tool
        self._client = client
        normalized_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", tool.name)
        self._aios_name = f"{server_name}__{normalized_name}"
        if tool.input_schema.get("type") != "object":
            raise MCPInvalidResponseFailure(
                f"MCP tool '{tool.name}' input schema is not an object schema."
            )
        _check_local_refs_only(tool.input_schema)
        try:
            validator_for(tool.input_schema).check_schema(tool.input_schema)
        except Exception as exc:
            raise MCPInvalidResponseFailure(
                f"MCP tool '{tool.name}' published an invalid input schema."
            ) from exc

    @property
    def name(self) -> str:
        return self._aios_name

    @property
    def description(self) -> str:
        return self._remote_tool.description or self._remote_tool.name

    @property
    def input_model(self) -> type[BaseModel]:
        return MCPArguments

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=self._remote_tool.input_schema,
            output_schema=self._remote_tool.output_schema,
            metadata={
                "mcp_server": self._server_name,
                "mcp_tool": self._remote_tool.name,
            },
        )

    def validate_arguments(self, arguments: dict[str, Any]) -> BaseModel:
        try:
            validator_for(self._remote_tool.input_schema)(
                self._remote_tool.input_schema
            ).validate(arguments)
            return MCPArguments.model_validate(arguments)
        except JSONSchemaValidationError as exc:
            raise ToolInputValidationError(
                "Tool input failed the MCP-declared schema."
            ) from exc
        except Exception as exc:
            if isinstance(exc, ToolInputValidationError):
                raise
            raise ToolInputValidationError(
                "Tool input failed the MCP-declared schema."
            ) from exc

    def execute(
        self,
        arguments: BaseModel,
        context: ToolExecutionContext,
    ) -> Any:
        if not isinstance(arguments, MCPArguments):
            raise ToolInvocationError(
                ToolErrorCode.INVALID_INPUT,
                "MCP adapter received an invalid argument envelope.",
            )
        try:
            response = self._client.call_tool(
                self._remote_tool.name,
                arguments.root,
            )
        except MCPConnectionFailure as exc:
            raise ToolInvocationError(
                ToolErrorCode.MCP_CONNECTION_FAILED,
                "MCP server is not connected.",
                cause_type=type(exc).__name__,
            ) from exc
        except MCPTimeoutFailure as exc:
            raise ToolInvocationError(
                ToolErrorCode.TIMEOUT,
                "MCP tool invocation timed out.",
                cause_type=type(exc).__name__,
            ) from exc
        except MCPInvocationFailure as exc:
            raise ToolInvocationError(
                ToolErrorCode.MCP_INVOCATION_FAILED,
                "MCP server could not invoke the requested tool.",
                cause_type=type(exc).__name__,
            ) from exc
        except MCPInvalidResponseFailure as exc:
            raise ToolInvocationError(
                ToolErrorCode.INVALID_MCP_RESPONSE,
                "MCP server returned an invalid response.",
                cause_type=type(exc).__name__,
            ) from exc
        except MCPDiscoveryFailure as exc:
            raise ToolInvocationError(
                ToolErrorCode.MCP_DISCOVERY_FAILED,
                "MCP tool catalog is unavailable.",
                cause_type=type(exc).__name__,
            ) from exc
        except MCPClientError as exc:
            raise ToolInvocationError(
                ToolErrorCode.MCP_INVOCATION_FAILED,
                "MCP request failed.",
                cause_type=type(exc).__name__,
            ) from exc

        if not isinstance(response, MCPCallResult):
            raise ToolInvocationError(
                ToolErrorCode.INVALID_MCP_RESPONSE,
                "MCP client returned an invalid result contract.",
            )
        if response.is_error:
            raise ToolInvocationError(
                ToolErrorCode.MCP_INVOCATION_FAILED,
                "MCP server reported that tool execution failed.",
                cause_type=response.error_type or "MCPToolError",
            )
        return response.output


def _check_local_refs_only(schema: dict[str, Any]) -> None:
    """Reject schemas that could cause validation to fetch remote references."""
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "$ref" and isinstance(value, str) and not value.startswith("#"):
                raise MCPInvalidResponseFailure(
                    "Remote MCP schema references are not supported."
                )
            _check_local_refs_only(value)
    elif isinstance(schema, list):
        for value in schema:
            _check_local_refs_only(value)
