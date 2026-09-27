from typing import Any, Protocol

from app.observability.types import EventError, EventType, ObservabilityEvent, RunContext


class EventSink(Protocol):
    """Destination for provider-neutral AIOS events."""

    def write(self, event: ObservabilityEvent) -> None: ...


class Observability(Protocol):
    """Application-level run lifecycle and event interface."""

    def start_run(self, metadata: dict[str, Any] | None = None) -> RunContext: ...

    def emit(
        self,
        event_type: EventType,
        component: str,
        *,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        duration_ms: float | None = None,
        error: Exception | EventError | None = None,
    ) -> ObservabilityEvent: ...

    def complete_run(self, run_id: str) -> RunContext: ...

    def fail_run(
        self, run_id: str, error: Exception | EventError
    ) -> RunContext: ...

    def cancel_run(self, run_id: str) -> RunContext: ...
