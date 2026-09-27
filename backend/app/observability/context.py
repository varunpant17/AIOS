from contextvars import ContextVar, Token
from typing import Iterator

from app.observability.types import RunContext

_active_run_id: ContextVar[str | None] = ContextVar("aios_active_run_id", default=None)


def current_run_id() -> str | None:
    return _active_run_id.get()


class bind_run:
    """Bind a run id for nested synchronous AIOS operations."""

    def __init__(self, run: RunContext | str) -> None:
        self._run_id = run.run_id if isinstance(run, RunContext) else run
        self._token: Token | None = None

    def __enter__(self) -> str:
        self._token = _active_run_id.set(self._run_id)
        return self._run_id

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._token is not None:
            _active_run_id.reset(self._token)
