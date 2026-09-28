from collections.abc import Sequence

from app.evaluation.interfaces import Metric
from app.evaluation.types import EvaluationResult, EvaluationSummary


class BasicMetric:
    """Deterministic counts and arithmetic means; empty collections yield zeros."""

    def aggregate(self, results: Sequence[EvaluationResult]) -> EvaluationSummary:
        total = len(results)
        passed = sum(1 for result in results if result.passed)
        failed = total - passed
        return EvaluationSummary(
            total_cases=total,
            passed_cases=passed,
            failed_cases=failed,
            pass_rate=passed / total if total else 0.0,
            average_score=sum(result.score for result in results) / total if total else 0.0,
        )
