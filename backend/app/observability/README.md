# Observability Foundation

An AIOS **run** is one execution boundary with a unique `run_id`, start/end timestamps, status, and safe metadata. An **event** is a timestamped fact within that run, such as `agent.started`, `llm.request`, `tool.completed`, or `mcp.failed`; each event carries the same `run_id` for correlation.

Observability describes structured execution behavior for querying and analysis. Application logging remains the place for operational diagnostics and human-readable messages; event metadata deliberately excludes prompt text, tool arguments, and outputs by default.

`ObservabilityService` implements the `Observability` protocol and writes provider-neutral Pydantic events to an injected `EventSink`. `InMemoryEventSink` supports local development and tests. Consumers receive the protocol, not a vendor client, so an OpenTelemetry, Langfuse, database, or log-backed sink can be added by implementing `EventSink` without changing `AgentRuntime`, `LLMManager`, or `ToolGateway`.

Correlated execution requires injecting the **same `ObservabilityService` instance** into every participating boundary:

```text
ObservabilityService(sink)
  ├── AgentRuntime
  ├── LLMManager
  ├── ToolGateway
  └── MCPToolBridge → discovered MCPToolAdapter instances
```

`AgentRuntime` starts and finishes the parent run. LLM, tool, and MCP calls reuse its active run context. Standalone calls create and finish their own runs only when no run is active. A standalone tool/MCP call that returns a normalized failure records its failed event and marks its owned run failed. A nested failure records the component event but leaves the parent run's status to `AgentRuntime`.

Telemetry is **fail-open**: AIOS boundaries catch and log observability failures and continue the underlying operation. The current sink interface is synchronous, so a slow sink can still block the AIOS call. Any future external sink must be designed with bounded, nonblocking writes; asynchronous queues and exporters are not part of this phase. The in-memory sink and run registry are process-local and are not durable or cross-process.

`ContextVar` values flow into asyncio tasks and `asyncio.to_thread` calls by default. A raw thread or executor without copied context does not inherit its parent's run; an instrumented standalone component then starts a separate run. Background work that inherits a context but outlives its run can have later events rejected after the parent becomes terminal.
