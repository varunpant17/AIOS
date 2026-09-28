import ast
import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from app.observability import (
    EventType,
    InMemoryEventSink,
    ObservabilityService,
    RunStatus,
    bind_run,
)
from app.planning import Plan, PlanStep
from app.workflows import (
    DeterministicStepExecutor,
    DuplicateWorkflowError,
    InMemoryWorkflowStore,
    InvalidWorkflowError,
    InvalidWorkflowTransitionError,
    StepErrorInfo,
    StepResult,
    WorkflowConcurrencyError,
    WorkflowExecutionError,
    WorkflowNotFoundError,
    WorkflowService,
    WorkflowStatus,
    WorkflowStep,
    WorkflowStepStatus,
)


def make_plan(step_count=2):
    return Plan(
        plan_id="plan-1",
        goal="Prepare a release",
        steps=tuple(
            PlanStep(
                step_id=f"source-{index}",
                position=index,
                description=f"Step {index}",
                action=f"action-{index}",
                metadata={"ordinal": index},
            )
            for index in range(step_count)
        ),
        metadata={"plan_tag": "release"},
    )


def make_success(*, metadata=None, output=None):
    return StepResult(success=True, output=output, metadata=metadata or {})


def make_failure(code="step_failed"):
    return StepResult(
        success=False,
        error=StepErrorInfo(
            code=code,
            message="Controlled step failure.",
            exception_type="ControlledFailure",
        ),
    )


class RecordingExecutor:
    def __init__(self, outcomes=None):
        self.outcomes = outcomes or {}
        self.calls = []
        self.contexts = []

    def execute(self, step, context):
        self.calls.append(step.source_step_id)
        self.contexts.append(context)
        return self.outcomes.get(step.source_step_id, make_success())


class WorkflowFoundationTests(unittest.TestCase):
    def test_domain_validation_lifecycle_order_utc_and_immutable_metadata(self):
        store = InMemoryWorkflowStore()
        workflow = WorkflowService(
            store, DeterministicStepExecutor({"source-0": make_success(), "source-1": make_success()})
        ).create(make_plan(), metadata={"nested": {"labels": ["safe"]}})
        self.assertEqual(workflow.status, WorkflowStatus.PENDING)
        self.assertEqual([step.position for step in workflow.steps], [0, 1])
        with self.assertRaises(TypeError):
            workflow.metadata["nested"]["labels"].append("mutate")
        with self.assertRaises(ValidationError):
            workflow.model_copy(update={"plan_id": " "})
        with self.assertRaises(ValidationError):
            workflow.model_copy(update={"steps": tuple(reversed(workflow.steps))})
        with self.assertRaises(ValidationError):
            workflow.model_copy(update={"started_at": datetime(2025, 1, 1)})
        with self.assertRaises(ValidationError):
            workflow.model_copy(update={"start_event_emitted": True})
        before_created = workflow.created_at - timedelta(seconds=1)
        with self.assertRaises(ValidationError):
            workflow.model_copy(
                update={"status": WorkflowStatus.RUNNING, "started_at": before_created}
            )
        with self.assertRaises(ValidationError):
            workflow.model_copy(
                update={
                    "status": WorkflowStatus.COMPLETED,
                    "started_at": workflow.created_at + timedelta(seconds=2),
                    "completed_at": workflow.created_at + timedelta(seconds=1),
                    "steps": tuple(
                        step.model_copy(
                            update={
                                "status": WorkflowStepStatus.COMPLETED,
                                "started_at": workflow.created_at,
                                "completed_at": workflow.created_at + timedelta(seconds=1),
                                "result": make_success(),
                            }
                        )
                        for step in workflow.steps
                    ),
                }
            )
        with self.assertRaises(ValidationError):
            WorkflowStep(
                source_step_id="source",
                position=0,
                description="Run",
                action="run",
                status=WorkflowStepStatus.COMPLETED,
            )
        self.assertTrue(workflow.created_at.tzinfo is UTC)

    def test_step_result_requires_consistent_outcome_and_detaches_data(self):
        payload = {"items": ["before"]}
        result = make_success(output=payload)
        payload["items"].append("after")
        self.assertEqual(result.output, {"items": ["before"]})
        with self.assertRaises(TypeError):
            result.output["items"].append("mutate")
        with self.assertRaises(ValidationError):
            StepResult(success=False)
        with self.assertRaises(ValidationError):
            StepResult(success=True, error=make_failure().error)

    def test_store_create_get_update_delete_missing_duplicate_and_copies(self):
        store = InMemoryWorkflowStore()
        executor = RecordingExecutor()
        service = WorkflowService(store, executor)
        created = service.create(make_plan())
        first = store.get(created.workflow_id)
        second = store.get(created.workflow_id)
        self.assertIsNot(first, second)
        self.assertIsNot(first.steps[0], second.steps[0])
        with self.assertRaises(DuplicateWorkflowError):
            store.create(created)
        with self.assertRaises(WorkflowNotFoundError):
            store.get("missing")
        with self.assertRaises(WorkflowNotFoundError):
            missing = created.model_copy(
                update={
                    "workflow_id": "missing",
                    "context": created.context.model_copy(update={"workflow_id": "missing"}),
                }
            )
            store.update(missing, expected_version=0)
        with self.assertRaises(WorkflowNotFoundError):
            store.delete("missing")
        updated = created.model_copy(update={"metadata": {"updated": True}})
        stored = store.update(updated, expected_version=0)
        self.assertEqual(stored.metadata["updated"], True)
        self.assertEqual(stored.version, 1)
        self.assertNotIn("updated", created.metadata)
        self.assertEqual(store.get(created.workflow_id).metadata["updated"], True)
        store.delete(created.workflow_id)
        with self.assertRaises(WorkflowNotFoundError):
            store.get(created.workflow_id)

    def test_store_rejects_stale_version_update(self):
        store = InMemoryWorkflowStore()
        workflow = WorkflowService(store, RecordingExecutor()).create(make_plan(1))
        first = workflow.model_copy(update={"metadata": {"writer": "first"}})
        stale = workflow.model_copy(update={"metadata": {"writer": "stale"}})
        store.update(first, expected_version=workflow.version)
        with self.assertRaises(WorkflowConcurrencyError):
            store.update(stale, expected_version=workflow.version)

    def test_store_duplicate_creation_is_thread_safe(self):
        store = InMemoryWorkflowStore()
        workflow = WorkflowService(InMemoryWorkflowStore(), RecordingExecutor()).create(make_plan(1))
        barrier = threading.Barrier(2)
        results = []

        def create_same():
            barrier.wait()
            try:
                store.create(workflow)
                results.append("created")
            except DuplicateWorkflowError:
                results.append("duplicate")

        threads = [threading.Thread(target=create_same) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
        self.assertCountEqual(results, ["created", "duplicate"])

    def test_store_rejects_skipped_lifecycle_updates_even_when_model_shape_is_valid(self):
        store = InMemoryWorkflowStore()
        workflow = WorkflowService(store, RecordingExecutor()).create(make_plan())
        now = workflow.created_at + timedelta(seconds=1)
        completed_steps = tuple(
            step.model_copy(update={
                "status": WorkflowStepStatus.COMPLETED,
                "started_at": workflow.created_at,
                "completed_at": now,
                "result": make_success(),
            })
            for step in workflow.steps
        )
        invalid_completed = workflow.model_copy(update={
            "status": WorkflowStatus.COMPLETED,
            "started_at": workflow.created_at,
            "completed_at": now,
            "steps": completed_steps,
        })
        with self.assertRaises(InvalidWorkflowTransitionError):
            store.update(invalid_completed, expected_version=workflow.version)

        failed_steps = (
            workflow.steps[0].model_copy(update={
                "status": WorkflowStepStatus.FAILED,
                "started_at": workflow.created_at,
                "completed_at": now,
                "result": make_failure(),
            }),
            workflow.steps[1],
        )
        invalid_failed = workflow.model_copy(update={
            "status": WorkflowStatus.FAILED,
            "started_at": workflow.created_at,
            "completed_at": now,
            "steps": failed_steps,
        })
        with self.assertRaises(InvalidWorkflowTransitionError):
            store.update(invalid_failed, expected_version=workflow.version)

        cancelled_steps = tuple(
            step.model_copy(update={
                "status": WorkflowStepStatus.CANCELLED,
                "completed_at": now,
            })
            for step in workflow.steps
        )
        invalid_cancelled = workflow.model_copy(update={
            "status": WorkflowStatus.CANCELLED,
            "completed_at": now,
            "steps": cancelled_steps,
        })
        with self.assertRaises(InvalidWorkflowTransitionError):
            store.update(invalid_cancelled, expected_version=workflow.version)

    def test_two_services_sharing_store_claim_a_workflow_only_once(self):
        store = InMemoryWorkflowStore()
        initial = WorkflowService(store, RecordingExecutor()).create(make_plan(1))
        barrier = threading.Barrier(2)
        count_lock = threading.Lock()
        calls = []
        outcomes = []
        attempts = []
        both_attempted = threading.Event()
        second_rejected = threading.Event()
        executor_entered = threading.Event()
        release_executor = threading.Event()

        class CountingExecutor:
            def execute(self, step, context):
                with count_lock:
                    calls.append(step.source_step_id)
                executor_entered.set()
                if not release_executor.wait(timeout=3):
                    raise TimeoutError("concurrency test executor gate timed out")
                return make_success()

        services = [WorkflowService(store, CountingExecutor()) for _ in range(2)]

        def execute(service):
            barrier.wait(timeout=2)
            with count_lock:
                attempts.append(service)
                if len(attempts) == 2:
                    both_attempted.set()
            try:
                outcomes.append(service.execute(initial.workflow_id).status)
            except WorkflowExecutionError:
                outcomes.append("rejected")
                second_rejected.set()

        threads = [threading.Thread(target=execute, args=(service,)) for service in services]
        for thread in threads:
            thread.start()
        self.assertTrue(executor_entered.wait(timeout=2))
        self.assertTrue(both_attempted.wait(timeout=2))
        self.assertTrue(second_rejected.wait(timeout=2))
        self.assertEqual(len(calls), 1)
        release_executor.set()
        for thread in threads:
            thread.join(timeout=3)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(calls, ["source-0"])
        self.assertIn(WorkflowStatus.COMPLETED, outcomes)
        self.assertEqual(sum(value == "rejected" for value in outcomes), 1)
        final = store.get(initial.workflow_id)
        self.assertEqual(final.status, WorkflowStatus.COMPLETED)
        self.assertEqual(final.steps[0].status, WorkflowStepStatus.COMPLETED)

    def test_cancellation_after_claim_is_ordered_after_workflow_started(self):
        claimed = threading.Event()
        allow_claim_return = threading.Event()
        sink = InMemoryEventSink()
        observability = ObservabilityService(sink)

        class PauseClaimReturnStore(InMemoryWorkflowStore):
            def claim_pending(self, workflow_id):
                workflow = super().claim_pending(workflow_id)
                claimed.set()
                if not allow_claim_return.wait(timeout=3):
                    raise TimeoutError("claim/start ordering test gate timed out")
                return workflow

        class CountingExecutor(RecordingExecutor):
            def execute(self, step, context):
                self.calls.append(step.source_step_id)
                return make_success(output={"stale": "must not be stored"})

        store = PauseClaimReturnStore()
        executor = CountingExecutor()
        executing = WorkflowService(store, executor, observability=observability)
        cancelling = WorkflowService(store, RecordingExecutor(), observability=observability)
        workflow = executing.create(make_plan(2))
        results = []
        execution_calls = []

        def execute_once():
            execution_calls.append(workflow.workflow_id)
            results.append(executing.execute(workflow.workflow_id))

        thread = threading.Thread(
            target=execute_once
        )
        thread.start()
        self.assertTrue(claimed.wait(timeout=2))

        deferred = cancelling.cancel(workflow.workflow_id)
        self.assertEqual(deferred.status, WorkflowStatus.CANCELLING)
        self.assertEqual(sink.events, [])
        allow_claim_return.set()
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())

        final = store.get(workflow.workflow_id)
        self.assertEqual(final.status, WorkflowStatus.CANCELLED)
        self.assertEqual(
            [step.status for step in final.steps],
            [WorkflowStepStatus.CANCELLED, WorkflowStepStatus.CANCELLED],
        )
        self.assertTrue(all(step.result is None for step in final.steps))
        self.assertEqual(dict(final.context.outputs), {})
        self.assertEqual(results[0].status, WorkflowStatus.CANCELLED)
        self.assertEqual(execution_calls, [workflow.workflow_id])
        self.assertEqual(executor.calls, [])
        self.assertEqual(
            [event.event_type for event in sink.events],
            [
                EventType.WORKFLOW_STARTED,
                EventType.WORKFLOW_STEP_CANCELLED,
                EventType.WORKFLOW_STEP_CANCELLED,
                EventType.WORKFLOW_CANCELLED,
            ],
        )
        self.assertEqual(len({event.run_id for event in sink.events}), 1)
        self.assertEqual(observability.get_run(sink.events[0].run_id).status, RunStatus.COMPLETED)

    def test_plan_step_metadata_and_context_inputs_are_detached(self):
        source_metadata = {"nested": {"tags": ["plan"]}}
        plan = Plan(
            goal="Alias safety",
            steps=(PlanStep(
                step_id="source-only",
                position=0,
                description="Use metadata",
                action="inspect",
                metadata=source_metadata,
            ),),
        )
        inputs = {"nested": {"values": ["input"]}}
        variables = {"nested": {"values": ["variable"]}}
        context_metadata = {"nested": {"values": ["context"]}}
        workflow = WorkflowService(InMemoryWorkflowStore(), RecordingExecutor()).create(
            plan,
            inputs=inputs,
            variables=variables,
            context_metadata=context_metadata,
        )
        self.assertIsNot(plan.steps[0].metadata, workflow.steps[0].metadata)
        self.assertIsNot(workflow.context.inputs, inputs)
        self.assertIsNot(workflow.context.variables, variables)
        self.assertIsNot(workflow.context.metadata, context_metadata)
        source_metadata["nested"]["tags"].append("caller-change")
        inputs["nested"]["values"].append("caller-change")
        variables["nested"]["values"].append("caller-change")
        context_metadata["nested"]["values"].append("caller-change")
        self.assertEqual(workflow.steps[0].metadata["nested"]["tags"], ["plan"])
        self.assertEqual(workflow.context.inputs["nested"]["values"], ["input"])
        self.assertEqual(workflow.context.variables["nested"]["values"], ["variable"])
        self.assertEqual(workflow.context.metadata["nested"]["values"], ["context"])
        with self.assertRaises(TypeError):
            workflow.context.inputs["nested"]["values"].append("blocked")

    def test_cancellation_between_steps_preserves_completed_step(self):
        after_first_completion = threading.Event()
        release_read = threading.Event()

        class PauseBeforeNextStepStore(InMemoryWorkflowStore):
            def __init__(self):
                super().__init__()
                self.pause_once = True

            def get(self, workflow_id):
                value = super().get(workflow_id)
                if (
                    self.pause_once
                    and value.status == WorkflowStatus.RUNNING
                    and value.steps[0].status == WorkflowStepStatus.COMPLETED
                    and value.current_step_id is None
                ):
                    self.pause_once = False
                    after_first_completion.set()
                    if not release_read.wait(timeout=3):
                        raise TimeoutError("between-step test gate timed out")
                return value

        store = PauseBeforeNextStepStore()
        executor = RecordingExecutor()
        service = WorkflowService(store, executor)
        workflow = service.create(make_plan(3))
        outcomes = []
        thread = threading.Thread(target=lambda: outcomes.append(service.execute(workflow.workflow_id)))
        thread.start()
        self.assertTrue(after_first_completion.wait(timeout=2))
        cancelled = WorkflowService(store, RecordingExecutor()).cancel(workflow.workflow_id)
        self.assertEqual(cancelled.status, WorkflowStatus.CANCELLED)
        release_read.set()
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        final = store.get(workflow.workflow_id)
        self.assertEqual(executor.calls, ["source-0"])
        self.assertEqual(final.steps[0].status, WorkflowStepStatus.COMPLETED)
        self.assertEqual(
            [step.status for step in final.steps[1:]],
            [WorkflowStepStatus.CANCELLED, WorkflowStepStatus.CANCELLED],
        )
        self.assertEqual(outcomes[0].status, WorkflowStatus.CANCELLED)

    def test_cancellation_wins_when_result_is_returned_but_not_stored(self):
        executor_returned = threading.Event()
        allow_commit = threading.Event()
        sink = InMemoryEventSink()
        observability = ObservabilityService(sink)

        class PauseCompletedUpdateStore(InMemoryWorkflowStore):
            def update(self, workflow, *, expected_version):
                if (
                    workflow.steps[0].status == WorkflowStepStatus.COMPLETED
                    and not executor_returned.is_set()
                ):
                    executor_returned.set()
                    if not allow_commit.wait(timeout=3):
                        raise TimeoutError("result-commit test gate timed out")
                return super().update(workflow, expected_version=expected_version)

        class ReturningExecutor:
            def execute(self, step, context):
                return make_success(output={"must": "be discarded"})

        store = PauseCompletedUpdateStore()
        executing = WorkflowService(store, ReturningExecutor(), observability=observability)
        cancelling = WorkflowService(store, RecordingExecutor(), observability=observability)
        workflow = executing.create(make_plan(2))
        results = []
        thread = threading.Thread(target=lambda: results.append(executing.execute(workflow.workflow_id)))
        thread.start()
        self.assertTrue(executor_returned.wait(timeout=2))
        self.assertEqual(cancelling.cancel(workflow.workflow_id).status, WorkflowStatus.CANCELLING)
        allow_commit.set()
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        final = store.get(workflow.workflow_id)
        self.assertEqual(final.status, WorkflowStatus.CANCELLED)
        self.assertEqual(final.steps[0].status, WorkflowStepStatus.CANCELLED)
        self.assertIsNone(final.steps[0].result)
        self.assertEqual(final.steps[1].status, WorkflowStepStatus.CANCELLED)
        self.assertEqual(dict(final.context.outputs), {})
        self.assertEqual(results[0].status, WorkflowStatus.CANCELLED)
        self.assertEqual(
            [event.event_type for event in sink.events],
            [
                EventType.WORKFLOW_STARTED,
                EventType.WORKFLOW_STEP_STARTED,
                EventType.WORKFLOW_STEP_CANCELLED,
                EventType.WORKFLOW_STEP_CANCELLED,
                EventType.WORKFLOW_CANCELLED,
            ],
        )
        self.assertEqual(len({event.run_id for event in sink.events}), 1)

    def test_plan_creates_independent_workflow_and_steps_execute_sequentially(self):
        plan = make_plan()
        original = plan.model_dump(mode="json")
        executor = RecordingExecutor(
            {
                "source-0": make_success(output={"first": "value"}),
                "source-1": make_success(output="done"),
            }
        )
        service = WorkflowService(InMemoryWorkflowStore(), executor)
        workflow = service.create(plan, inputs={"private": "input"})
        self.assertIsNot(workflow.steps[0], plan.steps[0])
        completed = service.execute(workflow.workflow_id)
        self.assertEqual(executor.calls, ["source-0", "source-1"])
        self.assertEqual(completed.status, WorkflowStatus.COMPLETED)
        self.assertEqual(
            [step.status for step in completed.steps],
            [WorkflowStepStatus.COMPLETED, WorkflowStepStatus.COMPLETED],
        )
        self.assertEqual(executor.contexts[1].outputs["source-0"], {"first": "value"})
        self.assertEqual(completed.context.outputs["source-1"], "done")
        self.assertEqual(plan.model_dump(mode="json"), original)
        self.assertIsNotNone(completed.started_at)
        self.assertIsNotNone(completed.completed_at)
        with self.assertRaises(WorkflowExecutionError):
            service.execute(workflow.workflow_id)

    def test_failure_stops_later_steps_and_returns_normalized_state(self):
        executor = RecordingExecutor({"source-0": make_failure("expected_failure")})
        service = WorkflowService(InMemoryWorkflowStore(), executor)
        workflow = service.create(make_plan())
        failed = service.execute(workflow.workflow_id)
        self.assertEqual(executor.calls, ["source-0"])
        self.assertEqual(failed.status, WorkflowStatus.FAILED)
        self.assertEqual(failed.steps[0].status, WorkflowStepStatus.FAILED)
        self.assertEqual(failed.steps[0].result.error.code, "expected_failure")
        self.assertEqual(failed.steps[1].status, WorkflowStepStatus.PENDING)
        self.assertEqual(service.get(workflow.workflow_id), failed)

    def test_executor_exception_is_normalized_without_leaking_message(self):
        class RaisingExecutor:
            def execute(self, step, context):
                raise RuntimeError("secret argument data")

        service = WorkflowService(InMemoryWorkflowStore(), RaisingExecutor())
        workflow = service.create(make_plan(1))
        result = service.execute(workflow.workflow_id)
        step_result = result.steps[0].result
        self.assertFalse(step_result.success)
        self.assertEqual(step_result.error.message, "Step execution failed.")
        self.assertNotIn("secret argument data", repr(step_result))

    def test_pending_workflow_can_be_cancelled_without_starting_steps(self):
        executor = RecordingExecutor()
        service = WorkflowService(InMemoryWorkflowStore(), executor)
        workflow = service.create(make_plan())
        cancelled = service.cancel(workflow.workflow_id)
        self.assertEqual(cancelled.status, WorkflowStatus.CANCELLED)
        self.assertEqual(executor.calls, [])
        self.assertTrue(all(step.status == WorkflowStepStatus.CANCELLED for step in cancelled.steps))
        self.assertEqual(service.execute(workflow.workflow_id).status, WorkflowStatus.CANCELLED)

    def test_cancellation_during_step_prevents_any_later_step_from_starting(self):
        entered = threading.Event()
        release = threading.Event()
        sink = InMemoryEventSink()
        observability = ObservabilityService(sink)

        class BlockingExecutor(RecordingExecutor):
            def execute(self, step, context):
                self.calls.append(step.source_step_id)
                entered.set()
                if not release.wait(timeout=3):
                    raise TimeoutError("executor test gate timed out")
                return make_success()

        executor = BlockingExecutor()
        service = WorkflowService(
            InMemoryWorkflowStore(), executor, observability=observability
        )
        workflow = service.create(make_plan())
        results = []
        thread = threading.Thread(target=lambda: results.append(service.execute(workflow.workflow_id)))
        thread.start()
        self.assertTrue(entered.wait(timeout=2))
        with self.assertRaises(WorkflowExecutionError):
            service.delete(workflow.workflow_id)
        cancelling = service.cancel(workflow.workflow_id)
        self.assertEqual(cancelling.status, WorkflowStatus.CANCELLING)
        release.set()
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        cancelled = results[0]
        self.assertEqual(cancelled.status, WorkflowStatus.CANCELLED)
        self.assertEqual(executor.calls, ["source-0"])
        self.assertEqual(cancelled.steps[0].status, WorkflowStepStatus.CANCELLED)
        self.assertEqual(cancelled.steps[1].status, WorkflowStepStatus.CANCELLED)
        self.assertEqual(
            [event.event_type for event in sink.events],
            [
                EventType.WORKFLOW_STARTED,
                EventType.WORKFLOW_STEP_STARTED,
                EventType.WORKFLOW_STEP_CANCELLED,
                EventType.WORKFLOW_STEP_CANCELLED,
                EventType.WORKFLOW_CANCELLED,
            ],
        )
        self.assertEqual(len({event.run_id for event in sink.events}), 1)

    def test_observability_events_are_correlated_safe_and_lifecycle_ordered(self):
        sink = InMemoryEventSink()
        observability = ObservabilityService(sink)
        executor = RecordingExecutor(
            {"source-0": make_success(output={"secret": "private output"}), "source-1": make_success()}
        )
        service = WorkflowService(InMemoryWorkflowStore(), executor, observability=observability)
        workflow = service.create(
            make_plan(), inputs={"user_text": "private input"}, metadata={"secret": "private metadata"}
        )
        completed = service.execute(workflow.workflow_id)
        expected = [
            EventType.WORKFLOW_STARTED,
            EventType.WORKFLOW_STEP_STARTED,
            EventType.WORKFLOW_STEP_COMPLETED,
            EventType.WORKFLOW_STEP_STARTED,
            EventType.WORKFLOW_STEP_COMPLETED,
            EventType.WORKFLOW_COMPLETED,
        ]
        events = sink.events
        self.assertEqual([event.event_type for event in events], expected)
        self.assertEqual(len({event.run_id for event in events}), 1)
        run = observability.get_run(events[0].run_id)
        self.assertEqual(run.status, RunStatus.COMPLETED)
        serialized = repr([event.model_dump(mode="json") for event in events])
        for secret in ("private input", "private output", "private metadata", "Prepare a release", "action-0"):
            self.assertNotIn(secret, serialized)
        self.assertTrue(all(event.metadata["workflow_id"] == completed.workflow_id for event in events))

    def test_workflow_events_share_nested_run_and_do_not_finalize_parent(self):
        sink = InMemoryEventSink()
        observability = ObservabilityService(sink)
        parent = observability.start_run()
        service = WorkflowService(
            InMemoryWorkflowStore(), RecordingExecutor(), observability=observability
        )
        workflow = service.create(make_plan(1))
        with bind_run(parent):
            service.execute(workflow.workflow_id)
        self.assertTrue(sink.events)
        self.assertEqual({event.run_id for event in sink.events}, {parent.run_id})
        self.assertEqual(observability.get_run(parent.run_id).status, RunStatus.RUNNING)
        observability.complete_run(parent.run_id)

    def test_failure_and_cancellation_observability_events(self):
        sink = InMemoryEventSink()
        observability = ObservabilityService(sink)
        failing = WorkflowService(
            InMemoryWorkflowStore(),
            RecordingExecutor({"source-0": make_failure()}),
            observability=observability,
        )
        failed_workflow = failing.create(make_plan())
        failed = failing.execute(failed_workflow.workflow_id)
        self.assertEqual(failed.status, WorkflowStatus.FAILED)
        failure_events = [event for event in sink.events if event.event_type in {
            EventType.WORKFLOW_STEP_FAILED, EventType.WORKFLOW_FAILED
        }]
        self.assertEqual([event.event_type for event in failure_events], [
            EventType.WORKFLOW_STEP_FAILED, EventType.WORKFLOW_FAILED
        ])
        failed_run = observability.get_run(failure_events[0].run_id)
        self.assertEqual(failed_run.status, RunStatus.FAILED)

        cancellable = failing.create(make_plan())
        cancelled = failing.cancel(cancellable.workflow_id)
        self.assertEqual(cancelled.status, WorkflowStatus.CANCELLED)
        self.assertIn(EventType.WORKFLOW_CANCELLED, [event.event_type for event in sink.events])
        self.assertIn(EventType.WORKFLOW_STEP_CANCELLED, [event.event_type for event in sink.events])

    def test_telemetry_failure_is_fail_open(self):
        class BrokenSink:
            def write(self, event):
                raise OSError("telemetry offline")

        service = WorkflowService(
            InMemoryWorkflowStore(), RecordingExecutor(),
            observability=ObservabilityService(BrokenSink()),
        )
        workflow = service.create(make_plan(1))
        with self.assertLogs("app.observability.safe", level="ERROR"):
            completed = service.execute(workflow.workflow_id)
        self.assertEqual(completed.status, WorkflowStatus.COMPLETED)

    def test_workflow_components_do_not_depend_on_execution_subsystems(self):
        root = Path(__file__).parents[1] / "app" / "workflows"
        forbidden = {"agents", "llm", "tools", "rag", "memory", "mcp"}
        for path in root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported_roots = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    imported_roots.add(
                        node.module.split(".")[1]
                        if node.module.startswith("app.")
                        else ""
                    )
                elif isinstance(node, ast.Import):
                    imported_roots.update(
                        alias.name.split(".")[1]
                        for alias in node.names
                        if alias.name.startswith("app.")
                    )
            self.assertTrue(forbidden.isdisjoint(imported_roots), f"forbidden import in {path}")


if __name__ == "__main__":
    unittest.main()
