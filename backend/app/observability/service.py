from datetime import UTC, datetime
from threading import RLock
from typing import Any

from app.observability.interfaces import EventSink
from app.observability.types import (
    EventError,
    EventType,
    ObservabilityEvent,
    RunContext,
    RunState,
    RunStatus,
    RunTransitionError,
)


class ObservabilityService:
    """Creates provider-neutral runs/events and writes events to an injected sink."""

    def __init__(self, sink: EventSink) -> None:
        self._sink = sink
        self._runs: dict[str, RunState] = {}
        self._lock = RLock()

    @property
    def sink(self) -> EventSink:
        return self._sink

    def start_run(self, metadata: dict[str, Any] | None = None) -> RunContext:
        context = RunContext(metadata=metadata or {})
        with self._lock:
            while context.run_id in self._runs:
                context = RunContext(metadata=metadata or {})
            self._runs[context.run_id] = RunState(context)
        return context

    def get_run(self, run_id: str) -> RunContext:
        with self._lock:
            state = self._runs.get(run_id)
            if state is None:
                raise KeyError(f"Run '{run_id}' was not found.")
        with state.lock:
            return state.context.model_copy(deep=True)

    def emit(
        self,
        event_type: EventType,
        component: str,
        *,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        duration_ms: float | None = None,
        error: Exception | EventError | None = None,
    ) -> ObservabilityEvent:
        if run_id is None:
            from app.observability.context import current_run_id

            run_id = current_run_id()
        if run_id is None:
            raise ValueError("An active or explicit run_id is required to emit an event.")
        with self._lock:
            state = self._runs.get(run_id)
            if state is None:
                raise KeyError(f"Run '{run_id}' was not found.")
        with state.lock:
            if state.context.status != RunStatus.RUNNING:
                raise RunTransitionError(
                    f"Cannot emit events for {state.context.status} run '{run_id}'."
                )
            event = ObservabilityEvent(
                run_id=run_id,
                event_type=event_type,
                component=component,
                metadata=metadata or {},
                duration_ms=duration_ms,
                error=self._event_error(error),
            )
            self._sink.write(event)
        return event

    @staticmethod
    def _event_error(error: Exception | EventError | None) -> EventError | None:
        if error is None:
            return None
        if isinstance(error, EventError):
            return error
        code = getattr(error, "code", type(error).__name__)
        return EventError(code=str(code), exception_type=type(error).__name__)

    def complete_run(self, run_id: str) -> RunContext:
        return self._transition(run_id, RunStatus.COMPLETED)

    def fail_run(
        self, run_id: str, error: Exception | EventError
    ) -> RunContext:
        return self._transition(
            run_id,
            RunStatus.FAILED,
            error=self._event_error(error),
        )

    def cancel_run(self, run_id: str) -> RunContext:
        return self._transition(run_id, RunStatus.CANCELLED)

    def _transition(
        self,
        run_id: str,
        status: RunStatus,
        *,
        error: EventError | None = None,
    ) -> RunContext:
        with self._lock:
            state = self._runs.get(run_id)
            if state is None:
                raise KeyError(f"Run '{run_id}' was not found.")
        with state.lock:
            if state.context.status != RunStatus.RUNNING:
                raise RunTransitionError(
                    f"Cannot transition run from {state.context.status} to {status}."
                )
            state.context = state.context.model_copy(
                update={"status": status, "ended_at": datetime.now(UTC), "error": error}
            )
            return state.context.model_copy(deep=True)
