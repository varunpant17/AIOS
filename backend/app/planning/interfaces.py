from collections.abc import Sequence
from typing import Any, Protocol

from app.planning.types import Plan, PlanStepSpec


class Planner(Protocol):
    """Provider-neutral goal and context to intended-plan contract."""

    def plan(
        self,
        goal: str,
        steps: Sequence[PlanStepSpec | dict[str, Any]],
        *,
        context: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Plan: ...
