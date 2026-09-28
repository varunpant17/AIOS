from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from app.observability.interfaces import Observability
from app.observability.safe import operation_run, safe_emit
from app.observability.types import EventError, EventType
from app.reflection.errors import InvalidReflectionError, ReflectorError, ReflectionError
from app.reflection.interfaces import Reflector
from app.reflection.types import ReflectionOutcome, ReflectionResult


class SimpleReflector:
    """Deterministic reflector that packages an explicitly supplied assessment."""

    def __init__(self, *, observability: Observability | None = None) -> None:
        self._observability = observability

    def reflect(
        self,
        assessment: str,
        outcome: ReflectionOutcome,
        *,
        observations: Sequence[str] = (),
        recommendations: Sequence[str] = (),
        context: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ReflectionResult:
        with operation_run(self._observability, "reflection") as operation:
            self._emit(EventType.REFLECTION_STARTED, operation.run_id, {})
            try:
                if not isinstance(assessment, str) or not assessment.strip():
                    raise InvalidReflectionError("Assessment must contain non-whitespace text.")
                if isinstance(observations, (str, bytes)) or isinstance(
                    recommendations, (str, bytes)
                ):
                    raise InvalidReflectionError(
                        "Observations and recommendations must be sequences of text."
                    )
                result_metadata = dict(metadata or {})
                if context is not None:
                    result_metadata["reflection_context"] = context
                result = ReflectionResult(
                    assessment=assessment,
                    outcome=outcome,
                    observations=tuple(observations),
                    recommendations=tuple(recommendations),
                    metadata=result_metadata,
                )
            except ReflectionError as exc:
                self._failed(operation.run_id, exc)
                raise
            except (ValidationError, TypeError, ValueError) as exc:
                error = InvalidReflectionError("Reflection input is invalid.")
                self._failed(operation.run_id, error)
                raise error from exc
            except Exception as exc:
                error = ReflectorError("Result could not be reflected.")
                self._failed(operation.run_id, error)
                raise error from exc
            self._emit(
                EventType.REFLECTION_COMPLETED,
                operation.run_id,
                {"reflection_id": result.reflection_id, "outcome": result.outcome.value},
            )
            return result

    def _emit(self, event_type: EventType, run_id: str | None, metadata: dict[str, Any]) -> None:
        safe_emit(
            self._observability,
            event_type,
            "reflection",
            run_id=run_id,
            metadata=metadata,
        )

    def _failed(self, run_id: str | None, error: Exception) -> None:
        safe_emit(
            self._observability,
            EventType.REFLECTION_FAILED,
            "reflection",
            run_id=run_id,
            metadata={},
            error=EventError(code=type(error).__name__, exception_type=type(error).__name__),
        )
