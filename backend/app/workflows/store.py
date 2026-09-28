from datetime import UTC, datetime
from threading import RLock

from pydantic import ValidationError

from app.workflows.errors import (
    DuplicateWorkflowError,
    InvalidWorkflowError,
    InvalidWorkflowTransitionError,
    WorkflowConcurrencyError,
    WorkflowExecutionError,
    WorkflowNotFoundError,
)
from app.workflows.types import Workflow, WorkflowStatus, WorkflowStep, WorkflowStepStatus


class InMemoryWorkflowStore:
    """Thread-safe in-process store with atomic claims and versioned updates."""

    def __init__(self) -> None:
        self._workflows: dict[str, Workflow] = {}
        self._lock = RLock()

    def create(self, workflow: Workflow) -> Workflow:
        validated = self._validated(workflow)
        with self._lock:
            if validated.version != 0:
                raise InvalidWorkflowError("New workflows must start at version zero.")
            if validated.status != WorkflowStatus.PENDING:
                raise InvalidWorkflowError("New workflows must start in the pending state.")
            if validated.workflow_id in self._workflows:
                raise DuplicateWorkflowError(
                    f"Workflow '{validated.workflow_id}' already exists."
                )
            self._workflows[validated.workflow_id] = validated.model_copy(deep=True)
            return self._workflows[validated.workflow_id].model_copy(deep=True)

    def get(self, workflow_id: str) -> Workflow:
        self._validate_id(workflow_id)
        with self._lock:
            workflow = self._workflows.get(workflow_id)
            if workflow is None:
                raise WorkflowNotFoundError(f"Workflow '{workflow_id}' was not found.")
            return workflow.model_copy(deep=True)

    def update(self, workflow: Workflow, *, expected_version: int) -> Workflow:
        validated = self._validated(workflow)
        with self._lock:
            current = self._workflows.get(validated.workflow_id)
            if current is None:
                raise WorkflowNotFoundError(
                    f"Workflow '{validated.workflow_id}' was not found."
                )
            if current.version != expected_version or validated.version != expected_version:
                raise WorkflowConcurrencyError("Workflow was updated from a stale version.")
            self._validate_update(current, validated)
            updated = validated.model_copy(update={"version": current.version + 1})
            self._workflows[updated.workflow_id] = updated.model_copy(deep=True)
            return self._workflows[updated.workflow_id].model_copy(deep=True)

    def claim_pending(self, workflow_id: str) -> Workflow:
        """Atomically reserve a pending workflow for one service instance."""
        self._validate_id(workflow_id)
        with self._lock:
            current = self._workflows.get(workflow_id)
            if current is None:
                raise WorkflowNotFoundError(f"Workflow '{workflow_id}' was not found.")
            if current.status != WorkflowStatus.PENDING:
                raise WorkflowExecutionError(
                    f"Workflow in {current.status.value} state cannot be claimed."
                )
            claimed = current.model_copy(
                update={
                    "status": WorkflowStatus.RUNNING,
                    "start_event_emitted": False,
                    "started_at": datetime.now(UTC),
                    "version": current.version + 1,
                }
            )
            self._workflows[workflow_id] = claimed.model_copy(deep=True)
            return self._workflows[workflow_id].model_copy(deep=True)

    def mark_started_event_emitted(self, workflow_id: str) -> Workflow:
        """Record start-event emission before allowing cancellation to finalize."""
        self._validate_id(workflow_id)
        with self._lock:
            current = self._workflows.get(workflow_id)
            if current is None:
                raise WorkflowNotFoundError(f"Workflow '{workflow_id}' was not found.")
            if current.status not in {WorkflowStatus.RUNNING, WorkflowStatus.CANCELLING}:
                raise WorkflowExecutionError(
                    f"Workflow in {current.status.value} state cannot acknowledge start."
                )
            if current.start_event_emitted:
                return current.model_copy(deep=True)
            updated = current.model_copy(
                update={"start_event_emitted": True, "version": current.version + 1}
            )
            self._workflows[workflow_id] = updated.model_copy(deep=True)
            return self._workflows[workflow_id].model_copy(deep=True)

    def request_cancel(
        self, workflow_id: str
    ) -> tuple[Workflow, tuple[WorkflowStep, ...], bool]:
        """Atomically cancel pending/between-step work or request active-step cancellation."""
        self._validate_id(workflow_id)
        with self._lock:
            current = self._workflows.get(workflow_id)
            if current is None:
                raise WorkflowNotFoundError(f"Workflow '{workflow_id}' was not found.")
            if current.status in {
                WorkflowStatus.COMPLETED,
                WorkflowStatus.FAILED,
                WorkflowStatus.CANCELLED,
                WorkflowStatus.CANCELLING,
            }:
                return current.model_copy(deep=True), (), False

            now = datetime.now(UTC)
            if current.status == WorkflowStatus.RUNNING and (
                current.current_step_id is not None or not current.start_event_emitted
            ):
                updated = current.model_copy(
                    update={
                        "status": WorkflowStatus.CANCELLING,
                        "version": current.version + 1,
                    }
                )
                changed_steps: tuple[WorkflowStep, ...] = ()
            else:
                steps = []
                changed = []
                for step in current.steps:
                    if step.status == WorkflowStepStatus.PENDING:
                        step = step.model_copy(
                            update={
                                "status": WorkflowStepStatus.CANCELLED,
                                "completed_at": now,
                            }
                        )
                        changed.append(step)
                    steps.append(step)
                updated = current.model_copy(
                    update={
                        "steps": tuple(steps),
                        "status": WorkflowStatus.CANCELLED,
                        "completed_at": now,
                        "current_step_id": None,
                        "current_step_position": None,
                        "version": current.version + 1,
                    }
                )
                changed_steps = tuple(changed)
            self._workflows[workflow_id] = updated.model_copy(deep=True)
            return self._workflows[workflow_id].model_copy(deep=True), changed_steps, True

    def delete(self, workflow_id: str) -> None:
        self._validate_id(workflow_id)
        with self._lock:
            workflow = self._workflows.get(workflow_id)
            if workflow is None:
                raise WorkflowNotFoundError(f"Workflow '{workflow_id}' was not found.")
            if workflow.status in {WorkflowStatus.RUNNING, WorkflowStatus.CANCELLING}:
                raise WorkflowExecutionError("An active workflow cannot be deleted; cancel it first.")
            del self._workflows[workflow_id]

    @staticmethod
    def _validate_update(current: Workflow, candidate: Workflow) -> None:
        if (
            candidate.plan_id != current.plan_id
            or candidate.created_at != current.created_at
            or candidate.context.workflow_id != current.context.workflow_id
            or candidate.context.inputs != current.context.inputs
            or candidate.context.variables != current.context.variables
            or candidate.context.metadata != current.context.metadata
            or candidate.start_event_emitted != current.start_event_emitted
            or len(candidate.steps) != len(current.steps)
        ):
            raise InvalidWorkflowError("Workflow definition fields are immutable after creation.")
        if candidate.metadata != current.metadata and current.status != WorkflowStatus.PENDING:
            raise InvalidWorkflowError("Workflow metadata cannot change after execution starts.")

        allowed_workflow_transitions = {
            WorkflowStatus.PENDING: {WorkflowStatus.PENDING},
            WorkflowStatus.RUNNING: {
                WorkflowStatus.RUNNING,
                WorkflowStatus.COMPLETED,
                WorkflowStatus.FAILED,
            },
            WorkflowStatus.CANCELLING: {
                WorkflowStatus.CANCELLING,
                WorkflowStatus.CANCELLED,
            },
            WorkflowStatus.COMPLETED: set(),
            WorkflowStatus.FAILED: set(),
            WorkflowStatus.CANCELLED: set(),
        }
        if candidate.status not in allowed_workflow_transitions[current.status]:
            raise InvalidWorkflowTransitionError(
                f"Cannot update workflow from {current.status.value} to {candidate.status.value}."
            )

        allowed_step_transitions = {
            WorkflowStepStatus.PENDING: {
                WorkflowStepStatus.PENDING,
                WorkflowStepStatus.RUNNING,
            },
            WorkflowStepStatus.RUNNING: {
                WorkflowStepStatus.RUNNING,
                WorkflowStepStatus.COMPLETED,
                WorkflowStepStatus.FAILED,
                WorkflowStepStatus.CANCELLED,
            },
            WorkflowStepStatus.COMPLETED: {WorkflowStepStatus.COMPLETED},
            WorkflowStepStatus.FAILED: {WorkflowStepStatus.FAILED},
            WorkflowStepStatus.CANCELLED: {WorkflowStepStatus.CANCELLED},
        }
        for old_step, new_step in zip(current.steps, candidate.steps, strict=True):
            if (
                old_step.step_id != new_step.step_id
                or old_step.source_step_id != new_step.source_step_id
                or old_step.position != new_step.position
                or old_step.description != new_step.description
                or old_step.action != new_step.action
                or old_step.metadata != new_step.metadata
            ):
                raise InvalidWorkflowError("Workflow step definitions are immutable after creation.")
            if (
                old_step.status
                in {
                    WorkflowStepStatus.COMPLETED,
                    WorkflowStepStatus.FAILED,
                    WorkflowStepStatus.CANCELLED,
                }
                and old_step.status == new_step.status
                and old_step != new_step
            ):
                raise InvalidWorkflowError("A terminal workflow step cannot be modified.")
            allowed = set(allowed_step_transitions[old_step.status])
            if (
                current.status == WorkflowStatus.CANCELLING
                and candidate.status == WorkflowStatus.CANCELLED
                and old_step.status in {WorkflowStepStatus.PENDING, WorkflowStepStatus.RUNNING}
            ):
                allowed.add(WorkflowStepStatus.CANCELLED)
            if new_step.status not in allowed:
                raise InvalidWorkflowTransitionError(
                    f"Cannot update step from {old_step.status.value} to {new_step.status.value}."
                )

    @staticmethod
    def _validated(workflow: Workflow) -> Workflow:
        if not isinstance(workflow, Workflow):
            raise InvalidWorkflowError("WorkflowStore accepts validated Workflow objects.")
        try:
            return Workflow.model_validate(workflow)
        except ValidationError as exc:
            raise InvalidWorkflowError("Workflow no longer satisfies its contract.") from exc

    @staticmethod
    def _validate_id(workflow_id: str) -> None:
        if not isinstance(workflow_id, str) or not workflow_id.strip():
            raise InvalidWorkflowError("workflow_id must contain non-whitespace text.")
