from collections.abc import Mapping

from app.workflows.errors import StepExecutionError
from app.workflows.interfaces import StepExecutor
from app.workflows.types import StepResult, WorkflowContext, WorkflowStep


class DeterministicStepExecutor:
    """Test-oriented executor that returns explicitly supplied outcomes by step ID."""

    def __init__(self, outcomes: Mapping[str, StepResult]) -> None:
        self._outcomes = {
            step_id: StepResult.model_validate(result)
            for step_id, result in outcomes.items()
        }

    def execute(self, step: WorkflowStep, context: WorkflowContext) -> StepResult:
        del context
        try:
            return self._outcomes[step.source_step_id].model_copy(deep=True)
        except KeyError as exc:
            raise StepExecutionError("No deterministic outcome was configured for this step.") from exc
