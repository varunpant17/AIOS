import ast
import unittest
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from pydantic import ValidationError

from app.core.immutable import freeze_json
from app.observability import (
    EventType,
    InMemoryEventSink,
    ObservabilityService,
    RunStatus,
    bind_run,
)
from app.planning import (
    InvalidPlanError,
    InvalidPlanStepError,
    Plan,
    PlanStatus,
    PlanStep,
    PlanStepSpec,
    PlanStepStatus,
    PlannerError,
    SimplePlanner,
)
from app.reflection import (
    InvalidReflectionError,
    ReflectionOutcome,
    ReflectionResult,
    SimpleReflector,
)


class PlanningReflectionFoundationTests(unittest.TestCase):
    def test_frozen_json_containers_block_all_public_mutators(self):
        frozen_dict = freeze_json({"key": "value", "other": 1})
        dict_mutations = (
            lambda: frozen_dict.__setitem__("key", "changed"),
            lambda: frozen_dict.__delitem__("key"),
            frozen_dict.clear,
            lambda: frozen_dict.pop("key"),
            frozen_dict.popitem,
            lambda: frozen_dict.setdefault("new", 2),
            lambda: frozen_dict.update({"new": 2}),
            lambda: frozen_dict.__ior__({"new": 2}),
            lambda: frozen_dict.__init__({"new": 2}),
        )
        for mutate in dict_mutations:
            with self.subTest(mutation=mutate):
                with self.assertRaises(TypeError):
                    mutate()

        frozen_list = freeze_json(["one", "two"])
        list_mutations = (
            lambda: frozen_list.__setitem__(0, "changed"),
            lambda: frozen_list.__delitem__(0),
            lambda: frozen_list.append("three"),
            lambda: frozen_list.extend(["three"]),
            lambda: frozen_list.insert(0, "zero"),
            frozen_list.pop,
            lambda: frozen_list.remove("one"),
            frozen_list.clear,
            frozen_list.reverse,
            frozen_list.sort,
            lambda: frozen_list.__iadd__(["three"]),
            lambda: frozen_list.__imul__(2),
            lambda: frozen_list.__init__(["replacement"]),
        )
        for mutate in list_mutations:
            with self.subTest(mutation=mutate):
                with self.assertRaises(TypeError):
                    mutate()

    def test_frozen_json_recurses_detaches_aliases_and_preserves_json_shape(self):
        original = {"nested": {"items": [1, {"enabled": True}]}, "tuple_like": ["a"]}
        frozen = freeze_json(original)
        original["nested"]["items"][1]["enabled"] = False
        original["nested"]["items"].append(2)
        self.assertEqual(frozen, {"nested": {"items": [1, {"enabled": True}]}, "tuple_like": ["a"]})
        with self.assertRaises(TypeError):
            frozen["nested"].__init__({"replaced": True})
        with self.assertRaises(TypeError):
            frozen["nested"]["items"].__init__(["replaced"])
        with self.assertRaises(TypeError):
            frozen["nested"]["items"][1].update({"enabled": False})
        with self.assertRaises(TypeError):
            frozen["nested"]["items"].append(3)
        with self.assertRaises(TypeError):
            freeze_json((1, 2))

    def test_plan_and_reflection_model_copy_revalidates_updates(self):
        plan = Plan(
            goal="Keep invariants",
            steps=(PlanStep(position=0, description="Inspect", action="inspect"),),
        )
        with self.assertRaises(ValidationError):
            plan.model_copy(update={"goal": " "})
        with self.assertRaises(ValidationError):
            plan.model_copy(
                update={"steps": (plan.steps[0].model_copy(update={"position": 2}),)}
            )
        updated_plan = plan.model_copy(update={"status": PlanStatus.ACCEPTED})
        self.assertEqual(updated_plan.status, PlanStatus.ACCEPTED)
        self.assertEqual(plan.status, PlanStatus.DRAFT)

        reflection = ReflectionResult(
            assessment="Valid assessment", outcome=ReflectionOutcome.SUCCEEDED
        )
        with self.assertRaises(ValidationError):
            reflection.model_copy(update={"assessment": " "})
        with self.assertRaises(ValidationError):
            reflection.model_copy(update={"timestamp": datetime(2025, 1, 1)})
        updated_reflection = reflection.model_copy(
            update={"outcome": ReflectionOutcome.PARTIAL}
        )
        self.assertEqual(updated_reflection.outcome, ReflectionOutcome.PARTIAL)
        self.assertEqual(reflection.outcome, ReflectionOutcome.SUCCEEDED)

    def test_plan_and_step_validation_order_and_status_contracts(self):
        steps = (
            PlanStep(step_id="step-a", position=0, description="First", action="inspect"),
            PlanStep(step_id="step-b", position=1, description="Second", action="summarize"),
        )
        plan = Plan(plan_id="plan-1", goal="Prepare report", steps=steps)
        self.assertEqual([step.position for step in plan.steps], [0, 1])
        self.assertEqual(plan.status, PlanStatus.DRAFT)
        self.assertEqual(plan.steps[0].status, PlanStepStatus.PLANNED)
        with self.assertRaises(ValidationError):
            Plan(goal=" ", steps=steps)
        with self.assertRaises(ValidationError):
            Plan(goal="Empty plan", steps=())
        with self.assertRaises(ValidationError):
            Plan(
                goal="Out of order",
                steps=(steps[1], steps[0]),
            )
        with self.assertRaises(ValidationError):
            Plan(
                goal="Duplicate IDs",
                steps=(steps[0], steps[0].model_copy(update={"position": 1})),
            )
        with self.assertRaises(ValidationError):
            PlanStep(position=-1, description="Bad", action="inspect")
        with self.assertRaises(ValidationError):
            PlanStep(position=0, description=" ", action="inspect")

    def test_plan_domain_is_immutable_including_nested_metadata(self):
        plan = Plan(
            goal="Retain policy",
            steps=(PlanStep(position=0, description="Read", action="review"),),
            metadata={"nested": {"labels": ["safe"]}},
        )
        with self.assertRaises(ValidationError):
            plan.goal = "Changed"
        with self.assertRaises(TypeError):
            plan.metadata["nested"]["labels"].append("changed")
        with self.assertRaises(ValidationError):
            plan.steps[0].action = "execute"
        self.assertEqual(plan.metadata["nested"]["labels"], ["safe"])
        self.assertEqual(plan.model_dump(mode="json")["goal"], "Retain policy")

    def test_plan_timestamps_require_utc_and_order(self):
        created = datetime(2025, 1, 1, tzinfo=UTC)
        step = (PlanStep(position=0, description="Do work", action="act"),)
        valid = Plan(goal="UTC plan", steps=step, created_at=created, updated_at=created)
        self.assertEqual(valid.created_at.utcoffset(), timedelta(0))
        with self.assertRaises(ValidationError):
            Plan(
                goal="Naive plan",
                steps=step,
                created_at=datetime(2025, 1, 1),
                updated_at=datetime(2025, 1, 1),
            )
        with self.assertRaises(ValidationError):
            Plan(
                goal="Offset plan",
                steps=step,
                created_at=datetime(2025, 1, 1, tzinfo=timezone(timedelta(hours=3))),
                updated_at=datetime(2025, 1, 1, tzinfo=timezone(timedelta(hours=3))),
            )
        with self.assertRaises(ValidationError):
            Plan(
                goal="Invalid order",
                steps=step,
                created_at=created,
                updated_at=created - timedelta(seconds=1),
            )

    def test_simple_planner_preserves_explicit_step_order_and_context(self):
        planner = SimplePlanner()
        plan = planner.plan(
            "Review release readiness",
            [
                {"description": "Inspect tests", "action": "inspect_tests"},
                PlanStepSpec(description="Review risks", action="review_risks"),
            ],
            context={"release": "v1"},
            metadata={"request_kind": "release_review"},
        )
        self.assertEqual([step.position for step in plan.steps], [0, 1])
        self.assertEqual([step.action for step in plan.steps], ["inspect_tests", "review_risks"])
        self.assertEqual(plan.metadata["planning_context"]["release"], "v1")
        self.assertEqual(plan.metadata["request_kind"], "release_review")
        self.assertEqual(plan.status, PlanStatus.DRAFT)

    def test_planner_normalizes_invalid_goal_and_step_inputs(self):
        planner = SimplePlanner()
        with self.assertRaises(InvalidPlanError):
            planner.plan(" ", [{"description": "A", "action": "a"}])
        with self.assertRaises(InvalidPlanStepError):
            planner.plan("Goal", [{"description": " ", "action": "a"}])
        with self.assertRaises(InvalidPlanError):
            planner.plan("Goal", [])

    def test_reflection_result_validates_and_preserves_structured_assessment(self):
        result = SimpleReflector().reflect(
            "The task completed with one omitted check.",
            ReflectionOutcome.PARTIAL,
            observations=("Two checks passed",),
            recommendations=("Run the omitted check",),
            context={"task_id": "task-7"},
            metadata={"review_kind": "quality"},
        )
        self.assertEqual(result.outcome, ReflectionOutcome.PARTIAL)
        self.assertEqual(result.observations, ("Two checks passed",))
        self.assertEqual(result.recommendations, ("Run the omitted check",))
        self.assertEqual(result.metadata["review_kind"], "quality")
        self.assertEqual(result.metadata["reflection_context"]["task_id"], "task-7")
        with self.assertRaises(ValidationError):
            ReflectionResult(assessment=" ", outcome=ReflectionOutcome.SUCCEEDED)
        with self.assertRaises(ValidationError):
            ReflectionResult(
                assessment="Assessment",
                outcome="not-an-outcome",
            )
        with self.assertRaises(ValidationError):
            ReflectionResult(
                assessment="Assessment",
                outcome=ReflectionOutcome.FAILED,
                observations=("",),
            )

    def test_reflection_is_immutable_and_timestamp_is_utc(self):
        timestamp = datetime(2025, 1, 1, tzinfo=UTC)
        result = ReflectionResult(
            assessment="Reviewed",
            outcome=ReflectionOutcome.SUCCEEDED,
            metadata={"nested": {"items": ["one"]}},
            timestamp=timestamp,
        )
        self.assertEqual(result.timestamp.utcoffset(), timedelta(0))
        with self.assertRaises(ValidationError):
            result.assessment = "changed"
        with self.assertRaises(TypeError):
            result.metadata["nested"]["items"].append("two")
        with self.assertRaises(ValidationError):
            ReflectionResult(
                assessment="Naive timestamp",
                outcome=ReflectionOutcome.UNKNOWN,
                timestamp=datetime(2025, 1, 1),
            )

    def test_simple_reflector_requires_explicit_assessment_and_outcome(self):
        reflector = SimpleReflector()
        with self.assertRaises(InvalidReflectionError):
            reflector.reflect(" ", ReflectionOutcome.UNKNOWN)
        with self.assertRaises(InvalidReflectionError):
            reflector.reflect("Observed", "invalid-outcome")
        with self.assertRaises(InvalidReflectionError):
            reflector.reflect("Observed", ReflectionOutcome.FAILED, observations="not a sequence")

    def test_implementations_have_no_llm_tool_rag_memory_or_mcp_imports(self):
        root = Path(__file__).parents[1] / "app"
        modules = (root / "planning" / "simple.py", root / "reflection" / "simple.py")
        forbidden = {"agents", "llm", "tools", "rag", "memory", "mcp", "workflows"}
        for path in modules:
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

    def test_observability_lifecycle_privacy_and_standalone_runs(self):
        sink = InMemoryEventSink()
        observability = ObservabilityService(sink)
        planner = SimplePlanner(observability=observability)
        reflector = SimpleReflector(observability=observability)
        goal = "sensitive user goal"
        assessment = "private execution assessment"
        planner.plan(goal, [{"description": "private plan step", "action": "review"}])
        reflector.reflect(
            assessment,
            ReflectionOutcome.SUCCEEDED,
            observations=("private observation",),
            recommendations=("private recommendation",),
        )
        self.assertEqual(
            [event.event_type for event in sink.events],
            [
                EventType.PLANNING_STARTED,
                EventType.PLANNING_COMPLETED,
                EventType.REFLECTION_STARTED,
                EventType.REFLECTION_COMPLETED,
            ],
        )
        serialized = repr([event.model_dump(mode="json") for event in sink.events])
        sensitive_values = (
            goal,
            assessment,
            "private plan step",
            "private observation",
            "private recommendation",
        )
        for sensitive in sensitive_values:
            self.assertNotIn(sensitive, serialized)
        self.assertEqual(len({event.run_id for event in sink.events[:2]}), 1)
        self.assertEqual(len({event.run_id for event in sink.events[2:]}), 1)
        self.assertEqual(
            [
                observability.get_run(run_id).status
                for run_id in {event.run_id for event in sink.events}
            ],
            [RunStatus.COMPLETED, RunStatus.COMPLETED],
        )

    def test_nested_runs_share_parent_and_failures_emit_events(self):
        sink = InMemoryEventSink()
        observability = ObservabilityService(sink)
        parent = observability.start_run()
        planner = SimplePlanner(observability=observability)
        reflector = SimpleReflector(observability=observability)
        with bind_run(parent):
            planner.plan("Goal", [{"description": "Step", "action": "act"}])
            reflector.reflect("Assessment", ReflectionOutcome.UNKNOWN)
            with self.assertRaises(InvalidPlanStepError):
                planner.plan("Goal", [{"description": " ", "action": "bad"}])
            with self.assertRaises(InvalidReflectionError):
                reflector.reflect(" ", ReflectionOutcome.UNKNOWN)
        self.assertEqual({event.run_id for event in sink.events}, {parent.run_id})
        self.assertEqual(
            [event.event_type for event in sink.events],
            [
                EventType.PLANNING_STARTED,
                EventType.PLANNING_COMPLETED,
                EventType.REFLECTION_STARTED,
                EventType.REFLECTION_COMPLETED,
                EventType.PLANNING_STARTED,
                EventType.PLANNING_FAILED,
                EventType.REFLECTION_STARTED,
                EventType.REFLECTION_FAILED,
            ],
        )
        self.assertEqual(observability.get_run(parent.run_id).status, RunStatus.RUNNING)
        observability.complete_run(parent.run_id)

    def test_standalone_planning_and_reflection_failures_finalize_owned_runs(self):
        sink = InMemoryEventSink()
        observability = ObservabilityService(sink)
        with self.assertRaises(InvalidPlanError):
            SimplePlanner(observability=observability).plan(" ", [])
        with self.assertRaises(InvalidReflectionError):
            SimpleReflector(observability=observability).reflect(
                " ", ReflectionOutcome.UNKNOWN
            )
        self.assertEqual(
            [event.event_type for event in sink.events],
            [
                EventType.PLANNING_STARTED,
                EventType.PLANNING_FAILED,
                EventType.REFLECTION_STARTED,
                EventType.REFLECTION_FAILED,
            ],
        )
        run_ids = {event.run_id for event in sink.events}
        self.assertEqual(len(run_ids), 2)
        self.assertTrue(
            all(observability.get_run(run_id).status == RunStatus.FAILED for run_id in run_ids)
        )

    def test_fail_open_observability_does_not_break_planning_or_reflection(self):
        class BrokenSink:
            def write(self, event):
                raise OSError("telemetry unavailable")

        observability = ObservabilityService(BrokenSink())
        planner = SimplePlanner(observability=observability)
        reflector = SimpleReflector(observability=observability)
        with self.assertLogs("app.observability.safe", level="ERROR"):
            plan = planner.plan("Goal", [{"description": "Step", "action": "act"}])
            reflected = reflector.reflect("Assessment", ReflectionOutcome.SUCCEEDED)
        self.assertEqual(plan.goal, "Goal")
        self.assertEqual(reflected.outcome, ReflectionOutcome.SUCCEEDED)


if __name__ == "__main__":
    unittest.main()
