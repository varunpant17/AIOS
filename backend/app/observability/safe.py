import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from app.observability.interfaces import Observability
from app.observability.context import bind_run, current_run_id
from app.observability.types import EventError, EventType, RunContext

logger = logging.getLogger(__name__)


def safe_start_run(
    observability: Observability | None, metadata: dict[str, Any] | None = None
) -> RunContext | None:
    if observability is None:
        return None
    try:
        return observability.start_run(metadata)
    except Exception:
        logger.exception("Observability could not start an AIOS run; continuing.")
        return None


def safe_emit(
    observability: Observability | None,
    event_type: EventType,
    component: str,
    *,
    run_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    duration_ms: float | None = None,
    error: Exception | EventError | None = None,
) -> None:
    if observability is None:
        return
    try:
        observability.emit(
            event_type,
            component,
            run_id=run_id,
            metadata=metadata,
            duration_ms=duration_ms,
            error=error,
        )
    except Exception:
        logger.exception("Observability event emission failed; continuing.")


def safe_complete_run(observability: Observability | None, run_id: str) -> None:
    if observability is None:
        return
    try:
        observability.complete_run(run_id)
    except Exception:
        logger.exception("Observability could not complete an AIOS run; continuing.")


def safe_fail_run(
    observability: Observability | None,
    run_id: str,
    error: Exception | EventError,
) -> None:
    if observability is None:
        return
    try:
        observability.fail_run(run_id, error)
    except Exception:
        logger.exception("Observability could not fail an AIOS run; continuing.")


@dataclass
class OperationRun:
    run_id: str | None
    observability: Observability | None
    owns_run: bool = False
    failed: bool = False

    def fail(self, error: Exception | EventError) -> None:
        if self.owns_run and self.run_id is not None and not self.failed:
            safe_fail_run(self.observability, self.run_id, error)
            self.failed = True


@contextmanager
def operation_run(observability: Observability | None, component: str):
    """Reuse an enclosing run or create a run for a standalone component call."""
    active = current_run_id()
    if active is not None or observability is None:
        yield OperationRun(active, observability)
        return
    run = safe_start_run(observability, {"entry_component": component})
    if run is None:
        yield OperationRun(None, observability)
        return
    operation = OperationRun(run.run_id, observability, owns_run=True)
    try:
        with bind_run(run):
            yield operation
    except Exception as exc:
        operation.fail(exc)
        raise
    else:
        if not operation.failed:
            safe_complete_run(observability, run.run_id)
