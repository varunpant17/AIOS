import threading
import unittest
import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from app.evaluation import (
    BasicMetric,
    ContainsEvaluator,
    DatasetValidationError,
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
    EvaluationRunError,
    EvaluationRunStatus,
    EvaluationService,
    EvaluationStoreError,
    ExactMatchEvaluator,
    InMemoryEvaluationStore,
    ThresholdEvaluator,
)
from app.evaluation.errors import EvaluatorError
from app.observability import EventType, InMemoryEventSink, ObservabilityService, bind_run


def make_case(case_id="case-1", expected="yes", **kwargs):
    return EvaluationCase(case_id=case_id, input={"prompt": "ignored"}, expected=expected, **kwargs)


def make_dataset(*cases):
    return EvaluationDataset(dataset_id="dataset-1", name="Dataset", cases=cases or (make_case(),))


class EvaluationFoundationTests(unittest.TestCase):
    def test_case_freezes_aliases_and_model_copy_revalidates(self):
        input_data = {"nested": [1]}
        expected = {"answer": ["ok"]}
        metadata = {"private": {"labels": ["x"]}}
        case = EvaluationCase(case_id="c1", input=input_data, expected=expected, metadata=metadata,
                              tags=(" z ", "a"))
        input_data["nested"].append(2)
        expected["answer"].append("changed")
        metadata["private"]["labels"].append("changed")
        self.assertEqual(case.input["nested"], [1])
        self.assertEqual(case.expected["answer"], ["ok"])
        self.assertEqual(case.metadata["private"]["labels"], ["x"])
        self.assertEqual(case.tags, ("a", "z"))
        with self.assertRaises(TypeError):
            case.input["nested"].append(3)
        with self.assertRaises(ValidationError):
            case.model_copy(update={"case_id": " "})
        self.assertEqual(case.model_copy(update={"case_id": "c2"}).case_id, "c2")

    def test_dataset_orders_cases_rejects_duplicates_and_empty(self):
        dataset = make_dataset(make_case("z"), make_case("a"))
        self.assertEqual([case.case_id for case in dataset.cases], ["a", "z"])
        with self.assertRaises(ValidationError):
            make_dataset(make_case("dup"), make_case("dup"))
        with self.assertRaises(ValidationError):
            EvaluationDataset(dataset_id="d", name="empty", cases=())
        original = [make_case("b"), make_case("a")]
        detached = EvaluationDataset(dataset_id="d", name="x", cases=original)
        original.clear()
        self.assertEqual([case.case_id for case in detached.cases], ["a", "b"])
        with self.assertRaises(TypeError):
            detached.cases[0] = make_case("bad")

    def test_result_validation_aliases_and_timestamps(self):
        metadata = {"labels": ["safe"]}
        result = EvaluationResult(case_id="c", evaluator_id="e", passed=True, score=1,
                                  metadata=metadata)
        metadata["labels"].append("mutated")
        self.assertEqual(result.metadata["labels"], ["safe"])
        with self.assertRaises(ValidationError):
            EvaluationResult(case_id="c", evaluator_id="e", passed=True, score=0.49)
        with self.assertRaises(ValidationError):
            EvaluationResult(case_id="c", evaluator_id="e", passed=True, score=True)
        with self.assertRaises(ValidationError):
            EvaluationResult(case_id="c", evaluator_id="e", passed=False, score=1)
        with self.assertRaises(ValidationError):
            EvaluationResult(case_id="c", evaluator_id="e", passed=True, score=1,
                             evaluated_at=datetime.now())
        with self.assertRaises(ValidationError):
            result.model_copy(update={"score": 3})

    def test_evaluators_exact_contains_threshold_and_invalid_values(self):
        exact = ExactMatchEvaluator()
        structured = EvaluationCase(case_id="struct", input=None,
                                    expected={"x": [1], "y": True})
        passed = exact.evaluate(structured, {"y": True, "x": [1]})
        self.assertTrue(passed.passed)
        self.assertFalse(exact.evaluate(make_case(expected=1), True).passed)
        contains = ContainsEvaluator()
        self.assertTrue(contains.evaluate(make_case(expected="ready"), "system ready now").passed)
        self.assertFalse(contains.evaluate(make_case(expected="ready"), "not yet").passed)
        self.assertTrue(contains.evaluate(make_case(expected={"a": [2]}), {"a": [1, 2], "b": 3}).passed)
        threshold = ThresholdEvaluator()
        self.assertTrue(threshold.evaluate(make_case(expected=0.7), 0.8).passed)
        self.assertFalse(threshold.evaluate(make_case(expected=0.7), 0.6).passed)
        with self.assertRaises(EvaluatorError):
            threshold.evaluate(make_case(expected="high"), 1)
        with self.assertRaises(EvaluatorError):
            threshold.evaluate(make_case(expected=0), "1")

    def test_metrics_aggregation_and_empty(self):
        metric = BasicMetric()
        empty = metric.aggregate(())
        self.assertEqual((empty.total_cases, empty.pass_rate, empty.average_score), (0, 0, 0))
        results = (
            EvaluationResult(case_id="a", evaluator_id="e", passed=True, score=1),
            EvaluationResult(case_id="b", evaluator_id="e", passed=False, score=0),
        )
        summary = metric.aggregate(results)
        self.assertEqual((summary.total_cases, summary.passed_cases, summary.failed_cases), (2, 1, 1))
        self.assertEqual((summary.pass_rate, summary.average_score), (0.5, 0.5))

    def test_run_lifecycle_utc_copy_and_store_versioning(self):
        store = InMemoryEvaluationStore()
        run = store.create_run(EvaluationRun(run_id="r1", dataset_id="d1"))
        started_at = datetime.now(UTC)
        started = run.model_copy(update={"status": EvaluationRunStatus.RUNNING,
                                         "started_at": started_at})
        started = store.update_run(started, expected_version=run.version)
        result = EvaluationResult(case_id="c", evaluator_id="e", passed=True, score=1)
        done = started.model_copy(update={
            "status": EvaluationRunStatus.COMPLETED,
            "completed_at": started_at + timedelta(seconds=1),
            "results": (result,), "summary": BasicMetric().aggregate((result,)),
        })
        saved = store.update_run(done, expected_version=started.version)
        self.assertEqual(saved.version, 2)
        with self.assertRaises(ValueError):
            saved.model_copy(update={"results": ()})
        with self.assertRaises(ValueError):
            run.model_copy(update={"status": EvaluationRunStatus.COMPLETED})
        with self.assertRaises(ValidationError):
            started.model_copy(update={"completed_at": started_at - timedelta(seconds=1)})
        with self.assertRaises(ValidationError):
            EvaluationRun(run_id="x", dataset_id="d", created_at=datetime.now(),
                          status=EvaluationRunStatus.CREATED)
        with self.assertRaises(EvaluationRunError):
            store.update_run(started, expected_version=started.version)
        changed_start = started.model_copy(update={"started_at": started_at + timedelta(seconds=1)})
        with self.assertRaises(EvaluationRunError):
            store.update_run(changed_start, expected_version=started.version)
        with self.assertRaises(EvaluationStoreError):
            store.get_run("missing")
        with self.assertRaises(EvaluationStoreError):
            store.create_run(EvaluationRun(run_id="r1", dataset_id="d1"))
        self.assertEqual(store.get_run("r1").results[0].case_id, "c")

    def test_store_thread_safety_rejects_duplicate_run_ids(self):
        store = InMemoryEvaluationStore()
        barrier = threading.Barrier(2)
        outcomes = []

        def create():
            barrier.wait()
            try:
                store.create_run(EvaluationRun(run_id="shared", dataset_id="d"))
                outcomes.append("created")
            except EvaluationStoreError:
                outcomes.append("duplicate")

        workers = [threading.Thread(target=create) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertCountEqual(outcomes, ["created", "duplicate"])

    def test_service_success_injection_sequential_metrics_and_telemetry_privacy(self):
        sink = InMemoryEventSink()
        observability = ObservabilityService(sink)
        seen = []

        class Recorder:
            evaluator_id = "recorder"

            def evaluate(self, case, actual):
                seen.append(case.case_id)
                return EvaluationResult(case_id=case.case_id, evaluator_id=self.evaluator_id,
                                        passed=actual == case.expected, score=1 if actual == case.expected else 0)

        dataset = EvaluationDataset(dataset_id="d", name="secret dataset",
                                    cases=(make_case("b", expected="hidden-b"),
                                           make_case("a", expected="hidden-a")))
        service = EvaluationService(InMemoryEvaluationStore(), Recorder(), observability=observability)
        with observability_run_context(observability):
            run = service.evaluate(dataset, {"a": "hidden-a", "b": "wrong"})
        self.assertEqual(seen, ["a", "b"])
        self.assertEqual(run.status, EvaluationRunStatus.COMPLETED)
        self.assertEqual((run.summary.total_cases, run.summary.passed_cases, run.summary.failed_cases), (2, 1, 1))
        self.assertEqual([event.event_type for event in sink.events], [
            EventType.EVALUATION_RUN_STARTED, EventType.EVALUATION_CASE_COMPLETED,
            EventType.EVALUATION_CASE_COMPLETED, EventType.EVALUATION_RUN_COMPLETED,
        ])
        serialized = repr([event.model_dump() for event in sink.events])
        for sensitive in ("hidden-a", "hidden-b", "wrong", "secret dataset"):
            self.assertNotIn(sensitive, serialized)
        self.assertEqual(len({event.run_id for event in sink.events}), 1)

    def test_service_fail_fast_records_case_and_finalizes_run(self):
        called = []

        class FailsSecond:
            evaluator_id = "test"

            def evaluate(self, case, actual):
                called.append(case.case_id)
                if case.case_id == "b":
                    raise RuntimeError("secret failure")
                return EvaluationResult(case_id=case.case_id, evaluator_id=self.evaluator_id,
                                        passed=True, score=1)

        sink = InMemoryEventSink()
        service = EvaluationService(InMemoryEvaluationStore(), FailsSecond(),
                                    observability=ObservabilityService(sink))
        run = service.evaluate(make_dataset(make_case("a"), make_case("b"), make_case("c")),
                               {"a": "yes", "b": "yes", "c": "yes"})
        self.assertEqual(called, ["a", "b"])
        self.assertEqual(run.status, EvaluationRunStatus.FAILED)
        self.assertEqual([result.case_id for result in run.results], ["a", "b"])
        self.assertEqual(run.results[-1].explanation, "Evaluator execution failed.")
        self.assertIsNotNone(run.error)
        self.assertEqual([event.event_type for event in sink.events], [
            EventType.EVALUATION_RUN_STARTED, EventType.EVALUATION_CASE_COMPLETED,
            EventType.EVALUATION_CASE_FAILED, EventType.EVALUATION_RUN_FAILED,
        ])
        self.assertNotIn("secret failure", repr([event.model_dump() for event in sink.events]))

    def test_invalid_actual_map_rejected_before_run(self):
        store = InMemoryEvaluationStore()
        service = EvaluationService(store, ExactMatchEvaluator())
        with self.assertRaises(DatasetValidationError):
            service.evaluate(make_dataset(), {})
        self.assertEqual(store.list_runs(), ())

    def test_evaluation_core_has_no_execution_subsystem_dependencies(self):
        package = Path(__file__).parents[1] / "app" / "evaluation"
        forbidden = {
            "app.agents", "app.llm", "app.workflows", "app.rag", "app.tools",
            "app.mcp", "app.multi_agent", "app.memory", "app.reflection",
            "app.planning",
        }
        for source in package.glob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            imports = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module)
                elif isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
            self.assertFalse(forbidden.intersection(imports), source.name)

    def test_observability_fail_open(self):
        class BrokenSink:
            def write(self, event):
                raise OSError("down")

        service = EvaluationService(InMemoryEvaluationStore(), ExactMatchEvaluator(),
                                    observability=ObservabilityService(BrokenSink()))
        run = service.evaluate(make_dataset(), {"case-1": "yes"})
        self.assertEqual(run.status, EvaluationRunStatus.COMPLETED)


class observability_run_context:
    """Bind an explicit shared run to prove event correlation without relying on standalone runs."""

    def __init__(self, observability):
        self.observability = observability

    def __enter__(self):
        self.run = self.observability.start_run({"owner": "test"})
        self.token = bind_run(self.run)
        self.token.__enter__()
        return self.run

    def __exit__(self, exc_type, exc, tb):
        self.token.__exit__(exc_type, exc, tb)
        self.observability.complete_run(self.run.run_id)
