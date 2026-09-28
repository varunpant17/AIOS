from datetime import UTC, datetime
from threading import Lock, RLock
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from app.observability.interfaces import Observability
from app.observability.safe import operation_run, safe_emit
from app.observability.types import EventError, EventType
from app.planning.types import Plan
from app.workflows.errors import (
    InvalidWorkflowError,
    WorkflowError,
    WorkflowConcurrencyError,
    WorkflowExecutionError,
    WorkflowStoreError,
)
from app.workflows.interfaces import StepExecutor, WorkflowStore
from app.workflows.types import (
    StepErrorInfo,
    StepResult,
    Workflow,
    WorkflowContext,
    WorkflowStatus,
    WorkflowStep,
    WorkflowStepStatus,
)


class WorkflowService:
    """Creates, sequentially executes, and tracks workflow instances."""

    def __init__(
        self,
        store: WorkflowStore,
        executor: StepExecutor,
        *,
        observability: Observability | None = None,
    ) -> None:
        self._store = store
        self._executor = executor
        self._observability = observability
        self._lock_guard = Lock()
        self._workflow_locks: dict[str, RLock] = {}

    def create(
        self,
        plan: Plan,
        *,
        inputs: dict[str, Any] | None = None,
        variables: dict[str, Any] | None = None,
        context_metadata: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Workflow:
        if not isinstance(plan, Plan):
            raise InvalidWorkflowError("Workflow creation requires a validated Plan.")
        try:
            plan = Plan.model_validate(plan)
            workflow_id = str(uuid4())
            workflow = Workflow(
                workflow_id=workflow_id,
                plan_id=plan.plan_id,
                steps=tuple(
                    WorkflowStep(
                        step_id=str(uuid4()),
                        source_step_id=step.step_id,
                        position=step.position,
                        description=step.description,
                        action=step.action,
                        metadata=step.metadata,
                    )
                    for step in plan.steps
                ),
                context=WorkflowContext(
                    workflow_id=workflow_id,
                    inputs=inputs or {},
                    variables=variables or {},
                    metadata=context_metadata or {},
                ),
                metadata=metadata or {},
            )
        except ValidationError as exc:
            raise InvalidWorkflowError("Workflow definition is invalid.") from exc
        try:
            return self._store.create(workflow)
        except WorkflowError:
            raise
        except Exception as exc:
            raise WorkflowStoreError("Workflow could not be stored.") from exc

    def get(self, workflow_id: str) -> Workflow:
        try:
            return self._store.get(workflow_id)
        except WorkflowError:
            raise
        except Exception as exc:
            raise WorkflowStoreError("Workflow could not be retrieved.") from exc

    def execute(self, workflow_id: str) -> Workflow:
        if not isinstance(workflow_id, str) or not workflow_id.strip():
            raise InvalidWorkflowError("workflow_id must contain non-whitespace text.")
        with operation_run(self._observability, "workflow") as operation:
            lock = self._workflow_lock(workflow_id)
            try:
                with lock:
                    try:
                        workflow = self._store_claim(workflow_id)
                    except WorkflowExecutionError:
                        latest = self.get(workflow_id)
                        if latest.status == WorkflowStatus.CANCELLED:
                            return latest
                        raise
                    self._emit(
                        EventType.WORKFLOW_STARTED,
                        operation.run_id,
                        self._workflow_metadata(workflow, step_count=len(workflow.steps)),
                    )
                    self._store_mark_started_event(workflow.workflow_id)
                return self._execute_steps(workflow_id, operation)
            except WorkflowError as exc:
                operation.fail(EventError(code=type(exc).__name__, exception_type=type(exc).__name__))
                raise
            except Exception as exc:
                error = WorkflowExecutionError("Workflow execution failed.")
                operation.fail(EventError(code=type(exc).__name__, exception_type=type(exc).__name__))
                raise error from exc

    def cancel(self, workflow_id: str) -> Workflow:
        if not isinstance(workflow_id, str) or not workflow_id.strip():
            raise InvalidWorkflowError("workflow_id must contain non-whitespace text.")
        with operation_run(self._observability, "workflow") as operation:
            workflow, cancelled_steps, changed = self._store_request_cancel(workflow_id)
            for step in cancelled_steps:
                self._emit_step(
                    EventType.WORKFLOW_STEP_CANCELLED,
                    operation.run_id,
                    workflow,
                    step,
                )
            if changed and workflow.status == WorkflowStatus.CANCELLED:
                self._emit(
                    EventType.WORKFLOW_CANCELLED,
                    operation.run_id,
                    self._workflow_metadata(workflow, status=workflow.status.value),
                )
            return workflow

    def delete(self, workflow_id: str) -> None:
        if not isinstance(workflow_id, str) or not workflow_id.strip():
            raise InvalidWorkflowError("workflow_id must contain non-whitespace text.")
        with self._workflow_lock(workflow_id):
            try:
                self._store.delete(workflow_id)
            except WorkflowError:
                raise
            except Exception as exc:
                raise WorkflowStoreError("Workflow could not be deleted.") from exc

    def _execute_steps(self, workflow_id: str, operation) -> Workflow:
        lock = self._workflow_lock(workflow_id)
        while True:
            with lock:
                workflow = self.get(workflow_id)
                if workflow.status in {WorkflowStatus.CANCELLED, WorkflowStatus.COMPLETED}:
                    return workflow
                if workflow.status == WorkflowStatus.CANCELLING:
                    return self._finish_cancellation(workflow, operation.run_id)
                step = next(
                    (item for item in workflow.steps if item.status == WorkflowStepStatus.PENDING),
                    None,
                )
                if step is None:
                    completed = workflow.model_copy(
                        update={"status": WorkflowStatus.COMPLETED, "completed_at": datetime.now(UTC)}
                    )
                    try:
                        completed = self._store_update(completed)
                    except WorkflowConcurrencyError:
                        latest = self.get(workflow_id)
                        if latest.status == WorkflowStatus.CANCELLING:
                            return self._finish_cancellation(latest, operation.run_id)
                        if latest.status in {WorkflowStatus.CANCELLED, WorkflowStatus.COMPLETED}:
                            return latest
                        continue
                    self._emit(
                        EventType.WORKFLOW_COMPLETED,
                        operation.run_id,
                        self._workflow_metadata(completed, status=completed.status.value),
                    )
                    return completed
                running_step = step.model_copy(
                    update={"status": WorkflowStepStatus.RUNNING, "started_at": datetime.now(UTC)}
                )
                workflow = self._replace_step(
                    workflow,
                    running_step,
                    current_step_id=step.step_id,
                    current_step_position=step.position,
                )
                try:
                    workflow = self._store_update(workflow)
                except WorkflowConcurrencyError:
                    # Cancellation or another store transition won before the step claim.
                    continue
                self._emit_step(
                    EventType.WORKFLOW_STEP_STARTED, operation.run_id, workflow, running_step
                )

            result = self._execute_one(running_step, workflow.context)

            with lock:
                workflow = self.get(workflow_id)
                if workflow.status == WorkflowStatus.CANCELLING:
                    return self._finish_cancellation(
                        workflow, operation.run_id, running_step.step_id
                    )
                now = datetime.now(UTC)
                step_status = (
                    WorkflowStepStatus.COMPLETED if result.success else WorkflowStepStatus.FAILED
                )
                finished_step = running_step.model_copy(
                    update={
                        "status": step_status,
                        "completed_at": now,
                        "result": result,
                    }
                )
                workflow_updates: dict[str, Any] = {
                    "current_step_id": None,
                    "current_step_position": None,
                }
                if result.success and result.output is not None:
                    workflow_updates["context"] = workflow.context.model_copy(
                        update={
                            "outputs": {
                                **workflow.context.outputs,
                                running_step.source_step_id: result.output,
                            }
                        }
                    )
                workflow = self._replace_step(workflow, finished_step, **workflow_updates)
                if not result.success:
                    workflow = workflow.model_copy(
                        update={"status": WorkflowStatus.FAILED, "completed_at": now}
                    )
                    try:
                        workflow = self._store_update(workflow)
                    except WorkflowConcurrencyError:
                        latest = self.get(workflow_id)
                        if latest.status == WorkflowStatus.CANCELLING:
                            return self._finish_cancellation(
                                latest, operation.run_id, running_step.step_id
                            )
                        if latest.status in {WorkflowStatus.CANCELLED, WorkflowStatus.COMPLETED}:
                            return latest
                        continue
                    self._emit_step(
                        EventType.WORKFLOW_STEP_FAILED,
                        operation.run_id,
                        workflow,
                        finished_step,
                    )
                    error = result.error or StepErrorInfo(
                        code="step_failed",
                        message="Step execution failed.",
                        exception_type="StepExecutionError",
                    )
                    self._emit(
                        EventType.WORKFLOW_FAILED,
                        operation.run_id,
                        self._workflow_metadata(workflow, status=workflow.status.value),
                        error=EventError(code=error.code, exception_type=error.exception_type),
                    )
                    operation.fail(
                        EventError(code=error.code, exception_type=error.exception_type)
                    )
                    return workflow
                try:
                    workflow = self._store_update(workflow)
                except WorkflowConcurrencyError:
                    latest = self.get(workflow_id)
                    if latest.status == WorkflowStatus.CANCELLING:
                        return self._finish_cancellation(
                            latest, operation.run_id, running_step.step_id
                        )
                    if latest.status in {WorkflowStatus.CANCELLED, WorkflowStatus.COMPLETED}:
                        return latest
                    continue
                self._emit_step(
                    EventType.WORKFLOW_STEP_COMPLETED,
                    operation.run_id,
                    workflow,
                    finished_step,
                )

    def _execute_one(self, step: WorkflowStep, context: WorkflowContext) -> StepResult:
        try:
            result = self._executor.execute(step, context)
            if not isinstance(result, StepResult):
                raise TypeError("StepExecutor must return StepResult.")
            return StepResult.model_validate(result)
        except Exception as exc:
            return StepResult(
                success=False,
                error=StepErrorInfo(
                    code=type(exc).__name__,
                    message="Step execution failed.",
                    exception_type=type(exc).__name__,
                ),
            )

    def _finish_cancellation(
        self,
        workflow: Workflow,
        run_id: str | None,
        active_step_id: str | None = None,
    ) -> Workflow:
        now = datetime.now(UTC)
        cancelled: list[WorkflowStep] = []
        steps = list(workflow.steps)
        for index, step in enumerate(steps):
            if step.step_id == active_step_id:
                step = step.model_copy(
                    update={
                        "status": WorkflowStepStatus.CANCELLED,
                        "completed_at": now,
                        "result": None,
                    }
                )
            elif step.status == WorkflowStepStatus.PENDING:
                step = step.model_copy(
                    update={"status": WorkflowStepStatus.CANCELLED, "completed_at": now}
                )
            else:
                continue
            steps[index] = step
            cancelled.append(step)
        workflow = workflow.model_copy(
            update={
                "steps": tuple(steps),
                "status": WorkflowStatus.CANCELLED,
                "completed_at": now,
                "current_step_id": None,
                "current_step_position": None,
            }
        )
        workflow = self._store_update(workflow)
        for step in cancelled:
            self._emit_step(EventType.WORKFLOW_STEP_CANCELLED, run_id, workflow, step)
        self._emit(
            EventType.WORKFLOW_CANCELLED,
            run_id,
            self._workflow_metadata(workflow, status=workflow.status.value),
        )
        return workflow

    def _replace_step(self, workflow: Workflow, step: WorkflowStep, **updates: Any) -> Workflow:
        steps = tuple(step if item.step_id == step.step_id else item for item in workflow.steps)
        return workflow.model_copy(update={"steps": steps, **updates})

    def _store_update(self, workflow: Workflow) -> Workflow:
        try:
            return self._store.update(workflow, expected_version=workflow.version)
        except WorkflowError:
            raise
        except Exception as exc:
            raise WorkflowStoreError("Workflow state could not be saved.") from exc

    def _store_claim(self, workflow_id: str) -> Workflow:
        try:
            return self._store.claim_pending(workflow_id)
        except WorkflowError:
            raise
        except Exception as exc:
            raise WorkflowStoreError("Workflow could not be claimed for execution.") from exc

    def _store_mark_started_event(self, workflow_id: str) -> Workflow:
        try:
            return self._store.mark_started_event_emitted(workflow_id)
        except WorkflowError:
            raise
        except Exception as exc:
            raise WorkflowStoreError("Workflow start event could not be acknowledged.") from exc

    def _store_request_cancel(
        self, workflow_id: str
    ) -> tuple[Workflow, tuple[WorkflowStep, ...], bool]:
        try:
            return self._store.request_cancel(workflow_id)
        except WorkflowError:
            raise
        except Exception as exc:
            raise WorkflowStoreError("Workflow cancellation could not be requested.") from exc

    def _workflow_lock(self, workflow_id: str) -> RLock:
        with self._lock_guard:
            return self._workflow_locks.setdefault(workflow_id, RLock())

    def _emit_step(
        self,
        event_type: EventType,
        run_id: str | None,
        workflow: Workflow,
        step: WorkflowStep,
    ) -> None:
        self._emit(
            event_type,
            run_id,
            self._workflow_metadata(
                workflow,
                step_id=step.step_id,
                source_step_id=step.source_step_id,
                step_position=step.position,
                step_status=step.status.value,
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
            "workflow",
            run_id=run_id,
            metadata=metadata,
            error=error,
        )

    @staticmethod
    def _workflow_metadata(workflow: Workflow, **metadata: Any) -> dict[str, Any]:
        return {
            "workflow_id": workflow.workflow_id,
            "plan_id": workflow.plan_id,
            "status": workflow.status.value,
            **metadata,
        }
