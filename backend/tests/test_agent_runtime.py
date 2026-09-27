import subprocess
import sys
import unittest
from unittest.mock import Mock

from app.agents import (
    AgentContext,
    AgentDefinition,
    AgentEventType,
    AgentExecutionStatus,
    AgentRuntime,
    AgentState,
    LLMAgent,
)
from app.agents.exceptions import AgentInputError, AgentStateTransitionError
from app.llm.exceptions import LLMInvalidRequestError
from app.llm.types import LLMRequest, LLMResponse, MessageRole


class AgentRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.definition = AgentDefinition(
            agent_id="support-agent",
            name="Support",
            description="Answers support questions",
            model="offline-model",
            system_instructions="Answer clearly.",
            metadata={"team": "support"},
        )
        self.context = AgentContext(
            goal="Resolve the user's issue",
            user_input="Why did my job fail?",
            request_id="request-123",
            metadata={"source": "test"},
        )
        self.manager = Mock()
        self.manager.generate.return_value = LLMResponse(
            content="Check the job logs.", provider="fake", model="offline-model"
        )
        self.agent = LLMAgent(self.definition, self.manager)
        self.runtime = AgentRuntime()

    def test_agent_definition_and_context_capture_execution_configuration(self):
        self.assertEqual(self.definition.agent_id, "support-agent")
        self.assertEqual(self.definition.name, "Support")
        self.assertEqual(self.context.goal, "Resolve the user's issue")
        self.assertEqual(self.context.request_id, "request-123")
        self.assertEqual(self.context.data, {})

    def test_agent_state_starts_created(self):
        state = AgentState(agent_id=self.definition.agent_id)
        self.assertEqual(state.status, AgentExecutionStatus.CREATED)
        self.assertEqual(state.iteration, 0)
        self.assertIsNone(state.result)
        self.assertIsNone(state.error)

    def test_state_transitions_enforce_lifecycle(self):
        state = AgentState(agent_id=self.definition.agent_id)
        state.transition(AgentExecutionStatus.RUNNING)
        state.transition(AgentExecutionStatus.COMPLETED)
        self.assertEqual(state.status, AgentExecutionStatus.COMPLETED)
        with self.assertRaises(AgentStateTransitionError):
            state.transition(AgentExecutionStatus.FAILED)

    def test_created_cannot_transition_directly_to_completed(self):
        state = AgentState(agent_id=self.definition.agent_id)
        with self.assertRaises(AgentStateTransitionError):
            state.transition(AgentExecutionStatus.COMPLETED)

    def test_runtime_executes_and_normalizes_result_and_state(self):
        result = self.runtime.execute(
            self.agent, self.context, execution_id="exec-123"
        )

        state = self.runtime.get_state("exec-123")
        self.assertEqual(result.execution_id, state.execution_id)
        self.assertEqual(result.agent_id, "support-agent")
        self.assertEqual(result.status, AgentExecutionStatus.COMPLETED)
        self.assertEqual(result.output, "Check the job logs.")
        self.assertEqual(result.metadata["request_id"], "request-123")
        self.assertEqual(state.status, AgentExecutionStatus.COMPLETED)
        self.assertEqual(state.iteration, 1)
        self.assertEqual(state.result, result.output)
        self.assertEqual(
            [event.type for event in state.events],
            [
                AgentEventType.EXECUTION_STARTED,
                AgentEventType.LLM_INVOKED,
                AgentEventType.EXECUTION_COMPLETED,
            ],
        )

    def test_llm_manager_is_injected_and_receives_normalized_request(self):
        self.runtime.execute(self.agent, self.context)

        self.manager.generate.assert_called_once()
        request = self.manager.generate.call_args.args[0]
        self.assertIsInstance(request, LLMRequest)
        self.assertEqual(request.model, "offline-model")
        self.assertEqual(request.messages[0].role, MessageRole.SYSTEM)
        self.assertEqual(request.messages[0].content, "Answer clearly.")
        self.assertEqual(request.messages[1].content, "Execution goal: Resolve the user's issue")
        self.assertEqual(request.messages[-1].content, self.context.user_input)

    def test_llm_failure_becomes_agent_level_failed_result_and_state(self):
        self.manager.generate.side_effect = LLMInvalidRequestError("bad request")

        result = self.runtime.execute(self.agent, self.context, execution_id="failed-1")

        state = self.runtime.get_state("failed-1")
        self.assertEqual(result.status, AgentExecutionStatus.FAILED)
        self.assertEqual(result.error.code, "llm_error")
        self.assertEqual(result.error.exception_type, "AgentLLMError")
        self.assertEqual(result.error.cause_type, "LLMInvalidRequestError")
        self.assertEqual(state.status, AgentExecutionStatus.FAILED)
        self.assertEqual(state.error, result.error)
        self.assertEqual(state.events[-1].type, AgentEventType.EXECUTION_FAILED)

    def test_unexpected_agent_failure_is_normalized(self):
        self.manager.generate.side_effect = RuntimeError("implementation detail")

        result = self.runtime.execute(self.agent, self.context)

        self.assertEqual(result.status, AgentExecutionStatus.FAILED)
        self.assertEqual(result.error.code, "execution_failed")
        self.assertEqual(result.error.message, "Agent execution failed.")

    def test_empty_input_and_duplicate_execution_id_are_rejected(self):
        with self.assertRaises(AgentInputError):
            self.runtime.execute(self.agent, AgentContext(user_input=" "))

        self.runtime.execute(self.agent, self.context, execution_id="same-id")
        with self.assertRaises(AgentInputError):
            self.runtime.execute(self.agent, self.context, execution_id="same-id")

    def test_unknown_execution_id_is_rejected(self):
        with self.assertRaises(AgentInputError):
            self.runtime.get_state("missing")

    def test_execution_ids_are_generated_when_not_provided(self):
        result = self.runtime.execute(self.agent, self.context)
        state = self.runtime.get_state(result.execution_id)
        self.assertTrue(result.execution_id)
        self.assertEqual(result.execution_id, state.execution_id)

    def test_injected_manager_avoids_provider_sdk_dependency(self):
        self.assertEqual(self.runtime.execute(self.agent, self.context).output, "Check the job logs.")
        self.assertNotIn("google.genai", self.manager.generate.call_args.args[0].__class__.__module__)

        subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from app.agents import AgentRuntime; "
                "assert 'google.genai' not in sys.modules",
            ],
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
