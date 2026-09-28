from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from app.observability.interfaces import Observability
from app.observability.safe import operation_run, safe_emit
from app.observability.types import EventError, EventType
from app.planning.errors import InvalidPlanError, InvalidPlanStepError, PlannerError, PlanningError
from app.planning.interfaces import Planner
from app.planning.types import Plan, PlanStep, PlanStepSpec


class SimplePlanner:
    """Deterministic planner that turns explicit step specifications into a plan."""

    def __init__(self, *, observability: Observability | None = None) -> None:
        self._observability = observability

    def plan(
        self,
        goal: str,
        steps: Sequence[PlanStepSpec | dict[str, Any]],
        *,
        context: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Plan:
        with operation_run(self._observability, "planning") as operation:
            self._emit(EventType.PLANNING_STARTED, operation.run_id, {})
            try:
                if not isinstance(goal, str) or not goal.strip():
                    raise InvalidPlanError("Plan goal must contain non-whitespace text.")
                if isinstance(steps, (str, bytes)):
                    raise InvalidPlanStepError(
                        "Steps must be an ordered sequence of step definitions."
                    )
                try:
                    specs = tuple(
                        item
                        if isinstance(item, PlanStepSpec)
                        else PlanStepSpec.model_validate(item)
                        for item in steps
                    )
                except (ValidationError, TypeError, ValueError) as exc:
                    raise InvalidPlanStepError("One or more plan steps are invalid.") from exc
                plan_metadata = dict(metadata or {})
                if context is not None:
                    plan_metadata["planning_context"] = context
                plan = Plan(
                    goal=goal,
                    steps=tuple(
                        PlanStep(
                            position=position,
                            description=spec.description,
                            action=spec.action,
                            metadata=spec.metadata,
                        )
                        for position, spec in enumerate(specs)
                    ),
                    metadata=plan_metadata,
                )
            except PlanningError as exc:
                self._failed(operation.run_id, exc)
                raise
            except (ValidationError, TypeError, ValueError) as exc:
                error = InvalidPlanError("Plan input is invalid.")
                self._failed(operation.run_id, error)
                raise error from exc
            except Exception as exc:
                error = PlannerError("Plan could not be constructed.")
                self._failed(operation.run_id, error)
                raise error from exc
            self._emit(
                EventType.PLANNING_COMPLETED,
                operation.run_id,
                {
                    "plan_id": plan.plan_id,
                    "step_count": len(plan.steps),
                    "status": plan.status.value,
                },
            )
            return plan

    def _emit(self, event_type: EventType, run_id: str | None, metadata: dict[str, Any]) -> None:
        safe_emit(
            self._observability,
            event_type,
            "planning",
            run_id=run_id,
            metadata=metadata,
        )

    def _failed(self, run_id: str | None, error: Exception) -> None:
        safe_emit(
            self._observability,
            EventType.PLANNING_FAILED,
            "planning",
            run_id=run_id,
            metadata={},
            error=EventError(code=type(error).__name__, exception_type=type(error).__name__),
        )
