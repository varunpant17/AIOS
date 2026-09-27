# AIOS Memory Foundation

Memory is information intentionally retained from an interaction or task. A `Memory` is not a conversation message or a conversation-history buffer. Memory is separate from RAG: RAG finds relevant external knowledge; Memory recalls retained information from prior state or experience. Phase 7 does not combine the two.

## Memory Types and Scope

- **Working** (`WORKING`): temporary task or session state.
- **Episodic** (`EPISODIC`): a retained record of an event or completed task.
- **Semantic** (`SEMANTIC`): an intentionally retained fact or preference.

Every record also declares a scope: `GLOBAL`, `USER`, `AGENT`, `SESSION`, or `TASK`. Non-global scopes require a `scope_id`; global records do not have one. These are explicit ownership boundaries, not automatic memory policies.

`Memory` fields are frozen after construction, and the store defensively copies metadata on write and read. `created_at` and `updated_at` must be timezone-aware UTC timestamps with a zero UTC offset; naive timestamps and non-zero offsets are rejected rather than converted.

## Architecture

```text
Application / Agent
        |
        v
  MemoryService
        |
        v
   MemoryStore protocol
        |
        v
InMemoryMemoryStore (current provider)
```

`MemoryService` owns the application API and operation semantics; the injected store owns persistence. A future persistent provider can implement `MemoryStore` without changing the service or domain models. The subsystem has no dependency on agents, LLMs, MCP, RAG, embeddings, or vector databases.

## Current Capabilities and Limits

The current provider supports create, get, delete, and deterministic case-insensitive substring search with optional type/scope filters. It returns defensive copies, rejects duplicate IDs and missing records explicitly, and orders matches by creation time then memory ID. Memory operations emit provider-neutral events through the existing observability interface; raw memory/query content is excluded from event metadata, and telemetry remains fail-open.

Storage is process-local and non-durable. Search is literal substring/filter matching, not semantic search. This phase does not extract memories automatically, update records, summarize, consolidate, forget, score importance, manage conversation history, or orchestrate memory with RAG. Future extension points include persistent `MemoryStore` adapters and replaceable search strategies, while keeping embeddings and provider-specific details outside the domain model.
