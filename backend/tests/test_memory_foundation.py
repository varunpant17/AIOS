import unittest
from datetime import UTC, datetime, timedelta, timezone

from pydantic import ValidationError

from app.memory import (
    DuplicateMemoryError,
    InMemoryMemoryStore,
    InvalidMemoryError,
    InvalidMemoryQueryError,
    Memory,
    MemoryNotFoundError,
    MemoryQuery,
    MemoryScope,
    MemoryService,
    MemoryStoreError,
    MemoryType,
)
from app.observability import EventType, InMemoryEventSink, ObservabilityService, RunStatus


def make_memory(
    memory_id="memory-1",
    *,
    content="User prefers concise reports",
    memory_type=MemoryType.SEMANTIC,
    scope=MemoryScope.USER,
    scope_id="user-1",
    source="conversation:turn-4",
    metadata=None,
    created_at=None,
):
    return Memory(
        memory_id=memory_id,
        content=content,
        memory_type=memory_type,
        scope=scope,
        scope_id=scope_id,
        source=source,
        metadata=metadata or {},
        created_at=created_at or datetime.now(UTC),
        updated_at=created_at or datetime.now(UTC),
    )


class MemoryFoundationTests(unittest.TestCase):
    def test_domain_types_scope_provenance_metadata_and_timestamps(self):
        memory = make_memory(metadata={"origin": "user request", "confirmed": True})
        self.assertEqual(
            {item.value for item in MemoryType}, {"working", "episodic", "semantic"}
        )
        self.assertEqual(
            {item.value for item in MemoryScope},
            {"global", "user", "agent", "session", "task"},
        )
        self.assertEqual(memory.source, "conversation:turn-4")
        self.assertEqual(memory.metadata["origin"], "user request")
        self.assertLessEqual(memory.created_at, memory.updated_at)
        self.assertIsNotNone(memory.memory_id)

        global_memory = make_memory(
            memory_id="global", scope=MemoryScope.GLOBAL, scope_id=None
        )
        self.assertIsNone(global_memory.scope_id)
        with self.assertRaises(ValidationError):
            make_memory(scope=MemoryScope.TASK, scope_id=None)
        with self.assertRaises(ValidationError):
            make_memory(scope=MemoryScope.GLOBAL, scope_id="user-1")
        with self.assertRaises(ValidationError):
            Memory(
                memory_id="bad",
                content=" ",
                memory_type="semantic",
                scope="global",
                source="source",
            )
        with self.assertRaises(ValidationError):
            make_memory(
                created_at=datetime.now(UTC),
                metadata={"invalid": object()},
            )

    def test_memory_rejects_updated_timestamp_before_created(self):
        now = datetime.now(UTC)
        with self.assertRaises(ValidationError):
            Memory(
                memory_id="time-order",
                content="fact",
                memory_type=MemoryType.SEMANTIC,
                scope=MemoryScope.GLOBAL,
                source="manual",
                created_at=now,
                updated_at=now - timedelta(seconds=1),
            )

    def test_memory_is_immutable_and_invalid_state_cannot_be_stored(self):
        memory = make_memory(metadata={"nested": {"items": []}})
        with self.assertRaises(ValidationError):
            memory.memory_id = " "
        with self.assertRaises(ValidationError):
            memory.scope = MemoryScope.GLOBAL
        with self.assertRaises(ValidationError):
            memory.scope_id = None
        with self.assertRaises(ValidationError):
            memory.content = " "
        with self.assertRaises(ValidationError):
            memory.updated_at = datetime.now(UTC) - timedelta(days=1)
        with self.assertRaises(TypeError):
            memory.metadata["unexpected"] = object()
        with self.assertRaises(TypeError):
            memory.metadata["nested"]["items"].append("invalid")

        store = InMemoryMemoryStore()
        self.assertEqual(store.create(memory), memory)
        self.assertEqual(store.get(memory.memory_id), memory)

        # Pydantic's model_copy(update=...) skips validation; the store boundary
        # must still reject such a forged object instead of persisting it.
        forged = memory.model_copy(update={"scope": MemoryScope.GLOBAL})
        with self.assertRaises(ValidationError):
            Memory.model_validate(forged)
        with self.assertRaises(InvalidMemoryError):
            store.create(forged)

    def test_memory_requires_aware_utc_timestamps(self):
        utc_time = datetime(2025, 1, 1, tzinfo=UTC)
        memory = make_memory(created_at=utc_time)
        self.assertEqual(memory.created_at.utcoffset(), timedelta(0))
        self.assertEqual(memory.updated_at.utcoffset(), timedelta(0))

        with self.assertRaises(ValidationError):
            make_memory(created_at=datetime(2025, 1, 1))
        with self.assertRaises(ValidationError):
            Memory(
                memory_id="offset-time",
                content="fact",
                memory_type=MemoryType.SEMANTIC,
                scope=MemoryScope.GLOBAL,
                source="manual",
                created_at=datetime(2025, 1, 1, tzinfo=timezone(timedelta(hours=2))),
                updated_at=datetime(2025, 1, 1, tzinfo=timezone(timedelta(hours=2))),
            )

        store = InMemoryMemoryStore()
        store.create(make_memory("valid-aware", created_at=utc_time))
        with self.assertRaises(ValidationError):
            make_memory("invalid-naive", created_at=datetime(2025, 1, 1))
        self.assertEqual(
            [item.memory_id for item in store.search(MemoryQuery())], ["valid-aware"]
        )

    def test_store_create_get_delete_and_missing_ids(self):
        store = InMemoryMemoryStore()
        memory = make_memory()
        stored = store.create(memory)
        self.assertEqual(stored, memory)
        self.assertEqual(store.get(memory.memory_id).source, memory.source)
        store.delete(memory.memory_id)
        with self.assertRaises(MemoryNotFoundError):
            store.get(memory.memory_id)
        with self.assertRaises(MemoryNotFoundError):
            store.delete(memory.memory_id)
        with self.assertRaises(InvalidMemoryError):
            store.get(" ")

    def test_store_rejects_duplicate_ids(self):
        store = InMemoryMemoryStore()
        memory = make_memory()
        store.create(memory)
        with self.assertRaises(DuplicateMemoryError):
            store.create(memory)

    def test_store_defensive_copies_on_input_output_and_search(self):
        store = InMemoryMemoryStore()
        source_metadata = {"nested": {"labels": ["saved"]}}
        original = make_memory(metadata=source_metadata)
        source_metadata["nested"]["labels"].append("mutated input")
        store.create(original)
        retrieved = store.get(original.memory_id)
        with self.assertRaises(TypeError):
            retrieved.metadata["nested"]["labels"].append("mutated output")
        search_result = store.search(MemoryQuery(text="concise"))[0]
        with self.assertRaises(TypeError):
            search_result.metadata["nested"]["labels"].append("mutated search")
        self.assertEqual(
            store.get(original.memory_id).metadata["nested"]["labels"], ["saved"]
        )

    def test_store_search_is_deterministic_and_filters_type_and_scope(self):
        store = InMemoryMemoryStore()
        created = datetime(2025, 1, 1, tzinfo=UTC)
        memories = [
            make_memory(
                "z-user", content="Blue project preference", created_at=created,
                memory_type=MemoryType.SEMANTIC,
            ),
            make_memory(
                "a-user", content="Blue project completed", created_at=created,
                memory_type=MemoryType.EPISODIC,
            ),
            make_memory(
                "global", content="Blue global policy", created_at=created,
                scope=MemoryScope.GLOBAL, scope_id=None,
            ),
            make_memory(
                "other-user", content="Blue preference", created_at=created,
                scope_id="user-2",
            ),
        ]
        for memory in memories:
            store.create(memory)

        query = MemoryQuery(text="BLUE", scope=MemoryScope.USER, scope_id="user-1")
        first = store.search(query)
        second = store.search(query)
        self.assertEqual([item.memory_id for item in first], ["a-user", "z-user"])
        self.assertEqual([item.memory_id for item in first], [item.memory_id for item in second])
        filtered = store.search(
            MemoryQuery(memory_type=MemoryType.EPISODIC, scope=MemoryScope.USER)
        )
        self.assertEqual([item.memory_id for item in filtered], ["a-user"])
        self.assertEqual(len(store.search(MemoryQuery(text="missing"))), 0)

    def test_query_validation_and_limit(self):
        with self.assertRaises(ValidationError):
            MemoryQuery(text=" ")
        with self.assertRaises(ValidationError):
            MemoryQuery(limit=0)
        with self.assertRaises(ValidationError):
            MemoryQuery(scope=MemoryScope.GLOBAL, scope_id="not-global")
        store = InMemoryMemoryStore()
        for number in range(3):
            store.create(make_memory(f"limit-{number}", content="needle"))
        self.assertEqual(len(store.search(MemoryQuery(text="needle", limit=2))), 2)

    def test_service_remember_get_search_recall_and_delete(self):
        service = MemoryService(InMemoryMemoryStore())
        memory = service.remember(make_memory())
        another = service.store(make_memory("memory-2"))
        self.assertEqual(another.memory_id, "memory-2")
        self.assertEqual(service.get(memory.memory_id), memory)
        result = service.search(MemoryQuery(text="concise"))
        self.assertEqual(result.result_count, 2)
        self.assertIn(memory.memory_id, {item.memory_id for item in result.memories})
        self.assertEqual(service.recall({"memory_type": "semantic"}).result_count, 2)
        service.delete(memory.memory_id)
        with self.assertRaises(MemoryNotFoundError):
            service.get(memory.memory_id)

    def test_service_validation_and_store_errors_are_normalized(self):
        service = MemoryService(InMemoryMemoryStore())
        with self.assertRaises(InvalidMemoryError):
            service.remember({"content": "invalid"})
        with self.assertRaises(InvalidMemoryQueryError):
            service.search({"text": " "})
        memory = make_memory()
        service.remember(memory)
        with self.assertRaises(DuplicateMemoryError):
            service.remember(memory)

        class BrokenStore:
            def create(self, memory):
                raise RuntimeError("backend detail")

            def get(self, memory_id):
                raise RuntimeError("backend detail")

            def delete(self, memory_id):
                raise RuntimeError("backend detail")

            def search(self, query):
                raise RuntimeError("backend detail")

        with self.assertRaisesRegex(MemoryStoreError, "Memory could not be stored") as caught:
            MemoryService(BrokenStore()).remember(make_memory())
        self.assertNotIn("backend detail", str(caught.exception))

    def test_observability_events_correlation_and_content_privacy(self):
        sink = InMemoryEventSink()
        observability = ObservabilityService(sink)
        service = MemoryService(InMemoryMemoryStore(), observability=observability)
        secret = "private preference phrase"
        memory = service.remember(make_memory(content=secret))
        service.search(MemoryQuery(text=secret))
        service.delete(memory.memory_id)
        events = sink.events
        self.assertEqual(
            [event.event_type for event in events],
            [
                EventType.MEMORY_STORE_STARTED,
                EventType.MEMORY_STORE_COMPLETED,
                EventType.MEMORY_SEARCH_STARTED,
                EventType.MEMORY_SEARCH_COMPLETED,
                EventType.MEMORY_DELETE_STARTED,
                EventType.MEMORY_DELETE_COMPLETED,
            ],
        )
        serialized = repr([event.model_dump(mode="json") for event in events])
        self.assertNotIn(secret, serialized)
        self.assertEqual(len({event.run_id for event in events}), 3)
        self.assertTrue(
            all(observability.get_run(event.run_id).status == RunStatus.COMPLETED for event in events)
        )

    def test_failed_operations_emit_failure_events_and_fail_standalone_run(self):
        sink = InMemoryEventSink()
        observability = ObservabilityService(sink)
        service = MemoryService(InMemoryMemoryStore(), observability=observability)
        with self.assertRaises(MemoryNotFoundError):
            service.delete("missing")
        self.assertEqual(
            [event.event_type for event in sink.events],
            [EventType.MEMORY_DELETE_STARTED, EventType.MEMORY_DELETE_FAILED],
        )
        run = observability.get_run(sink.events[0].run_id)
        self.assertEqual(run.status, RunStatus.FAILED)

    def test_observability_sink_failure_does_not_break_memory_operation(self):
        class BrokenSink:
            def write(self, event):
                raise OSError("telemetry unavailable")

        service = MemoryService(
            InMemoryMemoryStore(), observability=ObservabilityService(BrokenSink())
        )
        with self.assertLogs("app.observability.safe", level="ERROR"):
            memory = service.remember(make_memory())
        self.assertEqual(service.get(memory.memory_id), memory)


if __name__ == "__main__":
    unittest.main()
