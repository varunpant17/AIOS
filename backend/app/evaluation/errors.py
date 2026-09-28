class EvaluationError(Exception):
    """Base class for normalized evaluation boundary failures."""


class DatasetValidationError(EvaluationError):
    pass


class EvaluatorError(EvaluationError):
    pass


class EvaluationRunError(EvaluationError):
    pass


class EvaluationStoreError(EvaluationError):
    pass
