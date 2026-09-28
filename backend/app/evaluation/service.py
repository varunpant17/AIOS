from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import JsonValue, ValidationError

from app.core.immutable import freeze_json
from app.evaluation.errors import (
    DatasetValidationError,
    EvaluationError,
    EvaluationRunError,
    EvaluationStoreError,
    EvaluatorError,
)
from app.evaluation.interfaces import EvaluationStore, Evaluator, Metric
from app.evaluation.metrics import BasicMetric
from app.evaluation.types import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationErrorInfo,
    EvaluationResult,
    EvaluationRun,
    EvaluationRunStatus,
    EvaluationSummary,
)
from app.observability.interfaces import Observability
from app.observability.safe import operation_run, safe_emit
from app.observability.types import EventError, EventType


class EvaluationService:
    """Sequential provider-neutral evaluator over caller-supplied actual outputs."""

    def __init__(
        self,
        store: EvaluationStore,
        evaluator: Evaluator,
        *,
        metric: Metric | None = None,
        observability: Observability | None = None,
    ) -> None:
        self._store = store
        self._evaluator = evaluator
        self._metric = metric if metric is not None else BasicMetric()
        self._observability = observability
        evaluator_id = getattr(evaluator, "evaluator_id", None)
        if not isinstance(evaluator_id, str) or not evaluator_id.strip():
            raise EvaluatorError("Evaluator must expose a non-empty evaluator_id.")
        self._evaluator_id = evaluator_id

    def evaluate(
        self,
        dataset: EvaluationDataset | Mapping[str, Any],
        actuals: Mapping[str, JsonValue],
    ) -> EvaluationRun:
        with operation_run(self._observability, "evaluation") as operation:
            validated_dataset = self._validate_dataset(dataset)
            validated_actuals = self._validate_actuals(validated_dataset, actuals)
            run = EvaluationRun(
                run_id=str(uuid4()), dataset_id=validated_dataset.dataset_id
            )
            run = self._store_call("create_run", self._store.create_run, run)
            run = self._update(
                run,
                status=EvaluationRunStatus.RUNNING,
                started_at=datetime.now(UTC),
            )
            self._emit(
                EventType.EVALUATION_RUN_STARTED,
                operation.run_id,
                {"evaluation_run_id": run.run_id, "dataset_id": run.dataset_id},
            )

            results: list[EvaluationResult] = []
            for case in validated_dataset.cases:
                try:
                    result = self._evaluator.evaluate(case, validated_actuals[case.case_id])
                    if not isinstance(result, EvaluationResult):
                        raise EvaluatorError("Evaluator returned an invalid result object.")
                    if result.case_id != case.case_id or result.evaluator_id != self._evaluator_id:
                        raise EvaluatorError("Evaluator result identity does not match its request.")
                except Exception as exc:
                    normalized = exc if isinstance(exc, EvaluatorError) else EvaluatorError(
                        "Evaluator failed while evaluating a case."
                    )
                    failed_result = EvaluationResult(
                        case_id=case.case_id,
                        evaluator_id=self._evaluator_id,
                        passed=False,
                        score=0.0,
                        explanation="Evaluator execution failed.",
                    )
                    results.append(failed_result)
                    try:
                        summary = self._aggregate(results)
                    except EvaluationRunError:
                        summary = BasicMetric().aggregate(tuple(results))
                    run = self._update(run, results=tuple(results))
                    self._emit(
                        EventType.EVALUATION_CASE_FAILED,
                        operation.run_id,
                        {"evaluation_run_id": run.run_id, "dataset_id": run.dataset_id,
                         "case_id": case.case_id, "evaluator_id": self._evaluator_id},
                        error=normalized,
                    )
                    run_error = EvaluationErrorInfo(
                        code=type(normalized).__name__,
                        exception_type=type(exc).__name__,
                        case_id=case.case_id,
                    )
                    run = self._update(
                        run,
                        status=EvaluationRunStatus.FAILED,
                        completed_at=datetime.now(UTC),
                        summary=summary,
                        error=run_error,
                    )
                    self._emit(
                        EventType.EVALUATION_RUN_FAILED,
                        operation.run_id,
                        self._run_metadata(run),
                        error=normalized,
                    )
                    operation.fail(EventError(
                        code=type(normalized).__name__, exception_type=type(exc).__name__
                    ))
                    return run

                results.append(result)
                run = self._update(run, results=tuple(results))
                self._emit(
                    EventType.EVALUATION_CASE_COMPLETED,
                    operation.run_id,
                    {"evaluation_run_id": run.run_id, "dataset_id": run.dataset_id,
                     "case_id": case.case_id, "evaluator_id": result.evaluator_id,
                     "passed": result.passed, "score": result.score},
                )

            try:
                summary = self._aggregate(results)
            except EvaluationRunError as exc:
                summary = BasicMetric().aggregate(tuple(results))
                run = self._update(
                    run,
                    status=EvaluationRunStatus.FAILED,
                    completed_at=datetime.now(UTC),
                    summary=summary,
                    error=EvaluationErrorInfo(
                        code=type(exc).__name__, exception_type=type(exc).__name__
                    ),
                )
                self._emit(EventType.EVALUATION_RUN_FAILED, operation.run_id,
                           self._run_metadata(run), error=exc)
                operation.fail(EventError(code=type(exc).__name__, exception_type=type(exc).__name__))
                return run
            run = self._update(
                run,
                status=EvaluationRunStatus.COMPLETED,
                completed_at=datetime.now(UTC),
                summary=summary,
            )
            self._emit(EventType.EVALUATION_RUN_COMPLETED, operation.run_id, self._run_metadata(run))
            return run

    def get_run(self, run_id: str) -> EvaluationRun:
        return self._store_call("get_run", self._store.get_run, run_id)

    def _update(self, run: EvaluationRun, **changes: Any) -> EvaluationRun:
        candidate = run.model_copy(update=changes)
        try:
            return self._store.update_run(candidate, expected_version=run.version)
        except EvaluationError:
            raise
        except Exception as exc:
            raise EvaluationStoreError("Evaluation run could not be updated.") from exc

    @staticmethod
    def _store_call(operation: str, callback, *args):
        try:
            return callback(*args)
        except EvaluationError:
            raise
        except Exception as exc:
            raise EvaluationStoreError(f"Evaluation store {operation} failed.") from exc

    def _aggregate(self, results: list[EvaluationResult]) -> EvaluationSummary:
        try:
            summary = self._metric.aggregate(tuple(results))
            if not isinstance(summary, EvaluationSummary):
                raise TypeError("Metric returned an invalid summary.")
            return EvaluationSummary.model_validate(summary)
        except Exception as exc:
            raise EvaluationRunError("Evaluation metrics could not be aggregated.") from exc

    @staticmethod
    def _validate_dataset(dataset: EvaluationDataset | Mapping[str, Any]) -> EvaluationDataset:
        try:
            validated = dataset if isinstance(dataset, EvaluationDataset) else EvaluationDataset.model_validate(dataset)
            return EvaluationDataset.model_validate(validated)
        except (ValidationError, TypeError, ValueError) as exc:
            raise DatasetValidationError("Evaluation dataset is invalid.") from exc

    @staticmethod
    def _validate_actuals(
        dataset: EvaluationDataset, actuals: Mapping[str, JsonValue]
    ) -> dict[str, JsonValue]:
        if not isinstance(actuals, Mapping):
            raise DatasetValidationError("Actual outputs must be provided as a case ID mapping.")
        expected_ids = {case.case_id for case in dataset.cases}
        if set(actuals) != expected_ids:
            raise DatasetValidationError("Actual outputs must contain exactly one value per dataset case.")
        try:
            return {case_id: freeze_json(value) for case_id, value in actuals.items()}
        except (TypeError, ValueError) as exc:
            raise DatasetValidationError("Actual outputs must contain JSON-compatible values.") from exc

    def _emit(
        self,
        event_type: EventType,
        run_id: str | None,
        metadata: dict[str, JsonValue],
        *,
        error: Exception | None = None,
    ) -> None:
        safe_emit(self._observability, event_type, "evaluation", run_id=run_id,
                  metadata=metadata, error=error)

    @staticmethod
    def _run_metadata(run: EvaluationRun) -> dict[str, JsonValue]:
        summary = run.summary
        return {
            "evaluation_run_id": run.run_id,
            "dataset_id": run.dataset_id,
            "status": run.status.value,
            "total_cases": summary.total_cases if summary else 0,
            "passed_cases": summary.passed_cases if summary else 0,
            "failed_cases": summary.failed_cases if summary else 0,
            "pass_rate": summary.pass_rate if summary else 0.0,
            "average_score": summary.average_score if summary else 0.0,
        }
