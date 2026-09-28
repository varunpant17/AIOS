from threading import RLock

from pydantic import ValidationError

from app.evaluation.errors import (
    EvaluationStoreError,
    EvaluationRunError,
)
from app.evaluation.interfaces import EvaluationStore
from app.evaluation.types import EvaluationRun, EvaluationRunStatus


class InMemoryEvaluationStore:
    """Thread-safe process-local store; state is not durable or shared across processes."""

    def __init__(self) -> None:
        self._runs: dict[str, EvaluationRun] = {}
        self._lock = RLock()

    def create_run(self, run: EvaluationRun) -> EvaluationRun:
        validated = self._validated(run)
        with self._lock:
            if validated.status != EvaluationRunStatus.CREATED or validated.version != 0:
                raise EvaluationRunError("New evaluation runs must be created at version zero.")
            if validated.run_id in self._runs:
                raise EvaluationStoreError("Evaluation run ID already exists.")
            self._runs[validated.run_id] = validated.model_copy(deep=True)
            return self._runs[validated.run_id].model_copy(deep=True)

    def get_run(self, run_id: str) -> EvaluationRun:
        self._validate_id(run_id)
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise EvaluationStoreError("Evaluation run was not found.")
            return run.model_copy(deep=True)

    def update_run(self, run: EvaluationRun, *, expected_version: int) -> EvaluationRun:
        candidate = self._validated(run)
        with self._lock:
            current = self._runs.get(candidate.run_id)
            if current is None:
                raise EvaluationStoreError("Evaluation run was not found.")
            if current.version != expected_version or candidate.version != expected_version:
                raise EvaluationRunError("Evaluation run was updated from a stale version.")
            if (candidate.dataset_id != current.dataset_id
                    or candidate.created_at != current.created_at
                    or (current.started_at is not None
                        and candidate.started_at != current.started_at)):
                raise EvaluationRunError("Evaluation run identity is immutable.")
            allowed = {
                EvaluationRunStatus.CREATED: {EvaluationRunStatus.RUNNING},
                EvaluationRunStatus.RUNNING: {EvaluationRunStatus.RUNNING,
                                              EvaluationRunStatus.COMPLETED,
                                              EvaluationRunStatus.FAILED},
                EvaluationRunStatus.COMPLETED: set(),
                EvaluationRunStatus.FAILED: set(),
            }
            if candidate.status not in allowed[current.status]:
                raise EvaluationRunError(
                    f"Invalid evaluation run transition: {current.status.value} to {candidate.status.value}."
                )
            if current.status == EvaluationRunStatus.RUNNING:
                if candidate.results[:len(current.results)] != current.results:
                    raise EvaluationRunError("Previously recorded results cannot be changed or removed.")
            updated = EvaluationRun.model_validate(
                candidate.model_dump(mode="python") | {"version": current.version + 1}
            )
            self._runs[updated.run_id] = updated.model_copy(deep=True)
            return self._runs[updated.run_id].model_copy(deep=True)

    def list_runs(self, *, dataset_id: str | None = None) -> tuple[EvaluationRun, ...]:
        with self._lock:
            runs = [run for run in self._runs.values()
                    if dataset_id is None or run.dataset_id == dataset_id]
            return tuple(run.model_copy(deep=True) for run in sorted(
                runs, key=lambda item: (item.created_at, item.run_id)
            ))

    @staticmethod
    def _validated(run: EvaluationRun) -> EvaluationRun:
        if not isinstance(run, EvaluationRun):
            raise EvaluationStoreError("Evaluation store accepts EvaluationRun objects.")
        try:
            return EvaluationRun.model_validate(run)
        except (ValidationError, TypeError, ValueError) as exc:
            raise EvaluationStoreError("Evaluation run does not satisfy its domain contract.") from exc

    @staticmethod
    def _validate_id(run_id: str) -> None:
        if not isinstance(run_id, str) or not run_id.strip():
            raise EvaluationStoreError("run_id must contain non-whitespace text.")
