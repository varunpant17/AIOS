# Repository Guidelines

## Project Structure & Module Organization

The repository currently contains a Python backend in `backend/`. Application code is under `backend/app/`, organized by responsibility: `routers/` exposes FastAPI endpoints; `services/` holds business logic; `repositories/` handles persistence; `models/` and `schemas/` define database and API shapes. AI capabilities are grouped into `agents/`, `llm/`, `tools/`, `memory/`, `knowledge/`, `workflows/`, and `evaluation/`. Shared configuration and database/security setup live in `core/`. Alembic migrations are in `backend/alembic/versions/`; backend tests belong in `backend/tests/`. The root README describes architecture and setup.

## Build, Test, and Development Commands

Run backend commands from `backend/`:

- `uv sync` — install dependencies from `pyproject.toml` and `uv.lock`.
- `uv run uvicorn app.main:app --reload` — start the development API at `http://127.0.0.1:8000`.
- `uv run alembic upgrade head` — apply database migrations; configure `DATABASE_URL` in the local environment first.
- `uv run alembic revision --autogenerate -m "describe change"` — generate a migration after updating models.
- `uv run python -m unittest discover -s tests -v` — run backend unit tests.

Tests use Python's standard `unittest` framework and live in `backend/tests/`. Add focused tests for new behavior and keep database-dependent cases isolated.

## Coding Style & Naming Conventions

Use Python 3.12+, four spaces for indentation, and standard Python naming: `snake_case` for modules, functions, and variables; `PascalCase` for classes; and uppercase names for constants. Keep HTTP handling in routers, business rules in services, and database queries in repositories. Match the existing package boundaries and type/API schemas. No formatter or linter is configured; keep changes consistent with surrounding code.

## Testing Guidelines

There are no established coverage thresholds. Use descriptive `test_*.py` files and `unittest.TestCase` methods named `test_*`; isolate database-dependent cases and cover success and failure paths.

## Commit & Pull Request Guidelines

Recent commits use Conventional Commit-style subjects, often scoped, such as `feat(agent): introduce agent context` and `feat(llm): implement Gemini provider`. Follow `type(scope): imperative summary` (for example, `fix(auth): reject expired tokens`). Pull requests should explain the change and its rationale, note migration or configuration impacts, link related issues, and include relevant API examples or screenshots for user-visible changes.

## Security & Configuration

Keep credentials and local settings in `backend/.env`; never commit secrets. Update `.env` examples or documentation when adding required configuration, and review generated migrations before applying them.
