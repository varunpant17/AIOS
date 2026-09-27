from datetime import UTC, datetime
from uuid import uuid4

from app.agents.base_agent import BaseAgent
from app.agents.exceptions import (
    AgentExecutionError,
    AgentInputError,
    AgentLLMError,
)
from app.agents.types import (
    AgentContext,
    AgentErrorInfo,
    AgentEvent,
    AgentEventType,
    AgentExecutionStatus,
    AgentResult,
    AgentState,
)
from app.llm.exceptions import LLMError
from app.llm.types import Message, MessageRole
from app.tools.gateway import ToolGateway


class AgentRuntime:
    """Owns synchronous execution lifecycle and in-process state tracking."""

    def __init__(self, tool_gateway: ToolGateway | None = None) -> None:
        self._states: dict[str, AgentState] = {}
        self._tool_gateway = tool_gateway

    @property
    def tool_gateway(self) -> ToolGateway | None:
        """Configured tool boundary; the runtime does not start tool loops."""
        return self._tool_gateway

    def execute(
        self,
        agent: BaseAgent,
        context: AgentContext,
        *,
        execution_id: str | None = None,
    ) -> AgentResult:
        if not isinstance(agent, BaseAgent):
            raise AgentInputError("agent must be a BaseAgent instance.")
        if not isinstance(context, AgentContext):
            raise AgentInputError("context must be an AgentContext instance.")
        if not context.user_input.strip():
            raise AgentInputError("user_input cannot be empty.")

        execution_id = execution_id or str(uuid4())
        if execution_id in self._states:
            raise AgentInputError(f"Execution '{execution_id}' already exists.")

        started_at = datetime.now(UTC)
        messages = [*context.conversation]
        messages.append(Message(role=MessageRole.USER, content=context.user_input))
        metadata = {**agent.definition.metadata, **context.metadata}
        if context.request_id is not None:
            metadata["request_id"] = context.request_id
        state = AgentState(
            execution_id=execution_id,
            agent_id=agent.definition.agent_id,
            messages=messages,
            metadata=metadata,
            created_at=started_at,
            updated_at=started_at,
        )
        self._states[execution_id] = state
        state.transition(AgentExecutionStatus.RUNNING)
        state.iteration = 1
        self._emit(state, AgentEventType.EXECUTION_STARTED)

        try:
            output = agent.run(
                context,
                event_sink=lambda event_type: self._emit(state, event_type),
            )
            if not isinstance(output, str):
                raise AgentExecutionError("Agent output must be text.")
        except LLMError as exc:
            return self._fail(
                state,
                started_at,
                AgentLLMError("Agent LLM request failed."),
                error_code="llm_error",
                cause=exc,
            )
        except Exception as exc:
            return self._fail(
                state,
                started_at,
                AgentExecutionError("Agent execution failed."),
                error_code="execution_failed",
                cause=exc,
            )

        state.result = output
        state.transition(AgentExecutionStatus.COMPLETED)
        self._emit(state, AgentEventType.EXECUTION_COMPLETED)
        return AgentResult(
            execution_id=state.execution_id,
            agent_id=state.agent_id,
            status=state.status,
            output=output,
            metadata=dict(state.metadata),
            started_at=started_at,
            completed_at=state.updated_at,
        )

    def get_state(self, execution_id: str) -> AgentState:
        try:
            return self._states[execution_id].model_copy(deep=True)
        except KeyError as exc:
            raise AgentInputError(f"Execution '{execution_id}' was not found.") from exc

    def _fail(
        self,
        state: AgentState,
        started_at: datetime,
        error: AgentExecutionError,
        *,
        error_code: str,
        cause: Exception | None = None,
    ) -> AgentResult:
        state.transition(AgentExecutionStatus.FAILED)
        state.error = AgentErrorInfo(
            code=error_code,
            message=str(error),
            exception_type=type(error).__name__,
            cause_type=type(cause).__name__ if cause is not None else None,
        )
        self._emit(state, AgentEventType.EXECUTION_FAILED)
        if cause is not None:
            error.__cause__ = cause
        return AgentResult(
            execution_id=state.execution_id,
            agent_id=state.agent_id,
            status=state.status,
            error=state.error,
            metadata=dict(state.metadata),
            started_at=started_at,
            completed_at=state.updated_at,
        )

    @staticmethod
    def _emit(state: AgentState, event_type: AgentEventType) -> None:
        state.events.append(AgentEvent(type=event_type))
