# Deployment Foundation

This guide describes the current single-instance deployment boundary. It does not add cloud infrastructure, orchestration, migrations at startup, or a frontend.

## Local development

From `backend/`, copy `.env.example` to `.env`, set a reachable PostgreSQL URL and a local-only signing secret, then install and run:

```sh
uv sync
uv run uvicorn app.main:app --reload
```

Required settings are `APP_NAME`, `APP_VERSION`, `APP_DESCRIPTION`, `DATABASE_URL`, `SECRET_KEY`, and `ACCESS_TOKEN_EXPIRE_MINUTES`. Optional settings are `ENVIRONMENT` (`development`, `test`, `production`), `DEBUG`, `CORS_ORIGINS` (JSON list), `TRUSTED_HOSTS` (JSON list), `GEMINI_API_KEY`, `DEFAULT_LLM_PROVIDER`, and `DEFAULT_LLM_MODEL`. Never commit `.env` or log settings objects. Production secrets should come from protected runtime environment injection or a secret manager. Database URL and API key fields are omitted from the settings representation.

## Production configuration and security

Set `ENVIRONMENT=production` and `DEBUG=false`. Production requires a non-placeholder `SECRET_KEY` of at least 32 characters and an explicit `TRUSTED_HOSTS` list. CORS origins must be explicit; wildcard origins are rejected. CORS is off for an empty list and does not allow credentialed browser requests. Interactive API documentation is disabled in production. Request validation responses omit submitted input values, and unhandled errors return a generic 500 response; logs identify the exception type without logging its message or traceback.

The existing user API depends on PostgreSQL. Startup creates the SQLAlchemy engine and runs `SELECT 1`; an initialization failure leaves liveness available while readiness remains false. Readiness executes a fresh database check before returning ready. Health responses and lifecycle logs never include secret values. The root route and legacy `/api/v1/health` endpoints are retained.

## Health and lifecycle

- `GET /health/live` is a lightweight process liveness response.
- `GET /health/ready` returns 200 only after application initialization and a successful PostgreSQL check. It returns 503 before initialization, on initialization/dependency failure, or during shutdown.

FastAPI lifespan owns database initialization and engine disposal. Uvicorn handles SIGTERM and waits up to 30 seconds for active requests before lifespan cleanup. Long-running synchronous domain operations are not forcibly interrupted; no second cancellation mechanism is added. The web application does not globally construct agent/workflow services in this phase.

## Container

Build from `backend/` (the Docker ignore file excludes `.env`, local virtual environments, tests, and Git data):

```sh
docker build -t aios-backend -f Dockerfile .
docker run --rm --name aios-backend --env-file .env -p 8000:8000 --stop-timeout 35 aios-backend
```

The image uses Python 3.12 and the checked-in uv lockfile, runs as a non-root user, listens on port 8000, and handles SIGTERM through Uvicorn. Supply production variables through a protected runtime environment file or deployment secret facility; never bake them into the image. Apply Alembic migrations as a separate operator-controlled step; startup does not create or migrate tables.

## Persistence and deployment limits

The SQLAlchemy user API uses PostgreSQL. The AIOS `MemoryStore`, `WorkflowStore`, `EvaluationStore`, vector store, and observability sink interfaces are provider-neutral, but the current in-memory implementations are process-local, non-durable, and unsuitable for shared multi-process production state. A future persistent provider can implement those interfaces; no fake adapters are included.

This phase does not add PostgreSQL adapters for AIOS stores, Redis, Kubernetes, Helm, Terraform, cloud-specific resources, service mesh, workers/queues, autoscaling, multi-region deployment, enterprise IAM/OAuth integration, CI/CD, or frontend functionality.
