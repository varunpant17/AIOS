import json
from datetime import UTC, datetime
from threading import RLock
from typing import Any

from pydantic import ValidationError

from app.agents.runtime import AgentRuntime
from app.agents.types import AgentContext, AgentErrorInfo, AgentExecutionStatus, AgentResult
from app.multi_agent.errors import (
    AgentTaskError,
    AgentTaskNotFoundError,
    MultiAgentError,
)
from app.multi_agent.interfaces import A2AChannel, AgentRegistry
from app.multi_agent.router import AgentRouter
from app.multi_agent.types import AgentMessage, AgentMessageType, AgentTask, AgentTaskStatus
from app.observability.interfaces import Observability
from app.observability.safe import operation_run, safe_emit
from app.observability.types import EventError, EventType


class MultiAgentService:
    """Coordinates one bounded delegation through A2A and the existing runtime."""

    def __init__(
        self,
        registry: AgentRegistry,
        router: AgentRouter,
        channel: A2AChannel,
        runtime: AgentRuntime,
        *,
        observability: Observability | None = None,
    ) -> None:
        self._registry = registry
        self._router = router
        self._channel = channel
        self._runtime = runtime
        self._observability = observability
        self._tasks: dict[str, AgentTask] = {}
        self._lock = RLock()

    def delegate(
        self,
        requester_agent_id: str,
        *,
        payload: dict[str, Any],
        agent_id: str | None = None,
        capability: str | None = None,
    ) -> AgentTask:
        with operation_run(self._observability, "multi_agent") as operation:
            try:
                self._registry.get(requester_agent_id)
                target = self._router.resolve(agent_id=agent_id, capability=capability)
                task = AgentTask(
                    requester_agent_id=requester_agent_id,
                    assignee_agent_id=target.agent_id,
                    payload=payload,
                )
            except MultiAgentError:
                raise
            except (ValidationError, TypeError, ValueError) as exc:
                raise AgentTaskError("Delegated task input is invalid.") from exc

            self._save_task(task)
            self._emit(
                EventType.AGENT_TASK_CREATED,
                operation.run_id,
                self._task_metadata(task),
            )
            task = task.model_copy(
                update={
                    "status": AgentTaskStatus.RUNNING,
                    "started_at": datetime.now(UTC),
                    "version": 1,
                }
            )
            self._save_task(task)
            self._emit(
                EventType.AGENT_TASK_STARTED,
                operation.run_id,
                self._task_metadata(task),
            )

            message = AgentMessage(
                sender_agent_id=task.requester_agent_id,
                recipient_agent_id=task.assignee_agent_id,
                conversation_id=task.conversation_id,
                task_id=task.task_id,
                message_type=AgentMessageType.TASK_REQUEST,
                payload=task.payload,
            )
            try:
                self._channel.send(message)
                self._emit(
                    EventType.A2A_MESSAGE_SENT,
                    operation.run_id,
                    self._message_metadata(message),
                )
                received = self._channel.receive(
                    task.assignee_agent_id, task_id=task.task_id
                )
                self._emit(
                    EventType.A2A_MESSAGE_RECEIVED,
                    operation.run_id,
                    self._message_metadata(received),
                )
            except Exception as exc:
                failure = self._normalized_error(exc, "A2A message delivery failed.")
                self._emit(
                    EventType.A2A_MESSAGE_FAILED,
                    operation.run_id,
                    self._message_metadata(message),
                    error=EventError(
                        code=failure.code,
                        exception_type=failure.exception_type,
                    ),
                )
                failed = self._finish_task(
                    task,
                    AgentTaskStatus.FAILED,
                    error=failure,
                )
                self._emit_task_failed(failed, operation.run_id)
                operation.fail(
                    EventError(code=failure.code, exception_type=failure.exception_type)
                )
                return failed

            try:
                context = self._agent_context(received)
                result = self._runtime.execute(
                    self._registry.get_agent(task.assignee_agent_id), context
                )
                if not isinstance(result, AgentResult):
                    raise AgentTaskError("AgentRuntime returned an invalid result.")
                result_snapshot = result.model_dump(mode="json")
                if result.status == AgentExecutionStatus.COMPLETED:
                    completed = self._finish_task(
                        task,
                        AgentTaskStatus.COMPLETED,
                        result=result_snapshot,
                    )
                    self._emit(
                        EventType.AGENT_TASK_COMPLETED,
                        operation.run_id,
                        self._task_metadata(completed),
                    )
                    return completed
                failure = self._agent_result_error(result)
                failed = self._finish_task(
                    task,
                    AgentTaskStatus.FAILED,
                    result=result_snapshot,
                    error=failure,
                )
                self._emit_task_failed(failed, operation.run_id)
                operation.fail(
                    EventError(code=failure.code, exception_type=failure.exception_type)
                )
                return failed
            except Exception as exc:
                failure = self._normalized_error(exc, "Delegated agent execution failed.")
                failed = self._finish_task(task, AgentTaskStatus.FAILED, error=failure)
                self._emit_task_failed(failed, operation.run_id)
                operation.fail(
                    EventError(code=failure.code, exception_type=failure.exception_type)
                )
                return failed

    def get_task(self, task_id: str) -> AgentTask:
        if not isinstance(task_id, str) or not task_id.strip():
            raise AgentTaskNotFoundError("task_id must contain non-whitespace text.")
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise AgentTaskNotFoundError(f"Task '{task_id}' was not found.")
            return task.model_copy(deep=True)

    def _finish_task(
        self,
        task: AgentTask,
        status: AgentTaskStatus,
        *,
        result: dict[str, Any] | None = None,
        error: AgentErrorInfo | None = None,
    ) -> AgentTask:
        finished = task.model_copy(
            update={
                "status": status,
                "completed_at": datetime.now(UTC),
                "result": result,
                "error": error,
                "version": 2,
            }
        )
        self._save_task(finished)
        return finished

    def _save_task(self, task: AgentTask) -> None:
        with self._lock:
            self._tasks[task.task_id] = task.model_copy(deep=True)

    def _emit_task_failed(self, task: AgentTask, run_id: str | None) -> None:
        error = task.error or AgentErrorInfo(
            code="agent_task_failed",
            message="Delegated agent task failed.",
            exception_type="AgentTaskError",
        )
        self._emit(
            EventType.AGENT_TASK_FAILED,
            run_id,
            self._task_metadata(task),
            error=EventError(
                code=error.code,
                exception_type=error.exception_type,
            ),
        )

    def _emit(
        self,
        event_type: EventType,
        run_id: str | None,
        metadata: dict[str, Any],
        *,
        error: EventError | None = None,
    ) -> None:
        safe_emit(
            self._observability,
            event_type,
            "multi_agent",
            run_id=run_id,
            metadata=metadata,
            error=error,
        )

    @staticmethod
    def _task_metadata(task: AgentTask) -> dict[str, Any]:
        return {
            "task_id": task.task_id,
            "requester_agent_id": task.requester_agent_id,
            "assignee_agent_id": task.assignee_agent_id,
            "status": task.status.value,
            "version": task.version,
        }

    @staticmethod
    def _message_metadata(message: AgentMessage) -> dict[str, Any]:
        return {
            "message_id": message.message_id,
            "task_id": message.task_id,
            "conversation_id": message.conversation_id,
            "sender_agent_id": message.sender_agent_id,
            "recipient_agent_id": message.recipient_agent_id,
            "message_type": message.message_type.value,
        }

    @staticmethod
    def _normalized_error(exc: Exception, message: str) -> AgentErrorInfo:
        if isinstance(exc, MultiAgentError):
            code = type(exc).__name__
        else:
            code = "agent_execution_failed"
        return AgentErrorInfo(
            code=code,
            message=message,
            exception_type=type(exc).__name__,
        )

    @staticmethod
    def _agent_result_error(result: AgentResult) -> AgentErrorInfo:
        if result.error is None:
            return AgentErrorInfo(
                code="agent_failed",
                message="Delegated agent execution failed.",
                exception_type="AgentExecutionError",
            )
        return AgentErrorInfo(
            code=result.error.code,
            message="Delegated agent execution failed.",
            exception_type=result.error.exception_type,
            cause_type=result.error.cause_type,
        )

    @staticmethod
    def _agent_context(message: AgentMessage) -> AgentContext:
        payload = dict(message.payload)
        user_input = payload.get("user_input")
        if not isinstance(user_input, str):
            user_input = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        goal = payload.get("goal")
        return AgentContext(
            user_input=user_input,
            goal=goal if isinstance(goal, str) else None,
            request_id=message.task_id,
            metadata={
                "task_id": message.task_id,
                "requester_agent_id": message.sender_agent_id,
            },
            data={"delegated_payload": payload},
        )
