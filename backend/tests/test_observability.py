import asyncio
import contextvars
import threading
import unittest
from typing import Any

from pydantic import BaseModel

from app.agents import AgentContext, AgentDefinition, AgentRuntime, LLMAgent
from app.agents.base_agent import BaseAgent
from app.llm.manager import LLMManager
from app.llm.types import LLMRequest, LLMResponse, Message, MessageRole
from app.mcp import (
    MCPCallResult,
    MCPConnectionState,
    MCPToolBridge,
    MCPToolSpec,
)
from app.observability import (
    EventType,
    InMemoryEventSink,
    ObservabilityService,
    RunStatus,
    RunTransitionError,
    bind_run,
    current_run_id,
)
from app.tools import (
    AllowListToolPolicy,
    BaseTool,
    ToolExecutionContext,
    ToolGateway,
    ToolRegistry,
)


class EchoInput(BaseModel):
    value: str


class EchoTool(BaseTool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo a value."

    @property
    def input_model(self) -> type[BaseModel]:
        return EchoInput

    def execute(self, arguments: EchoInput, context: ToolExecutionContext) -> Any:
        return {"value": arguments.value}


class FailingTool(EchoTool):
    @property
    def name(self) -> str:
        return "failing"

    def execute(self, arguments: EchoInput, context: ToolExecutionContext) -> Any:
        raise RuntimeError("tool internals")


class FailingAgent(BaseAgent):
    def run(self, context, *, event_sink=None):
        raise RuntimeError("private error text")


class CallingAgent(BaseAgent):
    def __init__(self, definition, manager, gateway):
        super().__init__(definition)
        self.manager = manager
        self.gateway = gateway

    def run(self, context, *, event_sink=None):
        response = self.manager.generate(
            LLMRequest(
                model="fake-model",
                messages=[Message(role=MessageRole.USER, content=context.user_input)],
            )
        )
        self.gateway.invoke(
            "echo",
            {"value": context.user_input},
            ToolExecutionContext(
                agent_id=self.definition.agent_id,
                execution_id=context.user_input,
            ),
        )
        return response.content


class FakeMCPClient:
    def __init__(self, *, fail=False):
        self._state = MCPConnectionState.DISCONNECTED
        self.fail = fail

    @property
    def state(self):
        return self._state

    def connect(self):
        self._state = MCPConnectionState.CONNECTED

    def list_tools(self):
        return [
            MCPToolSpec(
                name="remote_echo",
                input_schema={"type": "object", "properties": {"value": {"type": "string"}}},
            )
        ]

    def call_tool(self, name, arguments):
        if self.fail:
            raise RuntimeError("private transport details")
        return MCPCallResult(output={"value": arguments["value"]})

    def close(self):
        self._state = MCPConnectionState.CLOSED


class ObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.sink = InMemoryEventSink()
        self.service = ObservabilityService(self.sink)

    def test_run_creation_completion_and_invalid_transition(self):
        run = self.service.start_run({"request_id": "req-1"})
        self.assertTrue(run.run_id)
        self.assertEqual(run.status, RunStatus.RUNNING)
        self.assertIsNone(run.ended_at)

        completed = self.service.complete_run(run.run_id)
        self.assertEqual(completed.status, RunStatus.COMPLETED)
        self.assertGreaterEqual(completed.ended_at, completed.started_at)
        with self.assertRaises(RunTransitionError):
            self.service.fail_run(run.run_id, RuntimeError("late failure"))
        with self.assertRaises(RunTransitionError):
            self.service.emit(EventType.AGENT_COMPLETED, "agent", run_id=run.run_id)

    def test_event_creation_correlation_order_and_failure_information(self):
        run = self.service.start_run()
        with bind_run(run):
            first = self.service.emit(EventType.AGENT_STARTED, "agent")
            second = self.service.emit(
                EventType.LLM_FAILED,
                "llm",
                error=RuntimeError("provider detail"),
            )
        self.assertNotEqual(first.event_id, second.event_id)
        self.assertEqual(first.run_id, run.run_id)
        self.assertEqual(second.run_id, run.run_id)
        events = self.sink.events_for_run(run.run_id)
        self.assertEqual([event.event_type for event in events], [EventType.AGENT_STARTED, EventType.LLM_FAILED])
        self.assertEqual(events[1].error.exception_type, "RuntimeError")
        self.assertIsNone(events[1].metadata.get("prompt"))
        self.service.fail_run(run.run_id, RuntimeError("provider detail"))
        failed_run = self.service.get_run(run.run_id)
        self.assertEqual(failed_run.status, RunStatus.FAILED)
        self.assertEqual(failed_run.error.exception_type, "RuntimeError")

    def test_agent_and_llm_lifecycle_share_a_run(self):
        provider = _FakeProvider()
        manager = LLMManager(provider=provider, observability=self.service)
        agent = LLMAgent(
            AgentDefinition(agent_id="agent-1", name="Test", model="fake-model"),
            manager,
        )
        result = AgentRuntime(observability=self.service).execute(
            agent, AgentContext(user_input="hello")
        )
        self.assertEqual(result.status.value, "completed")
        events = self.sink.events
        self.assertEqual(
            [event.event_type for event in events],
            [EventType.AGENT_STARTED, EventType.LLM_REQUEST, EventType.LLM_RESPONSE, EventType.AGENT_COMPLETED],
        )
        self.assertEqual(len({event.run_id for event in events}), 1)
        self.assertEqual(self.service.get_run(events[0].run_id).status, RunStatus.COMPLETED)
        self.assertNotIn("hello", repr(events))

    def test_agent_failure_emits_and_fails_run(self):
        agent = FailingAgent(AgentDefinition(agent_id="broken", name="Broken"))
        result = AgentRuntime(observability=self.service).execute(
            agent, AgentContext(user_input="hello")
        )
        self.assertEqual(result.status.value, "failed")
        self.assertEqual(self.sink.events[-1].event_type, EventType.AGENT_FAILED)
        self.assertEqual(self.sink.events[-1].error.exception_type, "AgentExecutionError")
        self.assertEqual(self.service.get_run(self.sink.events[-1].run_id).status, RunStatus.FAILED)

    def test_standalone_llm_failure_is_observed(self):
        manager = LLMManager(provider=_FakeProvider(fail=True), observability=self.service)
        with self.assertRaises(RuntimeError):
            manager.generate(LLMRequest(model="fake", messages=[]))
        self.assertEqual(
            [event.event_type for event in self.sink.events],
            [EventType.LLM_REQUEST, EventType.LLM_FAILED],
        )
        self.assertEqual(self.service.get_run(self.sink.events[0].run_id).status, RunStatus.FAILED)

    def test_tool_and_mcp_lifecycle_events(self):
        registry = ToolRegistry()
        registry.register(EchoTool())
        gateway = ToolGateway(
            registry,
            AllowListToolPolicy({"echo"}),
            observability=self.service,
        )
        result = gateway.invoke(
            "echo", {"value": "secret-input"},
            ToolExecutionContext(agent_id="a1", execution_id="exec-1"),
        )
        self.assertTrue(result.success)
        self.assertEqual(
            [event.event_type for event in self.sink.events],
            [EventType.TOOL_REQUEST, EventType.TOOL_COMPLETED],
        )
        self.assertNotIn("secret-input", repr(self.sink.events))

        sink = InMemoryEventSink()
        service = ObservabilityService(sink)
        mcp_registry = ToolRegistry()
        bridge = MCPToolBridge(
            "remote",
            FakeMCPClient(),
            mcp_registry,
            observability=service,
        )
        bridge.connect()
        bridge.discover_and_register()
        mcp_gateway = ToolGateway(
            mcp_registry,
            AllowListToolPolicy({"remote__remote_echo"}),
            observability=service,
        )
        mcp_gateway.invoke(
            "remote__remote_echo", {"value": "not-recorded"},
            ToolExecutionContext(agent_id="a1", execution_id="exec-2"),
        )
        self.assertEqual(
            [event.event_type for event in sink.events],
            [EventType.TOOL_REQUEST, EventType.MCP_REQUEST, EventType.MCP_COMPLETED, EventType.TOOL_COMPLETED],
        )
        self.assertEqual(len({event.run_id for event in sink.events}), 1)

    def test_mcp_failure_and_tool_failure_events(self):
        registry = ToolRegistry()
        bridge = MCPToolBridge("remote", FakeMCPClient(fail=True), registry, observability=self.service)
        bridge.connect()
        bridge.discover_and_register()
        gateway = ToolGateway(
            registry, AllowListToolPolicy({"remote__remote_echo"}), observability=self.service
        )
        result = gateway.invoke(
            "remote__remote_echo", {"value": "x"},
            ToolExecutionContext(agent_id="a1", execution_id="exec-3"),
        )
        self.assertFalse(result.success)
        self.assertEqual(
            [event.event_type for event in self.sink.events],
            [EventType.TOOL_REQUEST, EventType.MCP_REQUEST, EventType.MCP_FAILED, EventType.TOOL_FAILED],
        )
        self.assertEqual(
            self.service.get_run(self.sink.events[0].run_id).status,
            RunStatus.FAILED,
        )

    def test_standalone_tool_failure_fails_run_but_nested_failure_does_not(self):
        registry = ToolRegistry()
        registry.register(FailingTool())
        gateway = ToolGateway(
            registry,
            AllowListToolPolicy({"failing"}),
            observability=self.service,
        )
        result = gateway.invoke(
            "failing", {"value": "x"},
            ToolExecutionContext(agent_id="a1", execution_id="standalone-tool"),
        )
        self.assertFalse(result.success)
        standalone_run_id = self.sink.events[0].run_id
        self.assertEqual(self.sink.events[-1].event_type, EventType.TOOL_FAILED)
        self.assertEqual(self.service.get_run(standalone_run_id).status, RunStatus.FAILED)

        # A failed nested tool is an event; the parent agent owns the run outcome.
        agent_registry = ToolRegistry()
        agent_registry.register(FailingTool())
        nested_gateway = ToolGateway(
            agent_registry,
            AllowListToolPolicy({"failing"}),
            observability=self.service,
        )

        class HandlesToolFailure(BaseAgent):
            def run(self, context, *, event_sink=None):
                nested_gateway.invoke(
                    "failing",
                    {"value": "x"},
                    ToolExecutionContext(
                        agent_id=self.definition.agent_id,
                        execution_id="nested-tool",
                    ),
                )
                return "handled"

        agent_result = AgentRuntime(observability=self.service).execute(
            HandlesToolFailure(AgentDefinition(agent_id="a2", name="A2")),
            AgentContext(user_input="run"),
        )
        self.assertEqual(agent_result.status.value, "completed")
        nested_run_id = agent_result.metadata["run_id"]
        self.assertEqual(self.service.get_run(nested_run_id).status, RunStatus.COMPLETED)
        self.assertIn(
            EventType.TOOL_FAILED,
            [event.event_type for event in self.sink.events_for_run(nested_run_id)],
        )

    def test_concurrent_agent_runs_keep_llm_and_tool_events_isolated(self):
        barrier = threading.Barrier(2)
        provider_runs = {}
        provider_lock = threading.Lock()

        class ConcurrentProvider:
            provider_name = "concurrent-fake"

            def generate(self, request):
                marker = request.messages[-1].content
                observed_run_id = current_run_id()
                with provider_lock:
                    provider_runs[marker] = observed_run_id
                barrier.wait(timeout=5)
                return LLMResponse(content=marker, provider=self.provider_name)

        manager = LLMManager(
            provider=ConcurrentProvider(),
            observability=self.service,
        )
        registry = ToolRegistry()
        registry.register(EchoTool())
        gateway = ToolGateway(
            registry,
            AllowListToolPolicy({"echo"}),
            observability=self.service,
        )
        runtime = AgentRuntime(observability=self.service)
        agents = {
            "agent-a": CallingAgent(
                AgentDefinition(agent_id="agent-a", name="Agent A"), manager, gateway
            ),
            "agent-b": CallingAgent(
                AgentDefinition(agent_id="agent-b", name="Agent B"), manager, gateway
            ),
        }

        async def execute(agent_id):
            return await asyncio.to_thread(
                runtime.execute,
                agents[agent_id],
                AgentContext(user_input=agent_id),
            )

        async def execute_both():
            return await asyncio.gather(execute("agent-a"), execute("agent-b"))

        results = asyncio.run(execute_both())
        runs_by_agent = {
            result.output: result.metadata["run_id"] for result in results
        }
        self.assertEqual(provider_runs, runs_by_agent)

        for agent_id, run_id in runs_by_agent.items():
            events = self.sink.events_for_run(run_id)
            self.assertEqual(
                [event.event_type for event in events],
                [
                    EventType.AGENT_STARTED,
                    EventType.LLM_REQUEST,
                    EventType.LLM_RESPONSE,
                    EventType.TOOL_REQUEST,
                    EventType.TOOL_COMPLETED,
                    EventType.AGENT_COMPLETED,
                ],
            )
            tool_events = [event for event in events if event.component == "tool"]
            self.assertTrue(all(event.metadata["agent_id"] == agent_id for event in tool_events))
        self.assertEqual(
            {event.run_id for event in self.sink.events}, set(runs_by_agent.values())
        )

    def test_context_free_background_call_creates_its_own_run(self):
        parent = self.service.start_run({"entry_component": "agent"})
        manager = LLMManager(provider=_FakeProvider(), observability=self.service)
        empty_context = contextvars.Context()
        results = []
        with bind_run(parent):
            self.assertEqual(current_run_id(), parent.run_id)
            worker = threading.Thread(
                target=lambda: results.append(
                    empty_context.run(
                        manager.generate,
                        LLMRequest(model="fake", messages=[]),
                    )
                )
            )
            worker.start()
            worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0].content, "ok")
        event_run_ids = {event.run_id for event in self.sink.events}
        self.assertEqual(len(event_run_ids), 1)
        background_run_id = event_run_ids.pop()
        self.assertNotEqual(background_run_id, parent.run_id)
        self.assertEqual(self.service.get_run(background_run_id).status, RunStatus.COMPLETED)
        self.assertEqual(self.sink.events_for_run(parent.run_id), [])

    def test_fail_open_when_sink_raises(self):
        class BrokenSink:
            def write(self, event):
                raise OSError("sink unavailable")

        service = ObservabilityService(BrokenSink())
        provider = _FakeProvider()
        manager = LLMManager(provider=provider, observability=service)
        with self.assertLogs("app.observability.safe", level="ERROR"):
            result = manager.generate(LLMRequest(model="fake", messages=[]))
        self.assertEqual(result.content, "ok")


class _FakeProvider:
    provider_name = "fake"

    def __init__(self, fail=False):
        self.fail = fail

    def generate(self, request):
        if self.fail:
            raise RuntimeError("private provider message")
        return LLMResponse(content="ok", provider="fake", model=request.model)


if __name__ == "__main__":
    unittest.main()
