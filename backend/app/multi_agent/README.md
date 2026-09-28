# Multi-Agent and A2A Foundation

Phase 10 adds bounded, in-process delegation. `AgentRuntime` still executes one `BaseAgent`; `AgentRegistry` discovers agents and their declared capabilities; `AgentRouter` resolves an explicit ID or a unique capability; `AgentTask` tracks one immutable delegated request; `AgentMessage` is its communication envelope; `A2AChannel` delivers that envelope; and `MultiAgentService` coordinates one delegation through the existing runtime.

```text
MultiAgentService -> AgentRouter -> AgentRegistry
        |                              |
        +-> AgentTask -> A2AChannel -> BaseAgent -> AgentRuntime -> AgentResult
```

Agents are independently configured execution components; tools are callable capabilities an agent may use through `ToolGateway`. An `AgentTask` represents one delegated agent invocation; a `WorkflowStep` is one sequential step in a workflow and is not an agent message or delegation task.

Tasks follow `pending → running → completed|failed`. A task contains an immutable JSON snapshot of its delegated payload, result, and the existing `AgentErrorInfo` when failed.

Capability discovery is exact after case-folding and trimming. Multiple matching agents are an error; the router never chooses arbitrarily. Registry definitions and task/message JSON payloads are immutable snapshots. `AgentTask.result` holds the JSON snapshot of the existing `AgentResult` contract. Task and A2A telemetry contains identifiers, message type, statuses, and version only. The existing `AgentRuntime` owns its own execution and run lifecycle; task/A2A events reuse an enclosing active run or create a standalone operation run.

The registry, task tracking, and in-memory channel are process-local and do not coordinate across processes. A future transport can implement `A2AChannel` and preserve the same envelope contract. Network protocols, distributed discovery/queues, retries, parallel execution, autonomous loops, negotiation, DAG scheduling, compensation, replanning, Reflection orchestration, persistence, and frontend work are deferred.
