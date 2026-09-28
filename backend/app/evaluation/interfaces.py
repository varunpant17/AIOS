from collections.abc import Mapping, Sequence
from typing import Protocol

from pydantic import JsonValue

from app.evaluation.types import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
    EvaluationSummary,
)


class Evaluator(Protocol):
    evaluator_id: str

    def evaluate(self, case: EvaluationCase, actual: JsonValue) -> EvaluationResult: ...


class Metric(Protocol):
    def aggregate(self, results: Sequence[EvaluationResult]) -> EvaluationSummary: ...


class EvaluationStore(Protocol):
    def create_run(self, run: EvaluationRun) -> EvaluationRun: ...

    def get_run(self, run_id: str) -> EvaluationRun: ...

    def update_run(self, run: EvaluationRun, *, expected_version: int) -> EvaluationRun: ...

    def list_runs(self, *, dataset_id: str | None = None) -> tuple[EvaluationRun, ...]: ...


class EvaluationRunner(Protocol):
    def evaluate(
        self,
        dataset: EvaluationDataset,
        actuals: Mapping[str, JsonValue],
    ) -> EvaluationRun: ...
