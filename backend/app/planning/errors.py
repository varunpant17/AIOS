class PlanningError(Exception):
    """Base class for normalized planning boundary failures."""


class InvalidPlanError(PlanningError):
    pass


class InvalidPlanStepError(PlanningError):
    pass


class PlannerError(PlanningError):
    pass
