from collections.abc import Sequence
from typing import Any, Protocol

from app.reflection.types import ReflectionOutcome, ReflectionResult


class Reflector(Protocol):
    """Provider-neutral contract for assessing an existing result."""

    def reflect(
        self,
        assessment: str,
        outcome: ReflectionOutcome,
        *,
        observations: Sequence[str] = (),
        recommendations: Sequence[str] = (),
        context: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ReflectionResult: ...
