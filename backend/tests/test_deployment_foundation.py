import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.core.database import get_db
from app.evaluation import EvaluationRun, EvaluationStoreError, InMemoryEvaluationStore
from app.evaluation.interfaces import EvaluationStore
from app.evaluation.service import EvaluationService
from app.main import create_app
from app.memory.store import InMemoryMemoryStore
from app.memory.interfaces import MemoryStore
from app.memory.service import MemoryService
from app.memory.types import Memory, MemoryQuery, MemoryScope, MemoryType
from app.observability import InMemoryEventSink, ObservabilityService
from app.observability.interfaces import EventSink
from app.planning import Plan, PlanStep
from app.workflows.errors import WorkflowNotFoundError
from app.workflows.executor import DeterministicStepExecutor
from app.workflows.service import WorkflowService
from app.workflows.interfaces import WorkflowStore
from app.workflows.store import InMemoryWorkflowStore


def settings_values(**overrides):
    values = {
        "APP_NAME": "AIOS Test",
        "APP_VERSION": "test-version",
        "APP_DESCRIPTION": "Deployment test app",
        "DATABASE_URL": "postgresql+psycopg://user:pass@localhost/test",
        "SECRET_KEY": "development-only-secret-not-for-production",
        "ACCESS_TOKEN_EXPIRE_MINUTES": 30,
        "ENVIRONMENT": "test",
        "DEBUG": False,
    }
    values.update(overrides)
    return values


class DeploymentFoundationTests(unittest.TestCase):
    def test_settings_environment_selection_and_secret_repr(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "test"}, clear=True):
            values = settings_values()
            values.pop("ENVIRONMENT")
            config = Settings(_env_file=None, **values)
        self.assertEqual(config.ENVIRONMENT, "test")
        self.assertNotIn(config.SECRET_KEY, repr(config))
        self.assertNotIn(config.DATABASE_URL, repr(config))

    def test_production_requires_safe_secret_debug_off_and_trusted_hosts(self):
        production = settings_values(
            ENVIRONMENT="production",
            SECRET_KEY="random-production-signing-key-value-0123456789",
            TRUSTED_HOSTS=["api.example.test"],
            CORS_ORIGINS=["https://ui.example.test"],
        )
        self.assertEqual(Settings(_env_file=None, **production).ENVIRONMENT, "production")
        for invalid in (
            {**production, "SECRET_KEY": "development-only-secret-not-for-production"},
            {**production, "DEBUG": True},
            {**production, "TRUSTED_HOSTS": []},
            {**production, "TRUSTED_HOSTS": ["*"]},
            {**production, "CORS_ORIGINS": ["*"]},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValidationError):
                    Settings(_env_file=None, **invalid)

    def test_lifecycle_health_readiness_and_cleanup(self):
        events = []
        config = Settings(_env_file=None, **settings_values())
        app = create_app(
            config,
            initialize_resources=lambda url: events.append(("init", url)),
            cleanup_resources=lambda: events.append(("cleanup", None)),
            readiness_check=lambda: True,
        )
        self.assertFalse(app.state.lifecycle["initialized"])
        with TestClient(app) as client:
            live = client.get("/health/live")
            ready = client.get("/health/ready")
            self.assertEqual(live.status_code, 200)
            self.assertEqual(live.json(), {
                "status": "alive", "app_name": "AIOS Test", "version": "test-version",
                "environment": "test", "initialized": None, "shutting_down": None,
            })
            self.assertEqual(ready.status_code, 200)
            self.assertTrue(ready.json()["initialized"])
            self.assertFalse(ready.json()["shutting_down"])
            self.assertEqual(client.get("/").status_code, 200)
        self.assertTrue(app.state.lifecycle["shutting_down"])
        self.assertFalse(app.state.lifecycle["initialized"])
        self.assertEqual([event[0] for event in events], ["init", "cleanup"])

    def test_readiness_fails_if_database_check_fails(self):
        config = Settings(_env_file=None, **settings_values())
        app = create_app(
            config,
            initialize_resources=lambda url: None,
            cleanup_resources=lambda: None,
            readiness_check=lambda: False,
        )
        with TestClient(app) as client:
            response = client.get("/health/ready")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["status"], "not_ready")
            self.assertTrue(response.json()["initialized"])
            self.assertEqual(client.get("/health/live").status_code, 200)

    def test_startup_failure_keeps_liveness_and_hides_exception(self):
        config = Settings(_env_file=None, **settings_values())

        def fail_startup(url):
            raise RuntimeError("password=secret-value")

        app = create_app(config, initialize_resources=fail_startup,
                         cleanup_resources=lambda: None, readiness_check=lambda: True)
        with TestClient(app) as client:
            self.assertEqual(client.get("/health/live").status_code, 200)
            ready = client.get("/health/ready")
            self.assertEqual(ready.status_code, 503)
            self.assertFalse(ready.json()["initialized"])
            self.assertNotIn("secret-value", ready.text)

    def test_internal_and_validation_errors_do_not_echo_secrets(self):
        config = Settings(_env_file=None, **settings_values())
        app = create_app(config, initialize_resources=lambda url: None,
                         cleanup_resources=lambda: None, readiness_check=lambda: True)

        def explode():
            raise RuntimeError("internal-secret-value")

        app.add_api_route("/test/failure", explode)
        with TestClient(app, raise_server_exceptions=False) as client:
            failure = client.get("/test/failure")
            self.assertEqual(failure.status_code, 500)
            self.assertEqual(failure.json(), {"detail": "Internal server error."})
            self.assertNotIn("internal-secret-value", failure.text)
            invalid = client.post("/api/v1/health/check", json={"name": "x", "city": "secret-input"})
            self.assertEqual(invalid.status_code, 422)
            self.assertNotIn("secret-input", invalid.text)

    def test_cors_and_trusted_host_rules(self):
        config = Settings(_env_file=None, **settings_values(
            CORS_ORIGINS=["https://client.example.test"], TRUSTED_HOSTS=["testserver"]
        ))
        app = create_app(config, initialize_resources=lambda url: None,
                         cleanup_resources=lambda: None, readiness_check=lambda: True)
        with TestClient(app) as client:
            allowed = client.get("/health/live", headers={"Origin": "https://client.example.test"})
            self.assertEqual(allowed.headers.get("access-control-allow-origin"), "https://client.example.test")
            denied = client.get("/health/live", headers={"Origin": "https://untrusted.example.test"})
            self.assertNotIn("access-control-allow-origin", denied.headers)
            bad_host = client.get("/health/live", headers={"Host": "untrusted.example.test"})
            self.assertEqual(bad_host.status_code, 400)

    def test_production_disables_debug_docs_and_health_hides_secrets(self):
        config = Settings(_env_file=None, **settings_values(
            ENVIRONMENT="production",
            SECRET_KEY="random-production-signing-key-value-0123456789",
            TRUSTED_HOSTS=["testserver"],
        ))
        app = create_app(config, initialize_resources=lambda url: None,
                         cleanup_resources=lambda: None, readiness_check=lambda: True)
        self.assertFalse(app.debug)
        self.assertIsNone(app.docs_url)
        self.assertIsNone(app.openapi_url)
        with TestClient(app) as client:
            response = client.get("/health/live")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(config.SECRET_KEY, response.text)
            self.assertNotIn(config.DATABASE_URL, response.text)

    def test_in_memory_store_instances_are_isolated_and_process_local(self):
        evaluation_a, evaluation_b = InMemoryEvaluationStore(), InMemoryEvaluationStore()
        evaluation_a.create_run(EvaluationRun(run_id="local", dataset_id="d"))
        with self.assertRaises(EvaluationStoreError):
            evaluation_b.get_run("local")

        memory_a, memory_b = InMemoryMemoryStore(), InMemoryMemoryStore()
        memory_a.create(Memory(memory_id="m", content="saved", memory_type=MemoryType.EPISODIC,
                               scope=MemoryScope.GLOBAL, source="test"))
        self.assertEqual(len(memory_b.search(MemoryQuery())), 0)

        workflow_a, workflow_b = InMemoryWorkflowStore(), InMemoryWorkflowStore()
        workflow = WorkflowService(workflow_a, DeterministicStepExecutor({})).create(Plan(
            plan_id="p", goal="goal", steps=(PlanStep(step_id="s", position=0,
                                                       description="describe", action="act"),)
        ))
        with self.assertRaises(WorkflowNotFoundError):
            workflow_b.get(workflow.workflow_id)

        sink_a, sink_b = InMemoryEventSink(), InMemoryEventSink()
        self.assertEqual(sink_a.events, [])
        self.assertEqual(sink_b.events, [])
        self.assertIn("process-local", InMemoryEvaluationStore.__doc__)
        self.assertIn("in-process", InMemoryMemoryStore.__doc__)
        self.assertIn("in-process", InMemoryWorkflowStore.__doc__)

    def test_application_services_depend_on_provider_neutral_ports(self):
        self.assertIs(EvaluationService.__init__.__annotations__["store"], EvaluationStore)
        self.assertIs(MemoryService.__init__.__annotations__["store"], MemoryStore)
        self.assertIs(WorkflowService.__init__.__annotations__["store"], WorkflowStore)
        self.assertIs(ObservabilityService.__init__.__annotations__["sink"], EventSink)

    def test_container_configuration_is_static_and_excludes_secrets(self):
        backend_dir = Path(__file__).parents[1]
        dockerfile = (backend_dir / "Dockerfile").read_text(encoding="utf-8")
        dockerignore = (backend_dir / ".dockerignore").read_text(encoding="utf-8")
        self.assertIn("FROM python:3.12-slim", dockerfile)
        self.assertIn("uv sync --frozen --no-dev --no-install-project", dockerfile)
        self.assertIn("USER aios", dockerfile)
        self.assertIn("STOPSIGNAL SIGTERM", dockerfile)
        self.assertIn("--timeout-graceful-shutdown", dockerfile)
        self.assertNotIn("SECRET_KEY=", dockerfile)
        self.assertIn(".env", dockerignore)

    def test_database_sessions_require_lifespan_initialization(self):
        with patch("app.core.database._session_factory", None):
            with self.assertRaisesRegex(RuntimeError, "lifespan is not active"):
                next(get_db())
