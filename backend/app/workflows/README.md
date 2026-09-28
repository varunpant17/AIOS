# Workflow Engine Foundation

A `Plan` describes intended work. A `Workflow` is a separate execution instance derived from a validated plan; it copies the ordered steps and never changes the source `Plan`. `AgentRuntime` executes an agent request, while `WorkflowService` owns persisted step-by-step state for a plan. It does not start an agent or an autonomous loop.

## State and execution

Workflows move from `pending` to `running`, then to `completed`, `failed`, or `cancelled`. During cancellation of an in-flight synchronous step, the status is `cancelling`; that step is allowed to return, is recorded as cancelled, and no later step starts. Between steps cancellation becomes terminal immediately. Steps move from `pending` to `running`, then `completed`, `failed`, or `cancelled`. `WorkflowContext` is an immutable JSON snapshot of inputs, prior outputs, variables, and metadata. Each successful step's output is made available to later steps by its source plan step ID.

Cancellation is resolved at the store's atomic persistence boundary. If cancellation changes the workflow version before a returned step result is committed, the stale result update is rejected; cancellation wins, the running step is recorded as cancelled without a result, and no output is added to context. If step completion commits first, that step remains completed and cancellation applies between steps. A per-store atomic pending-workflow claim prevents separate service instances sharing that store from both starting execution. The store also tracks whether the execution service has emitted `workflow.started`: cancellation before that acknowledgement remains `cancelling`, so the start event is emitted before cancellation can become terminal. Version-checked updates reject stale writes and the store validates status transitions. These guarantees are in-process for `InMemoryWorkflowStore`; a future external store must provide equivalent atomic operations.

`StepExecutor` receives one `WorkflowStep` and the current immutable `WorkflowContext`, then returns a normalized `StepResult`. `DeterministicStepExecutor` is a test-oriented implementation driven by explicit source-step-ID outcomes. Workflow execution is sequential; a failed step stops the workflow and leaves later steps pending. Timestamps are timezone-aware UTC, and domain models reject invalid lifecycle combinations.

## Storage, telemetry, and boundaries

`WorkflowStore` is provider-neutral. `InMemoryWorkflowStore` provides thread-safe create/get/update/delete operations, rejects duplicate and missing IDs, validates domain objects, and returns defensive copies. It is process-local and does not provide durability.

Workflow and step events use the shared provider-neutral observability service. Telemetry contains workflow/plan/step identifiers and statuses, never inputs, outputs, arguments, or plan text. Emission is fail-open. A nested workflow reuses the active run; a standalone workflow operation owns its observability run.

Retries, parallel or DAG scheduling, distributed workers, durable databases, scheduling, human approval, compensation, and automatic replanning are deferred until execution contracts and persistence requirements are established. Future explicit executors can adapt `ToolGateway`; reflection can evaluate completed results later. Multi-agent and A2A coordination should compose workflows through explicit boundaries rather than adding autonomous behavior to this foundation.
