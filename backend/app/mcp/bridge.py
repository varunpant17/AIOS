from app.mcp.client import MCPClientPort
from app.mcp.errors import MCPClientError, MCPConnectionFailure, MCPDiscoveryFailure
from app.mcp.types import MCPConnectionState
from app.mcp.adapter import MCPToolAdapter
from app.tools.exceptions import DuplicateToolError
from app.tools.registry import ToolRegistry
from app.tools.types import ToolDefinition
from app.observability.interfaces import Observability


class MCPToolBridge:
    """Explicit connect → discover → adapt → register → close lifecycle."""

    def __init__(
        self,
        server_name: str,
        client: MCPClientPort,
        registry: ToolRegistry,
        *,
        observability: Observability | None = None,
    ) -> None:
        self._server_name = server_name
        self._client = client
        self._registry = registry
        self._observability = observability

    @property
    def state(self) -> MCPConnectionState:
        return self._client.state

    def connect(self) -> None:
        self._client.connect()

    def discover_and_register(self) -> list[ToolDefinition]:
        if self._client.state != MCPConnectionState.CONNECTED:
            raise MCPConnectionFailure("Connect to the MCP server before discovery.")
        try:
            discovered = self._client.list_tools()
            adapters = [
                MCPToolAdapter(
                    self._server_name, tool, self._client, self._observability
                )
                for tool in discovered
            ]
            self._registry.register_many(adapters)
            return [adapter.definition for adapter in adapters]
        except DuplicateToolError:
            raise
        except MCPClientError:
            raise
        except Exception as exc:
            raise MCPDiscoveryFailure("Could not adapt the discovered MCP tools.") from exc

    def close(self) -> None:
        self._client.close()
