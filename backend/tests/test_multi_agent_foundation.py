import threading
import unittest
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from app.agents import AgentContext, AgentDefinition, AgentExecutionStatus, AgentRuntime, BaseAgent
from app.multi_agent import (
    A2ACommunicationError,
    AgentMessage,
    AgentMessageType,
    AgentRouter,
    AgentTask,
    AgentTaskStatus,
    AmbiguousAgentCapabilityError,
    DuplicateAgentError,
    InMemoryA2AChannel,
    InMemoryAgentRegistry,
    InvalidAgentMessageError,
    MissingAgentCapabilityError,
    MultiAgentService,
)
from app.observability import (
    EventType,
    InMemoryEventSink,
    ObservabilityService,
    RunStatus,
    bind_run,
)


class EchoAgent(BaseAgent):
    def __init__(self, definition):
        super().__init__(definition)
        self.calls = []

    def run(self, context, *, event_sink=None):
        self.calls.append(context)
        return context.user_input


def make_agent(agent_id, *, capabilities=()):
    return EchoAgent(
        AgentDefinition(
            agent_id=agent_id,
            name=agent_id.title(),
            capabilities=tuple(capabilities),
        )
    )


class MultiAgentFoundationTests(unittest.TestCase):
    def setUp(self):
        self.registry = InMemoryAgentRegistry()
        self.requester = make_agent("requester", capabilities=("coordination",))
        self.worker = make_agent("worker", capabilities=("research",))
        self.registry.register(self.requester)
        self.registry.register(self.worker)
        self.router = AgentRouter(self.registry)

    def make_service(self, *, runtime=None, channel=None, observability=None):
        return MultiAgentService(
            self.registry,
            self.router,
            channel or InMemoryA2AChannel(self.registry),
            runtime or AgentRuntime(observability=observability),
            observability=observability,
        )

    def test_registry_registration_lookup_capabilities_and_defensive_definitions(self):
        definition = self.registry.get("worker")
        registered_definition = self.registry.get("worker")
        self.assertIsNot(definition, registered_definition)
        self.assertIsNot(definition.metadata, registered_definition.metadata)
        self.assertEqual(definition.capabilities, ("research",))
        definition.agent_id = "changed"
        definition.capabilities = ("changed",)
        definition.metadata["team"] = "changed"
        self.assertEqual(self.registry.get("worker").agent_id, "worker")
        self.assertEqual(self.registry.get("worker").capabilities, ("research",))
        self.assertEqual([item.agent_id for item in self.registry.list()], ["requester", "worker"])
        self.assertEqual(
            [item.agent_id for item in self.registry.find_by_capability(" RESEARCH ")],
            ["worker"],
        )
        with self.assertRaises(DuplicateAgentError):
            self.registry.register(make_agent("worker"))

    def test_registry_missing_agent_and_capability_validation(self):
        from app.multi_agent import AgentNotFoundError, InvalidAgentDefinitionError

        with self.assertRaises(AgentNotFoundError):
            self.registry.get("missing")
        with self.assertRaises(AgentNotFoundError):
            self.registry.unregister("missing")
        with self.assertRaises(InvalidAgentDefinitionError):
            self.registry.find_by_capability(" ")
        with self.assertRaises(ValidationError):
            AgentDefinition(agent_id=" ", name="Invalid")
        with self.assertRaises(ValidationError):
            AgentDefinition(agent_id="duplicate-cap", name="Invalid", capabilities=("x", " X "))

    def test_runtime_resolution_rejects_agent_definition_drift(self):
        from app.multi_agent import InvalidAgentDefinitionError

        self.worker.definition.capabilities = ("changed",)
        with self.assertRaises(InvalidAgentDefinitionError):
            self.registry.get_agent("worker")

    def test_registry_duplicate_registration_is_thread_safe(self):
        agent = make_agent("contended")
        barrier = threading.Barrier(2)
        outcomes = []

        def register():
            barrier.wait(timeout=2)
            try:
                self.registry.register(agent)
                outcomes.append("registered")
            except DuplicateAgentError:
                outcomes.append("duplicate")

        threads = [threading.Thread(target=register) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertCountEqual(outcomes, ["registered", "duplicate"])

    def test_router_resolves_id_unique_capability_and_rejects_missing_or_ambiguous(self):
        self.assertEqual(self.router.resolve(agent_id="worker").agent_id, "worker")
        self.assertEqual(self.router.resolve(capability="research").agent_id, "worker")
        with self.assertRaises(MissingAgentCapabilityError):
            self.router.resolve(capability="unknown")
        from app.multi_agent import InvalidAgentRouteError

        with self.assertRaises(InvalidAgentRouteError):
            self.router.resolve()
        with self.assertRaises(InvalidAgentRouteError):
            self.router.resolve(agent_id="worker", capability="research")
        self.registry.register(make_agent("worker-2", capabilities=("research",)))
        with self.assertRaises(AmbiguousAgentCapabilityError):
            self.router.resolve(capability="research")

    def test_task_freezes_input_and_enforces_lifecycle_timestamp_and_copy_contracts(self):
        payload = {"nested": {"items": ["original"]}}
        task = AgentTask(requester_agent_id="requester", assignee_agent_id="worker", payload=payload)
        payload["nested"]["items"].append("changed")
        self.assertEqual(task.payload["nested"]["items"], ["original"])
        with self.assertRaises(TypeError):
            task.payload["nested"]["items"].append("blocked")
        with self.assertRaises(ValueError):
            task.model_copy(update={"status": AgentTaskStatus.COMPLETED})
        with self.assertRaises(ValidationError):
            task.model_copy(update={"requester_agent_id": " "})
        running_at = task.created_at + timedelta(seconds=1)
        running = task.model_copy(
            update={
                "status": AgentTaskStatus.RUNNING,
                "started_at": running_at,
                "version": 1,
            }
        )
        self.assertEqual(
            running.model_copy(update={"status": AgentTaskStatus.RUNNING}), running
        )
        with self.assertRaises(ValueError):
            task.model_copy(update={"status": AgentTaskStatus.FAILED})
        with self.assertRaises(ValidationError):
            AgentTask(
                requester_agent_id="requester",
                assignee_agent_id="worker",
                payload={},
                created_at=datetime(2025, 1, 1),
            )
        with self.assertRaises(ValidationError):
            running.model_copy(update={"completed_at": running_at - timedelta(seconds=1)})
        with self.assertRaises(ValidationError):
            running.model_copy(update={"started_at": task.created_at - timedelta(seconds=1)})
        result_payload = {"nested": ["before"]}
        completed = running.model_copy(
            update={
                "status": AgentTaskStatus.COMPLETED,
                "version": 2,
                "completed_at": running_at + timedelta(seconds=1),
                "result": result_payload,
            }
        )
        result_payload["nested"].append("after")
        self.assertEqual(completed.result["nested"], ["before"])
        self.assertEqual(task.created_at.tzinfo, UTC)

    def test_message_validates_and_detaches_payload_aliases(self):
        payload = {"nested": ["before"]}
        message = AgentMessage(
            sender_agent_id="requester",
            recipient_agent_id="worker",
            conversation_id="conversation-1",
            task_id="task-1",
            message_type=AgentMessageType.TASK_REQUEST,
            payload=payload,
        )
        payload["nested"].append("after")
        self.assertEqual(message.payload["nested"], ["before"])
        with self.assertRaises(TypeError):
            message.payload["nested"].append("blocked")
        with self.assertRaises(ValidationError):
            message.model_copy(update={"recipient_agent_id": " "})
        with self.assertRaises(ValidationError):
            message.model_copy(update={"created_at": datetime(2025, 1, 1)})

    def test_channel_delivers_validated_messages_and_normalizes_failures(self):
        channel = InMemoryA2AChannel(self.registry)
        message = AgentMessage(
            sender_agent_id="requester",
            recipient_agent_id="worker",
            conversation_id="conversation-1",
            task_id="task-1",
            message_type=AgentMessageType.TASK_REQUEST,
            payload={"user_input": "hello"},
        )
        channel.send(message)
        received = channel.receive("worker", task_id="task-1")
        self.assertEqual(received, message)
        with self.assertRaises(A2ACommunicationError):
            channel.receive("worker", task_id="task-1")
        missing = message.model_copy(update={"recipient_agent_id": "missing"})
        with self.assertRaises(A2ACommunicationError):
            channel.send(missing)
        with self.assertRaises(InvalidAgentMessageError):
            channel.send(object())

    def test_service_delegates_through_channel_and_existing_runtime(self):
        sink = InMemoryEventSink()
        observability = ObservabilityService(sink)

        class RuntimeSpy(AgentRuntime):
            def __init__(self):
                super().__init__(observability=observability)
                self.calls = []

            def execute(self, agent, context, *, execution_id=None):
                self.calls.append((agent, context))
                return super().execute(agent, context, execution_id=execution_id)

        runtime = RuntimeSpy()
        service = self.make_service(runtime=runtime, observability=observability)
        task = service.delegate(
            "requester", capability="research", payload={"user_input": "private task text"}
        )
        self.assertEqual(task.status, AgentTaskStatus.COMPLETED)
        self.assertEqual(task.result["output"], "private task text")
        self.assertEqual(task.version, 2)
        self.assertEqual(len(runtime.calls), 1)
        self.assertIs(runtime.calls[0][0], self.worker)
        self.assertEqual(self.worker.calls[0].request_id, task.task_id)
        self.assertEqual(
            self.worker.calls[0].data["delegated_payload"]["user_input"],
            "private task text",
        )
        self.assertEqual(service.get_task(task.task_id), task)
        expected = [
            EventType.AGENT_TASK_CREATED,
            EventType.AGENT_TASK_STARTED,
            EventType.A2A_MESSAGE_SENT,
            EventType.A2A_MESSAGE_RECEIVED,
            EventType.AGENT_TASK_COMPLETED,
        ]
        task_events = [event for event in sink.events if event.component == "multi_agent"]
        self.assertEqual([event.event_type for event in task_events], expected)
        self.assertEqual(len({event.run_id for event in task_events}), 1)
        serialized = repr([event.model_dump(mode="json") for event in sink.events])
        self.assertNotIn("private task text", serialized)

    def test_nested_task_events_reuse_active_run(self):
        sink = InMemoryEventSink()
        observability = ObservabilityService(sink)
        parent = observability.start_run()
        service = self.make_service(observability=observability)
        with bind_run(parent):
            task = service.delegate("requester", agent_id="worker", payload={"user_input": "hi"})
        task_events = [event for event in sink.events if event.component == "multi_agent"]
        self.assertEqual(task.status, AgentTaskStatus.COMPLETED)
        self.assertEqual({event.run_id for event in task_events}, {parent.run_id})
        self.assertEqual(observability.get_run(parent.run_id).status, RunStatus.RUNNING)
        observability.complete_run(parent.run_id)

    def test_agent_failure_marks_task_failed_and_preserves_normalized_result(self):
        class FailingAgent(BaseAgent):
            def run(self, context, *, event_sink=None):
                raise RuntimeError("sensitive execution detail")

        failing = FailingAgent(AgentDefinition(agent_id="failing", name="Failing"))
        self.registry.register(failing)
        sink = InMemoryEventSink()
        observability = ObservabilityService(sink)
        service = self.make_service(observability=observability)
        task = service.delegate("requester", agent_id="failing", payload={"user_input": "fail"})
        self.assertEqual(task.status, AgentTaskStatus.FAILED)
        self.assertEqual(task.error.code, "execution_failed")
        self.assertNotIn("sensitive execution detail", repr(task))
        self.assertEqual(task.result["status"], AgentExecutionStatus.FAILED.value)
        with self.assertRaises(ValidationError):
            task.error.code = "changed"
        self.assertEqual(
            [event.event_type for event in sink.events if event.component == "multi_agent"][-1],
            EventType.AGENT_TASK_FAILED,
        )

    def test_registry_instances_are_independent_and_package_keeps_phase_boundary(self):
        import ast
        from pathlib import Path

        other_registry = InMemoryAgentRegistry()
        self.assertEqual(other_registry.list(), ())
        package = Path(__file__).parents[1] / "app" / "multi_agent"
        forbidden = {"tools", "mcp", "rag", "memory", "planning", "reflection", "workflows"}
        for path in package.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app."):
                    imported.add(node.module.split(".")[1])
                elif isinstance(node, ast.Import):
                    imported.update(
                        alias.name.split(".")[1]
                        for alias in node.names
                        if alias.name.startswith("app.")
                    )
            self.assertTrue(forbidden.isdisjoint(imported), f"out-of-phase import in {path}")

    def test_a2a_failure_fails_task_and_emits_normalized_events(self):
        sink = InMemoryEventSink()
        observability = ObservabilityService(sink)

        class BrokenChannel:
            def send(self, message):
                raise A2ACommunicationError("private transport detail")

            def receive(self, recipient_agent_id, *, task_id):
                raise AssertionError("receive must not follow failed send")

        service = self.make_service(channel=BrokenChannel(), observability=observability)
        task = service.delegate("requester", agent_id="worker", payload={"user_input": "hello"})
        self.assertEqual(task.status, AgentTaskStatus.FAILED)
        self.assertEqual(task.error.code, "A2ACommunicationError")
        events = [event.event_type for event in sink.events]
        self.assertEqual(
            events,
            [
                EventType.AGENT_TASK_CREATED,
                EventType.AGENT_TASK_STARTED,
                EventType.A2A_MESSAGE_FAILED,
                EventType.AGENT_TASK_FAILED,
            ],
        )
        self.assertNotIn("hello", repr([event.metadata for event in sink.events]))
        self.assertNotIn("private transport detail", repr(sink.events))

    def test_observability_failure_is_fail_open(self):
        class BrokenSink:
            def write(self, event):
                raise OSError("telemetry unavailable")

        observability = ObservabilityService(BrokenSink())
        service = self.make_service(observability=observability)
        with self.assertLogs("app.observability.safe", level="ERROR"):
            task = service.delegate("requester", agent_id="worker", payload={"user_input": "hello"})
        self.assertEqual(task.status, AgentTaskStatus.COMPLETED)

    def test_registry_unregister_and_unknown_task_errors(self):
        from app.multi_agent import AgentNotFoundError, AgentTaskNotFoundError

        with self.assertRaises(AgentTaskNotFoundError):
            self.make_service().get_task("missing")
        self.registry.unregister("worker")
        with self.assertRaises(AgentNotFoundError):
            self.registry.get("worker")


if __name__ == "__main__":
    unittest.main()
