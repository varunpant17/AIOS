import json
from time import perf_counter
from typing import Any

from pydantic import BaseModel

from app.tools.exceptions import (
    ToolInputValidationError,
    ToolInvocationError,
    ToolNotFoundError,
)
from app.tools.policy import ToolPolicy
from app.tools.registry import ToolRegistry
from app.tools.types import ToolErrorCode, ToolExecutionContext, ToolResult


class ToolGateway:
    """Validate, authorize, bound, execute, and normalize tool calls."""

    def __init__(
        self,
        registry: ToolRegistry,
        policy: ToolPolicy,
        *,
        max_invocations_per_execution: int = 10,
    ) -> None:
        if max_invocations_per_execution < 1:
            raise ValueError("max_invocations_per_execution must be positive")
        self._registry = registry
        self._policy = policy
        self._max_invocations = max_invocations_per_execution

    def invoke(
        self,
        name: str,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        started = perf_counter()
        try:
            tool = self._registry.get(name)
        except ToolNotFoundError:
            return ToolResult.failed(
                ToolErrorCode.TOOL_NOT_FOUND,
                f"Tool '{name}' is not registered.",
                metadata={"duration_ms": self._duration_ms(started)},
            )

        try:
            validated_arguments = tool.validate_arguments(arguments)
        except ToolInputValidationError as exc:
            return ToolResult.failed(
                ToolErrorCode.INVALID_INPUT,
                "Input does not match the tool's declared schema.",
                cause_type=(
                    type(exc.__cause__).__name__
                    if exc.__cause__
                    else type(exc).__name__
                ),
                metadata={"duration_ms": self._duration_ms(started)},
            )

        try:
            allowed = self._policy.is_allowed(tool.definition, context)
        except Exception as exc:
            return ToolResult.failed(
                ToolErrorCode.FORBIDDEN,
                "Tool authorization could not be verified.",
                cause_type=type(exc).__name__,
                metadata={"duration_ms": self._duration_ms(started)},
            )
        if not allowed:
            return ToolResult.failed(
                ToolErrorCode.FORBIDDEN,
                "This execution is not authorized to use the tool.",
                metadata={"duration_ms": self._duration_ms(started)},
            )

        if not context.reserve_invocation(self._max_invocations):
            return ToolResult.failed(
                ToolErrorCode.INVOCATION_LIMIT,
                "Tool invocation budget exhausted for this execution.",
                metadata={"duration_ms": self._duration_ms(started)},
            )

        try:
            output = tool.execute(validated_arguments, context)
            safe_output = self._json_safe(output)
        except ToolInvocationError as exc:
            return ToolResult.failed(
                exc.code,
                str(exc),
                cause_type=exc.cause_type,
                metadata={"duration_ms": self._duration_ms(started)},
            )
        except Exception as exc:
            return ToolResult.failed(
                ToolErrorCode.EXECUTION_FAILED,
                "Tool execution failed.",
                cause_type=type(exc).__name__,
                metadata={"duration_ms": self._duration_ms(started)},
            )
        return ToolResult.succeeded(
            safe_output,
            metadata={"duration_ms": self._duration_ms(started)},
        )

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        return json.loads(json.dumps(value, allow_nan=False))

    @staticmethod
    def _duration_ms(started: float) -> float:
        return round((perf_counter() - started) * 1000, 3)
