# Tool System

A tool is an explicitly registered capability that executes validated inputs under an agent execution context. The LLM may describe or request a tool in a future phase; it never executes a Python callable itself.

```text
AgentRuntime -> ToolGateway -> ToolRegistry -> ToolDefinition / BaseTool
                    │
                    ├── Pydantic input validation
                    ├── ToolPolicy (deny unless allowlisted)
                    ├── per-execution invocation budget
                    └── normalized JSON-safe ToolResult
```

`ToolDefinition` publishes a provider-neutral name, description, JSON input schema, optional output schema, and metadata. `BaseTool` declares its Pydantic input model and executes with validated arguments plus `ToolExecutionContext`. Definitions can later be mapped to LLM function schemas without provider SDK types.

`ToolRegistry` performs explicit registration, rejects duplicate names, resolves tools, and lists definitions. `ToolGateway` reserves the execution-scoped invocation budget, resolves the tool, validates arguments, consults the injected `ToolPolicy`, executes, and normalizes output. `AllowListToolPolicy` denies tools and agents unless explicitly allowed. Failures use `ToolResult` and `ToolErrorInfo`; internal exception messages and non-JSON outputs are not returned to callers.

`AgentRuntime` accepts an optional `ToolGateway` through dependency injection, establishing the boundary without running an autonomous tool loop. This phase does not enforce wall-clock timeouts because Python cannot safely stop an arbitrary synchronous tool once it is running; tools must remain bounded. Phase 4 can add MCP-backed `BaseTool` adapters through the same explicit registry.

The pre-existing untracked `tool_manager.py` is a basic in-memory name map: it supports register/get/list but silently overwrites duplicate names and has no validation, policy, execution, or result normalization. It remains unchanged and is not imported because committed code must not depend on an untracked file.
