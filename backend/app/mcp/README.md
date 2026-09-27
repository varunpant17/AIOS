# MCP Integration

`app/mcp` connects configured MCP servers to AIOS's existing tool boundary. It is a client and adapter layer; it does not create a second tool registry or let an LLM call a remote server directly.

## Lifecycle

Construct `MCPServerConfig` with a server name and explicit stdio command/arguments, then create `SDKStdioMCPClient`. Its connection is lazy: call `connect()`, then `MCPToolBridge.discover_and_register()` to list remote tools, adapt their schemas, and atomically register them with the shared `ToolRegistry`. Call `close()` when the server is no longer needed. The bridge does not start automatically at application import or startup.

The SDK-backed client keeps the asynchronous MCP session in one worker task while exposing the synchronous port used by `ToolGateway`. The SDK is imported only when connecting, so importing AIOS contracts does not require starting a server. Inject a client factory when writing transport-independent tests.

## Contracts and Safety

`MCPToolSpec` and `MCPCallResult` contain SDK-independent data. Discovered MCP tools become ordinary `BaseTool` adapters with names in the form `server__tool_name`; schema validation occurs before remote invocation. Remote `$ref` schema targets are rejected to avoid fetching untrusted schema URLs. Configure process commands and environment values explicitly, and keep secrets out of checked-in configuration.

Remote calls use the same `ToolGateway` authorization, invocation budget, and JSON-safe result handling as local tools. MCP transport and protocol errors are translated to AIOS tool error codes without returning raw server exception messages. The current implementation supports stdio only; HTTP transports, automatic server discovery, reconnection, and lifecycle integration are not implemented. MCP server tools are remote capabilities and should receive least-privilege credentials and process permissions.
