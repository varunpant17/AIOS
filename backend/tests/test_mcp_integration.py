import os
import subprocess
import sys
import unittest

from mcp import Client
from mcp.server import MCPServer

from app.mcp import (
    MCPCallResult,
    MCPConnectionState,
    MCPServerConfig,
    MCPToolBridge,
    MCPToolSpec,
    SDKStdioMCPClient,
)
from app.mcp.errors import (
    MCPConnectionFailure,
    MCPDiscoveryFailure,
    MCPInvalidResponseFailure,
    MCPInvocationFailure,
    MCPTimeoutFailure,
)
from app.tools import (
    AllowListToolPolicy,
    ToolErrorCode,
    ToolExecutionContext,
    ToolGateway,
    ToolRegistry,
)
from app.tools.exceptions import DuplicateToolError


class FakeMCPClient:
    def __init__(self, tools=None, *, call_result=None, call_error=None, list_error=None):
        self._tools = tools or [
            MCPToolSpec(
                name="echo value",
                description="Return the supplied value.",
                input_schema={
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
            )
        ]
        self._call_result = call_result or MCPCallResult(output={"echo": "ok"})
        self._call_error = call_error
        self._list_error = list_error
        self._state = MCPConnectionState.DISCONNECTED
        self.calls = []

    @property
    def state(self):
        return self._state

    def connect(self):
        if self._state == MCPConnectionState.CLOSED:
            raise MCPConnectionFailure("closed")
        self._state = MCPConnectionState.CONNECTED

    def list_tools(self):
        if self._state != MCPConnectionState.CONNECTED:
            raise MCPConnectionFailure("not connected")
        if self._list_error:
            raise self._list_error
        return list(self._tools)

    def call_tool(self, name, arguments):
        if self._state != MCPConnectionState.CONNECTED:
            raise MCPConnectionFailure("not connected")
        self.calls.append((name, arguments))
        if self._call_error:
            raise self._call_error
        return self._call_result

    def close(self):
        self._state = MCPConnectionState.CLOSED


class MCPIntegrationTests(unittest.TestCase):
    def test_sdk_client_is_constructed_without_connecting_or_import_side_effect(self):
        config = MCPServerConfig(server_name="calculator", command="unused-test-command")
        client = SDKStdioMCPClient(config)
        self.assertEqual(client.state, MCPConnectionState.DISCONNECTED)
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import app.mcp; "
                "assert 'mcp' not in sys.modules",
            ],
            check=True,
            env=os.environ.copy(),
        )

    def test_official_sdk_in_process_server_lifecycle_discovery_and_gateway_call(self):
        server = MCPServer(name="local-calculator")

        @server.tool()
        def add(left: int, right: int) -> dict[str, int]:
            return {"total": left + right}

        config = MCPServerConfig(server_name="calc", command="unused-in-process")
        client = SDKStdioMCPClient(
            config,
            client_factory=lambda _config: Client(server, raise_exceptions=True),
        )
        registry = ToolRegistry()
        bridge = MCPToolBridge("calc", client, registry)

        self.assertEqual(bridge.state, MCPConnectionState.DISCONNECTED)
        bridge.connect()
        self.assertEqual(bridge.state, MCPConnectionState.CONNECTED)
        self.assertEqual(registry.list_tools(), [])
        definitions = bridge.discover_and_register()
        self.assertEqual([item.name for item in definitions], ["calc__add"])
        self.assertEqual(registry.list_definitions()[0].input_schema["type"], "object")

        gateway = ToolGateway(
            registry,
            AllowListToolPolicy({"calc__add"}, allowed_agents={"agent-a"}),
        )
        result = gateway.invoke(
            "calc__add",
            {"left": 6, "right": 7},
            ToolExecutionContext(agent_id="agent-a", execution_id="run-1"),
        )
        self.assertTrue(result.success)
        self.assertEqual(result.output, {"total": 13})
        bridge.close()
        self.assertEqual(bridge.state, MCPConnectionState.CLOSED)
        bridge.close()

    def test_discovery_converts_specs_and_registers_atomically(self):
        client = FakeMCPClient()
        registry = ToolRegistry()
        bridge = MCPToolBridge("remote", client, registry)
        with self.assertRaises(MCPConnectionFailure):
            bridge.discover_and_register()
        bridge.connect()
        definitions = bridge.discover_and_register()
        self.assertEqual(definitions[0].name, "remote__echo_value")
        self.assertEqual(definitions[0].metadata["mcp_tool"], "echo value")
        self.assertEqual(registry.list_tools()[0].name, "remote__echo_value")

    def test_gateway_validation_policy_and_budget_remain_in_force(self):
        client = FakeMCPClient()
        registry = ToolRegistry()
        bridge = MCPToolBridge("remote", client, registry)
        bridge.connect()
        bridge.discover_and_register()
        gateway = ToolGateway(
            registry,
            AllowListToolPolicy({"remote__echo_value"}, allowed_agents={"agent-a"}),
            max_invocations_per_execution=1,
        )
        context = ToolExecutionContext(agent_id="agent-a", execution_id="run-1")

        invalid = gateway.invoke("remote__echo_value", {"value": 42}, context)
        self.assertEqual(invalid.error.code, ToolErrorCode.INVALID_INPUT)
        self.assertEqual(client.calls, [])

        success = gateway.invoke("remote__echo_value", {"value": "hi"}, context)
        self.assertTrue(success.success)
        self.assertEqual(client.calls, [("echo value", {"value": "hi"})])
        exhausted = gateway.invoke("remote__echo_value", {"value": "again"}, context)
        self.assertEqual(exhausted.error.code, ToolErrorCode.INVOCATION_LIMIT)

        denied = gateway.invoke(
            "remote__echo_value",
            {"value": "no"},
            ToolExecutionContext(agent_id="other", execution_id="run-2"),
        )
        self.assertEqual(denied.error.code, ToolErrorCode.FORBIDDEN)

    def test_mcp_tool_error_and_transport_failures_are_normalized(self):
        tool = MCPToolSpec(
            name="echo",
            input_schema={"type": "object", "properties": {}},
        )
        for client_error, expected_code in (
            (MCPInvocationFailure("secret SDK text"), ToolErrorCode.MCP_INVOCATION_FAILED),
            (MCPTimeoutFailure("secret timeout text"), ToolErrorCode.TIMEOUT),
            (MCPConnectionFailure("secret connection text"), ToolErrorCode.MCP_CONNECTION_FAILED),
            (MCPInvalidResponseFailure("secret response text"), ToolErrorCode.INVALID_MCP_RESPONSE),
            (MCPDiscoveryFailure("secret discovery text"), ToolErrorCode.MCP_DISCOVERY_FAILED),
        ):
            client = FakeMCPClient(tools=[tool], call_error=client_error)
            registry = ToolRegistry()
            bridge = MCPToolBridge("remote", client, registry)
            bridge.connect()
            bridge.discover_and_register()
            result = ToolGateway(
                registry,
                AllowListToolPolicy({"remote__echo"}),
            ).invoke(
                "remote__echo",
                {},
                ToolExecutionContext(agent_id="a", execution_id="r"),
            )
            with self.subTest(expected=expected_code):
                self.assertEqual(result.error.code, expected_code)
                self.assertNotIn("secret", result.error.message)

        client = FakeMCPClient(tools=[tool], call_result=MCPCallResult(is_error=True))
        registry = ToolRegistry()
        bridge = MCPToolBridge("remote", client, registry)
        bridge.connect()
        bridge.discover_and_register()
        result = ToolGateway(registry, AllowListToolPolicy({"remote__echo"})).invoke(
            "remote__echo", {}, ToolExecutionContext(agent_id="a", execution_id="r")
        )
        self.assertEqual(result.error.code, ToolErrorCode.MCP_INVOCATION_FAILED)

    def test_invalid_mcp_schema_response_is_rejected_during_adaptation(self):
        invalid = MCPToolSpec.model_construct(
            name="bad", description="bad schema", input_schema={"type": "string"}
        )
        client = FakeMCPClient(tools=[invalid])
        registry = ToolRegistry()
        bridge = MCPToolBridge("remote", client, registry)
        bridge.connect()
        with self.assertRaises(MCPInvalidResponseFailure):
            bridge.discover_and_register()
        self.assertEqual(registry.list_tools(), [])

    def test_registry_duplicate_discovery_is_atomic(self):
        client = FakeMCPClient()
        registry = ToolRegistry()
        first = MCPToolBridge("remote", client, registry)
        first.connect()
        first.discover_and_register()

        another_client = FakeMCPClient()
        second = MCPToolBridge("remote", another_client, registry)
        second.connect()
        with self.assertRaises(DuplicateToolError):
            second.discover_and_register()
        self.assertEqual(len(registry.list_tools()), 1)

    def test_aios_contracts_do_not_retain_sdk_objects(self):
        client = FakeMCPClient()
        registry = ToolRegistry()
        bridge = MCPToolBridge("remote", client, registry)
        bridge.connect()
        bridge.discover_and_register()
        definition = registry.list_definitions()[0]
        result = ToolGateway(registry, AllowListToolPolicy({definition.name})).invoke(
            definition.name,
            {"value": "x"},
            ToolExecutionContext(agent_id="a", execution_id="r"),
        )
        self.assertIsInstance(definition, __import__("app.tools.types", fromlist=["ToolDefinition"]).ToolDefinition)
        self.assertIsInstance(result, __import__("app.tools.types", fromlist=["ToolResult"]).ToolResult)
        self.assertNotIn("mcp.", repr(definition.model_dump()))
        self.assertNotIn("mcp.", repr(result.model_dump()))


if __name__ == "__main__":
    unittest.main()
