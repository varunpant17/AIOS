"""Provider-neutral run lifecycle and structured event capture."""

from app.observability.context import bind_run, current_run_id
from app.observability.interfaces import EventSink, Observability
from app.observability.service import ObservabilityService
from app.observability.sinks import InMemoryEventSink
from app.observability.types import (
    EventError,
    EventType,
    ObservabilityEvent,
    RunContext,
    RunStatus,
    RunTransitionError,
)

__all__ = [
    "EventError",
    "EventSink",
    "EventType",
    "InMemoryEventSink",
    "Observability",
    "ObservabilityEvent",
    "ObservabilityService",
    "RunContext",
    "RunStatus",
    "RunTransitionError",
    "bind_run",
    "current_run_id",
]
