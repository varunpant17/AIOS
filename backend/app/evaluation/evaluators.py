import json
from collections.abc import Mapping
from math import isfinite
from typing import Any

from pydantic import JsonValue

from app.core.immutable import freeze_json
from app.evaluation.errors import EvaluatorError
from app.evaluation.interfaces import Evaluator
from app.evaluation.types import EvaluationCase, EvaluationResult


def _canonical(value: Any) -> str:
    try:
        frozen = freeze_json(value)
        return json.dumps(frozen, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise EvaluatorError("Evaluator values must be JSON-compatible.") from exc


def _result(case: EvaluationCase, evaluator_id: str, passed: bool, explanation: str) -> EvaluationResult:
    return EvaluationResult(
        case_id=case.case_id,
        evaluator_id=evaluator_id,
        passed=passed,
        score=1.0 if passed else 0.0,
        explanation=explanation,
    )


class ExactMatchEvaluator:
    """Compares JSON values canonically, independent of object key ordering."""

    evaluator_id = "exact_match"

    def evaluate(self, case: EvaluationCase, actual: JsonValue) -> EvaluationResult:
        passed = _canonical(case.expected) == _canonical(actual)
        return _result(case, self.evaluator_id, passed, "Exact match." if passed else "Values differ.")


def _contains(expected: Any, actual: Any) -> bool:
    if isinstance(expected, str):
        return isinstance(actual, str) and expected in actual
    if isinstance(expected, dict):
        return isinstance(actual, Mapping) and all(
            key in actual and _contains(value, actual[key]) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and all(
            any(_contains(item, candidate) for candidate in actual) for item in expected
        )
    return _canonical(expected) == _canonical(actual)


class ContainsEvaluator:
    """Checks substring, recursive object subset, or required list-item containment."""

    evaluator_id = "contains"

    def evaluate(self, case: EvaluationCase, actual: JsonValue) -> EvaluationResult:
        _canonical(actual)
        passed = _contains(case.expected, actual)
        return _result(case, self.evaluator_id, passed, "Required content found." if passed else "Required content missing.")


class ThresholdEvaluator:
    """Passes when a finite numeric actual value is >= the numeric expected threshold."""

    evaluator_id = "threshold"

    def evaluate(self, case: EvaluationCase, actual: JsonValue) -> EvaluationResult:
        threshold = case.expected
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise EvaluatorError("Threshold expected value must be numeric.")
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            raise EvaluatorError("Threshold actual value must be numeric.")
        if not isfinite(threshold) or not isfinite(actual):
            raise EvaluatorError("Threshold values must be finite numbers.")
        passed = actual >= threshold
        return _result(case, self.evaluator_id, passed, "Threshold met." if passed else "Threshold not met.")
