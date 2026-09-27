import unittest

from pydantic import BaseModel

from app.agents.runtime import AgentRuntime
from app.tools import (
    AllowListToolPolicy,
    BaseTool,
    ToolDefinition,
    ToolErrorCode,
    ToolExecutionContext,
    ToolGateway,
    ToolRegistry,
    ToolResult,
)
from app.tools.exceptions import DuplicateToolError


class AddInput(BaseModel):
    left: int
    right: int


class AddOutput(BaseModel):
    total: int


class AddTool(BaseTool):
    name = "add"
    description = "Add two integers."
    input_model = AddInput
    output_model = AddOutput

    def execute(self, arguments: AddInput, context: ToolExecutionContext):
        return AddOutput(total=arguments.left + arguments.right)


class BrokenTool(AddTool):
    name = "broken"

    def execute(self, arguments: AddInput, context: ToolExecutionContext):
        raise RuntimeError("private implementation details")


def make_gateway(*, allowed_tools=None, max_invocations=10):
    registry = ToolRegistry()
    registry.register(AddTool())
    return ToolGateway(
        registry,
        AllowListToolPolicy({"add"} if allowed_tools is None else allowed_tools),
        max_invocations_per_execution=max_invocations,
    )


def context(agent_id="agent-1", execution_id="exec-1"):
    return ToolExecutionContext(agent_id=agent_id, execution_id=execution_id)


class ToolSystemTests(unittest.TestCase):
    def test_tool_definition_exposes_provider_neutral_schemas(self):
        definition = AddTool().definition
        self.assertIsInstance(definition, ToolDefinition)
        self.assertEqual(definition.name, "add")
        self.assertEqual(definition.input_schema["title"], "AddInput")
        self.assertEqual(definition.output_schema["title"], "AddOutput")
        self.assertNotIn("google.genai", repr(definition.model_dump()))

    def test_registry_register_lookup_and_list(self):
        registry = ToolRegistry()
        tool = AddTool()
        registry.register(tool)
        self.assertIs(registry.get("add"), tool)
        self.assertEqual(registry.list_tools(), [tool])
        self.assertEqual(registry.list_definitions()[0].name, "add")

    def test_registry_rejects_duplicate_registration(self):
        registry = ToolRegistry()
        registry.register(AddTool())
        with self.assertRaises(DuplicateToolError):
            registry.register(AddTool())

    def test_valid_input_executes_and_result_is_json_normalized(self):
        result = make_gateway().invoke(
            "add", {"left": 4, "right": 7}, context()
        )
        self.assertTrue(result.success)
        self.assertEqual(result.output, {"total": 11})
        self.assertIsNone(result.error)
        self.assertIn("duration_ms", result.metadata)

    def test_invalid_input_does_not_reach_tool(self):
        result = make_gateway().invoke("add", {"left": "bad"}, context())
        self.assertFalse(result.success)
        self.assertEqual(result.error.code, ToolErrorCode.INVALID_INPUT)
        self.assertEqual(result.error.cause_type, "ValidationError")

    def test_unknown_tool_returns_normalized_failure(self):
        result = make_gateway().invoke("missing", {}, context())
        self.assertEqual(result.error.code, ToolErrorCode.TOOL_NOT_FOUND)

    def test_allowlist_policy_denies_tool_and_agent_by_default(self):
        gateway = make_gateway(allowed_tools=set())
        result = gateway.invoke("add", {"left": 1, "right": 2}, context())
        self.assertEqual(result.error.code, ToolErrorCode.FORBIDDEN)

        restricted_registry = ToolRegistry()
        restricted_registry.register(AddTool())
        agent_restricted = ToolGateway(
            restricted_registry,
            AllowListToolPolicy({"add"}, allowed_agents={"trusted-agent"}),
        )
        denied = agent_restricted.invoke(
            "add", {"left": 1, "right": 2}, context(agent_id="other")
        )
        self.assertEqual(denied.error.code, ToolErrorCode.FORBIDDEN)

    def test_policy_failure_is_fail_closed(self):
        class BrokenPolicy:
            def is_allowed(self, definition, execution_context):
                raise RuntimeError("policy unavailable")

        registry = ToolRegistry()
        registry.register(AddTool())
        result = ToolGateway(registry, BrokenPolicy()).invoke(
            "add", {"left": 1, "right": 2}, context()
        )
        self.assertEqual(result.error.code, ToolErrorCode.FORBIDDEN)
        self.assertEqual(result.error.cause_type, "RuntimeError")

    def test_tool_exception_is_normalized_without_leaking_message(self):
        registry = ToolRegistry()
        registry.register(BrokenTool())
        gateway = ToolGateway(registry, AllowListToolPolicy({"broken"}))
        result = gateway.invoke("broken", {"left": 1, "right": 2}, context())
        self.assertEqual(result.error.code, ToolErrorCode.EXECUTION_FAILED)
        self.assertEqual(result.error.message, "Tool execution failed.")
        self.assertEqual(result.error.cause_type, "RuntimeError")
        self.assertNotIn("private implementation", result.error.message)

    def test_non_json_output_becomes_normalized_failure(self):
        class UnsafeTool(AddTool):
            name = "unsafe"

            def execute(self, arguments: AddInput, execution_context: ToolExecutionContext):
                return object()

        registry = ToolRegistry()
        registry.register(UnsafeTool())
        result = ToolGateway(registry, AllowListToolPolicy({"unsafe"})).invoke(
            "unsafe", {"left": 1, "right": 2}, context()
        )
        self.assertEqual(result.error.code, ToolErrorCode.EXECUTION_FAILED)

    def test_per_execution_invocation_budget(self):
        gateway = make_gateway(max_invocations=1)
        execution_context = context()
        first = gateway.invoke("add", {"left": 1, "right": 2}, execution_context)
        second = gateway.invoke("add", {"left": 3, "right": 4}, execution_context)
        self.assertTrue(first.success)
        self.assertEqual(second.error.code, ToolErrorCode.INVOCATION_LIMIT)
        self.assertTrue(
            gateway.invoke("add", {"left": 1, "right": 2}, context(execution_id="exec-2")).success
        )

    def test_tool_result_requires_consistent_success_and_error_fields(self):
        self.assertTrue(ToolResult.succeeded({"ok": True}).success)
        self.assertFalse(
            ToolResult.failed(ToolErrorCode.FORBIDDEN, "denied").success
        )
        with self.assertRaises(ValueError):
            ToolResult(success=True, error={"code": "forbidden", "message": "no"})

    def test_agent_runtime_accepts_tool_gateway_by_dependency_injection(self):
        gateway = make_gateway()
        runtime = AgentRuntime(tool_gateway=gateway)
        self.assertIs(runtime.tool_gateway, gateway)


if __name__ == "__main__":
    unittest.main()
