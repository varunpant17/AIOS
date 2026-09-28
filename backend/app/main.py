import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import Settings, settings
from app.core.database import check_database, dispose_database, initialize_database
from app.routers.api import api_router
from app.schemas.health import ApplicationHealthResponse

logger = logging.getLogger(__name__)


def create_app(
    config: Settings = settings,
    *,
    initialize_resources: Callable[[str], Any] = initialize_database,
    cleanup_resources: Callable[[], Any] = dispose_database,
    readiness_check: Callable[[], bool] = check_database,
) -> FastAPI:
    """Build the HTTP application and own its shared resource lifecycle."""

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.lifecycle = {"initialized": False, "shutting_down": False}
        application.state.readiness_check = readiness_check
        try:
            try:
                initialize_resources(config.DATABASE_URL)
            except Exception as exc:
                logger.error("Application resource initialization failed (exception_type=%s).",
                             type(exc).__name__)
            else:
                application.state.lifecycle["initialized"] = True
                logger.info("Application resources initialized.")
            yield
        finally:
            application.state.lifecycle["shutting_down"] = True
            application.state.lifecycle["initialized"] = False
            logger.info("Application shutdown started.")
            try:
                cleanup_resources()
            except Exception as exc:
                logger.error("Application resource cleanup failed (exception_type=%s).",
                             type(exc).__name__)
            logger.info("Application shutdown complete.")

    production = config.ENVIRONMENT == "production"
    application = FastAPI(
        title=config.APP_NAME,
        version=config.APP_VERSION,
        description=config.APP_DESCRIPTION,
        debug=config.DEBUG,
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
        openapi_url=None if production else "/openapi.json",
        lifespan=lifespan,
    )
    application.state.lifecycle = {"initialized": False, "shutting_down": False}
    application.state.readiness_check = readiness_check

    if config.CORS_ORIGINS:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=config.CORS_ORIGINS,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    if config.TRUSTED_HOSTS:
        application.add_middleware(TrustedHostMiddleware, allowed_hosts=config.TRUSTED_HOSTS)

    @application.exception_handler(RequestValidationError)
    async def request_validation_error(request: Request, exc: RequestValidationError):
        # Omit pydantic's input/context values, which may contain submitted secrets.
        errors = [
            {"loc": error.get("loc", ()), "msg": error.get("msg", "Invalid request."),
             "type": error.get("type", "value_error")}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    @application.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        logger.error("Unhandled request failure (exception_type=%s).", type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "Internal server error."})

    @application.get("/", include_in_schema=not production)
    async def root():
        return {"message": "AI Enterprise Operating System API"}

    health_router = APIRouter(prefix="/health", tags=["Health"])

    @health_router.get("/live", response_model=ApplicationHealthResponse)
    async def live():
        return ApplicationHealthResponse(
            status="alive", app_name=config.APP_NAME, version=config.APP_VERSION,
            environment=config.ENVIRONMENT,
        )

    @health_router.get("/ready", response_model=ApplicationHealthResponse)
    def ready(request: Request):
        lifecycle = getattr(request.app.state, "lifecycle", {})
        initialized = bool(lifecycle.get("initialized", False))
        shutting_down = bool(lifecycle.get("shutting_down", False))
        dependency_ready = False
        if initialized and not shutting_down:
            try:
                dependency_ready = bool(request.app.state.readiness_check())
            except Exception as exc:
                logger.error("Readiness check failed (exception_type=%s).", type(exc).__name__)
        is_ready = initialized and not shutting_down and dependency_ready
        return JSONResponse(
            status_code=200 if is_ready else 503,
            content=ApplicationHealthResponse(
                status="ready" if is_ready else "not_ready",
                app_name=config.APP_NAME,
                version=config.APP_VERSION,
                environment=config.ENVIRONMENT,
                initialized=initialized,
                shutting_down=shutting_down,
            ).model_dump(),
        )

    application.include_router(health_router)
    application.include_router(api_router)
    return application


app = create_app()
