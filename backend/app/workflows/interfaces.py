from typing import Protocol

from app.workflows.types import StepResult, Workflow, WorkflowContext, WorkflowStep


class WorkflowStore(Protocol):
    """Provider-neutral persistence contract with atomic lifecycle operations."""

    def create(self, workflow: Workflow) -> Workflow: ...

    def get(self, workflow_id: str) -> Workflow: ...

    def update(self, workflow: Workflow, *, expected_version: int) -> Workflow: ...

    def claim_pending(self, workflow_id: str) -> Workflow: ...

    def mark_started_event_emitted(self, workflow_id: str) -> Workflow:
        """Atomically acknowledge start-event emission and advance the workflow version."""
        ...

    def request_cancel(
        self, workflow_id: str
    ) -> tuple[Workflow, tuple[WorkflowStep, ...], bool]: ...

    def delete(self, workflow_id: str) -> None: ...


class StepExecutor(Protocol):
    """Executes one step and returns a normalized provider-neutral outcome."""

    def execute(self, step: WorkflowStep, context: WorkflowContext) -> StepResult: ...
