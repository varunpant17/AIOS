# RAG Foundation

RAG (retrieval-augmented generation) in AIOS is a retrieval subsystem, not an agent or tool. This phase ends at `RAGContext`: it finds relevant knowledge for a later caller but does not build prompts or generate an answer.

## Data Flows

```text
Ingestion: Document → Chunker → EmbeddingProvider.embed_many → VectorStore.index
Query:     text → EmbeddingProvider.embed → VectorStore.search → RetrievedChunk → RAGContext
```

`Document` holds source content, source identity, and metadata. `Chunk` carries a stable chunk ID, document ID, source, position, text, and copied document metadata. `RetrievedChunk` retains the complete chunk and repeats its document ID/source alongside a relevance score. `RAGContext` preserves the original query and ordered retrieval results for a future generation layer.

## Replaceable Boundaries

`EmbeddingProvider` is separate from `LLMManager`: vectorization is an embedding operation with single-text and batch contracts, not text generation. `VectorStore` abstracts indexing and similarity search without exposing database-specific concepts. `Chunker`, `EmbeddingProvider`, and `VectorStore` are injected into `IngestionService`; `Retriever` receives the embedding and store ports. No hidden global providers or stores are created.

The included `DeterministicHashEmbeddingProvider` hashes lexical tokens into normalized vectors. It provides repeatable tests, not semantic or production-quality embeddings. `InMemoryVectorStore` uses cosine similarity and deterministic tie-breaking; both included implementations are process-local. `FixedSizeChunker` uses character windows and preserves provenance and offsets; it is intentionally not token-aware.

Ingestion and retrieval emit `rag.ingestion.*` and `rag.retrieval.*` events through the existing Phase 5 `Observability` interface when injected. Inject the same `ObservabilityService` instance used by `AgentRuntime` when RAG events should correlate with an agent run; otherwise standalone ingestion/retrieval calls create their own runs. Events include IDs, counts, and top-k but omit document/query text. Telemetry remains fail-open.

## Errors and Scope

RAG boundaries raise normalized `RAGError` subclasses for invalid queries/top-k, chunking, embedding, vector-store dimensions, and retrieval failures. A valid query against an empty store returns an empty `RAGContext`. Store search rejects nonpositive `top_k`, empty/non-finite vectors, and dimension mismatches; indexing validates a whole batch before changing the in-memory index.

This phase intentionally defers production vector databases, PDF/OCR and other document parsers, advanced chunking, reranking, hybrid search, query rewriting, RAG agents, answer generation, and citation generation. Future providers can implement the protocols without changing ingestion or retrieval orchestration.
