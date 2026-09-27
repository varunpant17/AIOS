from threading import RLock

from app.observability.types import ObservabilityEvent


class InMemoryEventSink:
    """Thread-safe event sink intended for tests and local development."""

    def __init__(self) -> None:
        self._events: list[ObservabilityEvent] = []
        self._lock = RLock()

    def write(self, event: ObservabilityEvent) -> None:
        with self._lock:
            self._events.append(event)

    @property
    def events(self) -> list[ObservabilityEvent]:
        with self._lock:
            return list(self._events)

    def events_for_run(self, run_id: str) -> list[ObservabilityEvent]:
        with self._lock:
            return [event for event in self._events if event.run_id == run_id]
