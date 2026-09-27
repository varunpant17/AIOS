# Agent Runtime

An AIOS agent is a configured runtime component that can use capabilities through AIOS boundaries. An agent is not the language model itself: `LLMAgent` uses the Phase 1 `LLMManager` and never imports a provider SDK.

```text
Caller -> AgentRuntime -> LLMAgent -> LLMManager -> configured provider
             │
             ├── AgentState -> AgentResult
             └── optional ToolGateway (injected boundary; no tool loop)
```

`AgentDefinition` holds an agent id, name, description, optional model, system instructions, and metadata. `AgentContext` carries one execution's goal, input, conversation, correlation id, metadata, and contextual data. It is transient execution context, not persistent memory.

`AgentState` records execution id, agent id, lifecycle status, step count, messages, result/error, metadata, timestamps, and lifecycle events. Its transition method enforces `created → running → completed|failed|cancelled`. `AgentRuntime.execute()` creates the state, invokes the agent once, records lifecycle events, normalizes success or failure to `AgentResult`, and retains an in-process state snapshot retrievable by execution id. State persistence and autonomous loops are intentionally out of scope.

`LLMAgent` receives an `LLMManager` through constructor injection, converts its definition and context into an `LLMRequest`, and returns generated text. MCP-backed tools can now be exposed through the injected `ToolGateway`; autonomous tool selection and loops remain unimplemented. Retrieval, memory, planning, and workflow execution can be added at the runtime/context boundary without coupling agents to provider SDKs.
