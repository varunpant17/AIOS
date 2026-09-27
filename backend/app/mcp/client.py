import asyncio
import json
from collections.abc import Callable
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from contextlib import AbstractContextManager
from threading import RLock
from typing import Any, Protocol

import anyio
from pydantic import ValidationError

from app.mcp.errors import (
    MCPConnectionFailure,
    MCPDiscoveryFailure,
    MCPInvalidResponseFailure,
    MCPInvocationFailure,
    MCPTimeoutFailure,
)
from app.mcp.types import (
    MCPCallResult,
    MCPConnectionState,
    MCPServerConfig,
    MCPToolSpec,
)


class MCPClientPort(Protocol):
    """Synchronous AIOS-facing lifecycle and tool operations."""

    @property
    def state(self) -> MCPConnectionState: ...

    def connect(self) -> None: ...

    def list_tools(self) -> list[MCPToolSpec]: ...

    def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPCallResult: ...

    def close(self) -> None: ...


class SDKStdioMCPClient:
    """Synchronous facade over the official async MCP SDK's stdio client."""

    def __init__(
        self,
        config: MCPServerConfig,
        *,
        client_factory: Callable[[MCPServerConfig], Any] | None = None,
    ) -> None:
        self._config = config
        self._client_factory = client_factory
        self._state = MCPConnectionState.DISCONNECTED
        self._lock = RLock()
        self._portal_context: AbstractContextManager | None = None
        self._portal = None
        self._worker_future: Future | None = None
        self._ready_future: Future | None = None
        self._request_send = None

    @property
    def state(self) -> MCPConnectionState:
        return self._state

    def connect(self) -> None:
        with self._lock:
            if self._state == MCPConnectionState.CONNECTED:
                return
            if self._state == MCPConnectionState.CLOSED:
                raise MCPConnectionFailure("Closed MCP clients cannot be reconnected.")
            self._state = MCPConnectionState.CONNECTING
            try:
                from anyio.from_thread import start_blocking_portal

                self._portal_context = start_blocking_portal(
                    name=f"aios-mcp-{self._config.server_name}"
                )
                self._portal = self._portal_context.__enter__()
                self._ready_future = Future()
                self._worker_future = self._portal.start_task_soon(self._session_worker)
                self._ready_future.result(timeout=self._config.connect_timeout_seconds)
                self._state = MCPConnectionState.CONNECTED
            except FutureTimeoutError as exc:
                self._state = MCPConnectionState.FAILED
                self._shutdown_portal()
                raise MCPTimeoutFailure("MCP connection timed out.") from exc
            except MCPConnectionFailure:
                self._state = MCPConnectionState.FAILED
                self._shutdown_portal()
                raise
            except Exception as exc:
                self._state = MCPConnectionState.FAILED
                self._shutdown_portal()
                raise MCPConnectionFailure("Could not connect to the MCP server.") from exc

    async def _session_worker(self) -> None:
        from mcp import Client, StdioServerParameters

        try:
            if self._client_factory is not None:
                client = self._client_factory(self._config)
            else:
                target = StdioServerParameters(
                    command=self._config.command,
                    args=self._config.args,
                    env=self._config.env or None,
                    cwd=self._config.cwd,
                )
                client = Client(
                    target,
                    read_timeout_seconds=self._config.request_timeout_seconds,
                )

            async with client as session:
                send_channel, receive_channel = anyio.create_memory_object_stream(0)
                self._request_send = send_channel
                if self._ready_future is not None:
                    self._ready_future.set_result(None)
                async with send_channel, receive_channel:
                    async for operation, payload, reply in receive_channel:
                        if operation == "close":
                            reply.set_result(None)
                            break
                        try:
                            if operation == "list_tools":
                                value = await self._list_tools_in_session(session)
                            elif operation == "call_tool":
                                value = await self._call_tool_in_session(
                                    session,
                                    payload["name"],
                                    payload["arguments"],
                                )
                            else:
                                raise MCPInvalidResponseFailure(
                                    "Unknown internal MCP client operation."
                                )
                            reply.set_result(value)
                        except Exception as exc:
                            reply.set_exception(exc)
        except Exception as exc:
            if self._ready_future is not None and not self._ready_future.done():
                self._ready_future.set_exception(exc)
            raise
        finally:
            self._request_send = None

    async def _list_tools_in_session(self, session: Any) -> list[MCPToolSpec]:
        tools: list[MCPToolSpec] = []
        cursor: str | None = None
        while True:
            response = await session.list_tools(cursor=cursor)
            tools.extend(
                MCPToolSpec(
                    name=tool.name,
                    description=tool.description or tool.title or tool.name,
                    input_schema=tool.input_schema,
                    output_schema=tool.output_schema,
                )
                for tool in response.tools
            )
            cursor = response.next_cursor
            if cursor is None:
                return tools

    async def _call_tool_in_session(
        self,
        session: Any,
        name: str,
        arguments: dict[str, Any],
    ) -> MCPCallResult:
        from mcp.types import CallToolResult, TextContent

        response = await session.call_tool(name, arguments)
        if not isinstance(response, CallToolResult):
            raise MCPInvalidResponseFailure("MCP response was not a tool result.")
        if response.is_error:
            return MCPCallResult(is_error=True, error_type="MCPToolError")
        output = response.structured_content
        if output is None:
            text_blocks = [
                content.text
                for content in response.content
                if isinstance(content, TextContent)
            ]
            if len(text_blocks) != len(response.content):
                raise MCPInvalidResponseFailure(
                    "MCP returned non-text content without structured output."
                )
            output = text_blocks[0] if len(text_blocks) == 1 else text_blocks or None
        try:
            output = json.loads(json.dumps(output, allow_nan=False))
        except (TypeError, ValueError) as exc:
            raise MCPInvalidResponseFailure(
                "MCP output is not JSON-compatible."
            ) from exc
        return MCPCallResult(output=output)

    def list_tools(self) -> list[MCPToolSpec]:
        self._require_connected()
        try:
            return self._request(
                "list_tools",
                None,
                timeout=self._config.request_timeout_seconds,
            )
        except MCPTimeoutFailure:
            raise
        except MCPInvalidResponseFailure:
            raise
        except Exception as exc:
            raise MCPDiscoveryFailure("MCP tool discovery failed.") from exc

    def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPCallResult:
        self._require_connected()
        try:
            return self._request(
                "call_tool",
                {"name": name, "arguments": arguments},
                timeout=self._config.request_timeout_seconds,
            )
        except MCPTimeoutFailure:
            raise
        except MCPInvalidResponseFailure:
            raise
        except Exception as exc:
            raise MCPInvocationFailure("MCP tool invocation failed.") from exc

    def _request(self, operation: str, payload: Any, *, timeout: float):
        if self._portal is None:
            raise MCPConnectionFailure("MCP client event loop is unavailable.")
        future = self._portal.start_task_soon(
            self._send_request, operation, payload
        )
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError as exc:
            future.cancel()
            raise MCPTimeoutFailure("MCP request timed out.") from exc
        except MCPInvalidResponseFailure:
            raise
        except Exception as exc:
            if isinstance(exc, TimeoutError):
                raise MCPTimeoutFailure("MCP request timed out.") from exc
            if isinstance(exc, ValidationError):
                raise MCPInvalidResponseFailure(
                    "MCP server returned invalid protocol data."
                ) from exc
            raise

    async def _send_request(self, operation: str, payload: Any):
        if self._request_send is None:
            raise MCPConnectionFailure("MCP session is not available.")
        reply: asyncio.Future = asyncio.get_running_loop().create_future()
        await self._request_send.send((operation, payload, reply))
        return await reply

    def close(self) -> None:
        with self._lock:
            if self._state == MCPConnectionState.CLOSED:
                return
            close_error = None
            if (
                self._state == MCPConnectionState.CONNECTED
                and self._portal is not None
                and self._worker_future is not None
            ):
                try:
                    self._request("close", None, timeout=self._config.request_timeout_seconds)
                    self._worker_future.result(timeout=self._config.request_timeout_seconds)
                except Exception as exc:
                    close_error = exc
            self._shutdown_portal()
            self._state = MCPConnectionState.CLOSED
            if close_error is not None:
                raise MCPConnectionFailure("Could not close the MCP session cleanly.") from close_error

    def _require_connected(self) -> None:
        if self._state != MCPConnectionState.CONNECTED:
            raise MCPConnectionFailure("MCP client is not connected.")

    def _shutdown_portal(self) -> None:
        if self._portal_context is not None:
            try:
                self._portal_context.__exit__(None, None, None)
            finally:
                self._portal_context = None
                self._portal = None
