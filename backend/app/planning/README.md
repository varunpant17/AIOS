# Planning and Reflection Foundation

Planning answers what work is intended to reach a goal. A `Plan` contains an ordered, validated sequence of `PlanStep` definitions. It is not execution: the planner does not run actions, change agent state, retry work, or orchestrate workflows.

Reflection evaluates an already-produced outcome and returns a structured `ReflectionResult` with an assessment, outcome, observations, and recommendations. It does not execute tools, call a planner, or change workflow or memory state. Planning describes intended work; reflection evaluates results after work has happened.

`Planner` and `Reflector` are provider-neutral protocols. `SimplePlanner` builds a plan from explicit ordered step definitions, while `SimpleReflector` packages an explicitly supplied assessment. These deterministic implementations prove the contracts; neither claims intelligent planning or evaluation. Both use the existing observability system and avoid sending goals, plan content, assessment text, observations, or recommendations in telemetry metadata.

LLM integration is deferred so the domain contracts remain independent of a specific model. These contracts define no chain-of-thought field or reasoning-trace collection; callers should supply concise assessments and observations as structured outputs. The Workflow Engine belongs to Phase 9: it will own execution and state transitions, not these domain capabilities. Future providers may implement the protocols and a later orchestrator may coordinate planning, execution, reflection, memory, or RAG without coupling those concerns into these contracts.

Current limits: plans and reflections are in-memory domain results, not persisted or executed. The simple implementations do no optimization, automatic replanning, extraction, ranking, or multi-agent coordination.
