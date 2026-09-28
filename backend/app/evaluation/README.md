# Evaluation Foundation

Evaluation asks whether a produced behavior or output was acceptable. Tests verify software contracts; observability records what happened during execution. Evaluation consumes caller-supplied outputs and makes deterministic judgments without executing LLMs, agents, tools, RAG, workflows, MCP, or multi-agent systems.

`EvaluationCase` is an immutable, caller-identified input/expected-value pair. Metadata and normalized tags are descriptive and the built-in evaluators ignore them. `EvaluationDataset` is non-empty, rejects duplicate case IDs, and orders cases by ID. JSON inputs, expectations, and metadata are recursively frozen and detached from caller data.

An injected `Evaluator` judges one case and returns an immutable `EvaluationResult`. Scores are finite values in `[0, 1]`; `passed` is true exactly for scores at least `0.5`. `ExactMatchEvaluator` compares canonical JSON values. `ContainsEvaluator` checks string substrings, recursive object subsets, or that every expected list item occurs in the actual list; other JSON scalars use exact equality. `ThresholdEvaluator` treats `expected` as a finite numeric threshold and passes when finite numeric `actual >= expected`; booleans are not numeric inputs.

`Metric` aggregates results. `BasicMetric` reports total, passed, failed, pass rate, and mean score. Empty collections produce zero counts and zero rates/scores. Valid results always have scores, so missing scores cannot enter aggregation.

`EvaluationRun` moves from `created` to `running`, then `completed` or `failed`. The service processes dataset cases sequentially. A judgment with `passed=False` is a valid evaluation outcome and later cases continue. If an evaluator raises or returns an invalid result, the service records a normalized failed result for that case, finalizes the run as failed, and stops; later cases do not run. On this failure path, the summary covers attempted cases, including the failed case. If an injected metric fails, the run fails with a built-in summary so its terminal record remains coherent. UTC timestamps and version-checked store updates protect lifecycle snapshots.

`EvaluationService` accepts a provider-neutral evaluator, metric, store, and optional existing AIOS observability service. Telemetry uses the shared `operation_run` correlation and contains identifiers, outcomes, aggregate counts, and scores, never inputs, expected/actual values, explanations, or arbitrary case metadata. Emission is fail-open.

`InMemoryEvaluationStore` is thread-safe for shared in-process use, but is not durable and does not share state across processes. Future LLM, agent, RAG, workflow, and multi-agent integrations should adapt their outputs into evaluation cases/actuals around this core. LLM-as-a-Judge, external evaluation frameworks, experiment tracking, distributed execution, persistence, dashboards, and adapters are out of scope.
