import unittest

from pydantic import ValidationError

from app.observability import (
    EventType,
    InMemoryEventSink,
    ObservabilityService,
    RunStatus,
    bind_run,
)
from app.rag import (
    Chunk,
    DeterministicHashEmbeddingProvider,
    Document,
    EmbeddingError,
    FixedSizeChunker,
    InMemoryVectorStore,
    IngestionService,
    InvalidChunkError,
    InvalidQueryError,
    InvalidTopKError,
    RAGContext,
    RetrievedChunk,
    Retriever,
    VectorDimensionError,
    VectorStoreError,
)


def make_chunk(chunk_id, document_id="doc-1", text="text", position=0, source="kb://one", metadata=None):
    return Chunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        position=position,
        source=source,
        metadata=metadata or {},
    )


class RAGFoundationTests(unittest.TestCase):
    def test_document_chunk_retrieved_provenance_and_context_contracts(self):
        document = Document(
            document_id="doc-stable",
            content="knowledge",
            source="kb://guide",
            metadata={"tenant": "acme"},
        )
        chunk = make_chunk(
            "chunk-stable",
            document_id=document.document_id,
            text="knowledge",
            source=document.source,
            metadata=document.metadata,
        )
        retrieved = RetrievedChunk(
            chunk=chunk,
            document_id=document.document_id,
            source=document.source,
            score=0.91,
            metadata=document.metadata,
        )
        context = RAGContext(query="knowledge", retrieved_chunks=[retrieved])
        self.assertEqual(context.retrieved_chunks[0].chunk.chunk_id, "chunk-stable")
        self.assertEqual(context.retrieved_chunks[0].source, "kb://guide")
        self.assertEqual(context.retrieved_chunks[0].metadata["tenant"], "acme")
        with self.assertRaises(ValidationError):
            Document(content="  ", source="kb://empty")
        with self.assertRaises(ValidationError):
            RetrievedChunk(
                chunk=chunk,
                document_id="another-document",
                source=document.source,
                score=0.5,
            )
        with self.assertRaises(ValidationError):
            RAGContext(query=" ")

    def test_deterministic_embedding_supports_single_and_batch_and_rejects_empty(self):
        provider = DeterministicHashEmbeddingProvider(dimensions=64)
        single = provider.embed("same text")
        self.assertEqual(single, provider.embed("same text"))
        self.assertEqual(provider.embed_many(["same text", "other"]), [single, provider.embed("other")])
        self.assertEqual(len(single), 64)
        self.assertAlmostEqual(sum(value * value for value in single), 1.0)
        with self.assertRaises(EmbeddingError):
            provider.embed("  ")
        with self.assertRaises(EmbeddingError):
            provider.embed_many("not a text sequence")

    def test_fixed_chunker_is_deterministic_and_preserves_source_metadata(self):
        document = Document(
            document_id="doc-fixed",
            content="alpha beta gamma",
            source="s3://bucket/key",
            metadata={"tenant": "team-a"},
        )
        chunker = FixedSizeChunker(chunk_size=7, overlap=2)
        first = chunker.chunk(document)
        second = chunker.chunk(document)
        self.assertEqual([chunk.chunk_id for chunk in first], [chunk.chunk_id for chunk in second])
        self.assertEqual([chunk.position for chunk in first], list(range(len(first))))
        self.assertTrue(all(chunk.document_id == document.document_id for chunk in first))
        self.assertTrue(all(chunk.source == document.source for chunk in first))
        self.assertTrue(all(chunk.metadata["tenant"] == "team-a" for chunk in first))
        self.assertIn("start_char", first[0].metadata)
        with self.assertRaises(ValidationError):
            Document(content="", source="s3://bucket/empty")
        with self.assertRaises(ValueError):
            FixedSizeChunker(chunk_size=5, overlap=5)

        class WrongProvenanceChunker:
            def chunk(self, source_document):
                return [make_chunk("wrong", document_id="other-document")]

        with self.assertRaises(InvalidChunkError):
            IngestionService(
                WrongProvenanceChunker(),
                DeterministicHashEmbeddingProvider(),
                InMemoryVectorStore(),
            ).ingest(document)

    def test_fixed_chunker_preserves_window_offsets_and_overlap(self):
        document = Document(
            document_id="doc-windows",
            content="abcdefghij",
            source="kb://window-source",
            metadata={"tenant": "team-b", "category": "guide"},
        )
        chunker = FixedSizeChunker(chunk_size=4, overlap=2)

        chunks = chunker.chunk(document)
        repeated = chunker.chunk(document)

        expected = [
            ("abcd", 0, 4),
            ("cdef", 2, 6),
            ("efgh", 4, 8),
            ("ghij", 6, 10),
        ]
        actual = [
            (chunk.text, chunk.metadata["start_char"], chunk.metadata["end_char"])
            for chunk in chunks
        ]
        self.assertEqual(actual, expected)
        self.assertEqual(
            [chunk.chunk_id for chunk in chunks],
            [chunk.chunk_id for chunk in repeated],
        )
        self.assertEqual([chunk.position for chunk in chunks], [0, 1, 2, 3])
        for chunk in chunks:
            self.assertEqual(chunk.document_id, "doc-windows")
            self.assertEqual(chunk.source, "kb://window-source")
            self.assertEqual(chunk.metadata["tenant"], "team-b")
            self.assertEqual(chunk.metadata["category"], "guide")

    def test_fixed_chunker_offsets_refer_to_source_windows_before_trimming(self):
        document = Document(
            document_id="doc-trimmed-window",
            content=" ab  cd ",
            source="kb://trimmed-window",
        )
        chunks = FixedSizeChunker(chunk_size=4).chunk(document)

        self.assertEqual([chunk.text for chunk in chunks], ["ab", "cd"])
        self.assertEqual(
            [
                (chunk.metadata["start_char"], chunk.metadata["end_char"])
                for chunk in chunks
            ],
            [(0, 4), (4, 8)],
        )

    def test_vector_store_cosine_ordering_top_k_and_empty_store(self):
        store = InMemoryVectorStore()
        self.assertEqual(store.search([1.0, 0.0], top_k=2), [])
        left = make_chunk("left", text="left")
        diagonal = make_chunk("diagonal", text="diagonal", position=1)
        store.index([left, diagonal], [[1.0, 0.0], [0.7, 0.7]])
        results = store.search([1.0, 0.0], top_k=1)
        self.assertEqual([item.chunk.chunk_id for item in results], ["left"])
        self.assertAlmostEqual(results[0].score, 1.0)
        self.assertEqual(len(store.search([1.0, 0.0], top_k=9)), 2)
        with self.assertRaises(InvalidTopKError):
            store.search([1.0, 0.0], top_k=0)
        with self.assertRaises(VectorDimensionError):
            store.search([1.0, 0.0, 0.0], top_k=1)

    def test_vector_store_reports_cosine_scores_not_dot_products(self):
        store = InMemoryVectorStore()
        chunks = [
            make_chunk("identical"),
            make_chunk("diagonal", position=1),
            make_chunk("orthogonal", position=2),
            make_chunk("zero", position=3),
        ]
        store.index(
            chunks,
            [
                [1.0, 0.0],
                [1.0, 1.0],
                [0.0, 1.0],
                [0.0, 0.0],
            ],
        )

        results = store.search([1.0, 0.0], top_k=4)
        scores = {result.chunk.chunk_id: result.score for result in results}

        self.assertAlmostEqual(scores["identical"], 1.0)
        self.assertAlmostEqual(scores["diagonal"], 1.0 / (2.0**0.5))
        self.assertAlmostEqual(scores["orthogonal"], 0.0)
        # The in-memory store's zero-vector contract assigns a zero score.
        self.assertAlmostEqual(scores["zero"], 0.0)

    def test_vector_store_rejects_invalid_dimensions_without_partial_index(self):
        store = InMemoryVectorStore()
        with self.assertRaises(VectorDimensionError):
            store.index(
                [make_chunk("a"), make_chunk("b", position=1)],
                [[1.0, 0.0], [1.0]],
            )
        self.assertEqual(store.search([1.0], top_k=1), [])
        store.index([make_chunk("existing")], [[1.0, 0.0]])
        with self.assertRaises(VectorDimensionError):
            store.index([make_chunk("wrong-dim")], [[1.0, 0.0, 0.0]])
        with self.assertRaises(VectorStoreError):
            store.index([make_chunk("nan")], [[float("nan"), 0.0]])
        self.assertEqual(len(store.search([1.0, 0.0], top_k=10)), 1)

    def test_ingestion_and_retrieval_preserve_provenance_and_relevance(self):
        embedding = DeterministicHashEmbeddingProvider(dimensions=512)
        store = InMemoryVectorStore()
        ingestion = IngestionService(FixedSizeChunker(chunk_size=100), embedding, store)
        documents = [
            Document(
                document_id="quartz-doc",
                content="quartz token amber",
                source="kb://quartz",
                metadata={"tenant": "north"},
            ),
            Document(
                document_id="ocean-doc",
                content="oceanic phrase cobalt",
                source="kb://ocean",
                metadata={"tenant": "south"},
            ),
        ]
        for document in documents:
            ingestion.ingest(document)

        result = Retriever(embedding, store, top_k=2).retrieve("quartz amber")
        self.assertEqual(result.query, "quartz amber")
        self.assertEqual(result.retrieved_chunks[0].document_id, "quartz-doc")
        self.assertEqual(result.retrieved_chunks[0].source, "kb://quartz")
        self.assertEqual(result.retrieved_chunks[0].metadata["tenant"], "north")
        self.assertGreater(result.retrieved_chunks[0].score, result.retrieved_chunks[1].score)

        class ReversedStore:
            def search(self, query_vector, top_k):
                return list(reversed(store.search(query_vector, top_k)))

        reordered = Retriever(embedding, ReversedStore(), top_k=2).retrieve(
            "quartz amber"
        )
        self.assertEqual(reordered.retrieved_chunks[0].document_id, "quartz-doc")
        empty = Retriever(embedding, InMemoryVectorStore()).retrieve("no indexed data")
        self.assertEqual(empty.retrieved_chunks, [])

    def test_retriever_invalid_parameters_and_embedding_failure_are_normalized(self):
        embedding = DeterministicHashEmbeddingProvider()
        with self.assertRaises(InvalidTopKError):
            Retriever(embedding, InMemoryVectorStore(), top_k=0)
        retriever = Retriever(embedding, InMemoryVectorStore())
        with self.assertRaises(InvalidQueryError):
            retriever.retrieve("  ")
        with self.assertRaises(InvalidTopKError):
            retriever.retrieve("query", top_k=-1)

        class BrokenEmbedding:
            def embed(self, text):
                raise RuntimeError("provider internals")

            def embed_many(self, texts):
                raise RuntimeError("provider internals")

        with self.assertRaises(EmbeddingError) as caught:
            Retriever(BrokenEmbedding(), InMemoryVectorStore()).retrieve("query")
        self.assertNotIn("provider internals", str(caught.exception))

        sink = InMemoryEventSink()
        service = ObservabilityService(sink)
        with self.assertRaises(EmbeddingError):
            Retriever(
                BrokenEmbedding(), InMemoryVectorStore(), observability=service
            ).retrieve("private query")
        self.assertEqual(
            [event.event_type for event in sink.events],
            [EventType.RAG_RETRIEVAL_STARTED, EventType.RAG_RETRIEVAL_FAILED],
        )
        self.assertNotIn("private query", repr(sink.events))
        self.assertEqual(service.get_run(sink.events[0].run_id).status, RunStatus.FAILED)

    def test_vector_store_failure_is_normalized_and_rag_events_fail_open(self):
        class BrokenStore:
            def index(self, chunks, vectors):
                raise RuntimeError("database detail")

            def search(self, query_vector, top_k):
                raise RuntimeError("database detail")

        with self.assertRaises(VectorStoreError) as caught:
            IngestionService(
                FixedSizeChunker(),
                DeterministicHashEmbeddingProvider(),
                BrokenStore(),
            ).ingest(Document(content="content", source="private://source"))
        self.assertNotIn("database detail", str(caught.exception))

        class BrokenSink:
            def write(self, event):
                raise OSError("telemetry sink")

        service = ObservabilityService(BrokenSink())
        ingestion = IngestionService(
            FixedSizeChunker(),
            DeterministicHashEmbeddingProvider(),
            InMemoryVectorStore(),
            observability=service,
        )
        with self.assertLogs("app.observability.safe", level="ERROR"):
            chunks = ingestion.ingest(Document(content="private text", source="private://source"))
        self.assertTrue(chunks)

    def test_rag_observability_events_exclude_document_and_query_text(self):
        sink = InMemoryEventSink()
        service = ObservabilityService(sink)
        embedding = DeterministicHashEmbeddingProvider()
        store = InMemoryVectorStore()
        ingestion = IngestionService(
            FixedSizeChunker(), embedding, store, observability=service
        )
        retriever = Retriever(embedding, store, observability=service)
        parent_run = service.start_run({"entry_component": "agent"})
        with bind_run(parent_run):
            ingestion.ingest(
                Document(content="secret document body", source="private://records")
            )
            retriever.retrieve("secret search query")
        service.complete_run(parent_run.run_id)
        self.assertEqual(
            [event.event_type for event in sink.events],
            [
                EventType.RAG_INGESTION_STARTED,
                EventType.RAG_INGESTION_COMPLETED,
                EventType.RAG_RETRIEVAL_STARTED,
                EventType.RAG_RETRIEVAL_COMPLETED,
            ],
        )
        serialized = repr([event.model_dump(mode="json") for event in sink.events])
        self.assertNotIn("secret document body", serialized)
        self.assertNotIn("secret search query", serialized)
        self.assertNotIn("private://records", serialized)
        self.assertEqual({event.run_id for event in sink.events}, {parent_run.run_id})
        self.assertEqual(service.get_run(parent_run.run_id).status, RunStatus.COMPLETED)


if __name__ == "__main__":
    unittest.main()
