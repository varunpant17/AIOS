import hashlib
import math
import re
from collections.abc import Sequence

from app.rag.errors import EmbeddingError


class DeterministicHashEmbeddingProvider:
    """Small deterministic lexical embedding for tests and local examples only."""

    def __init__(self, dimensions: int = 128) -> None:
        if (
            not isinstance(dimensions, int)
            or isinstance(dimensions, bool)
            or dimensions < 1
        ):
            raise ValueError("dimensions must be positive")
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        if not isinstance(text, str) or not text.strip():
            raise EmbeddingError("Embedding input must contain non-whitespace text.")
        vector = [0.0] * self.dimensions
        tokens = re.findall(r"\w+", text.casefold(), flags=re.UNICODE)
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:8], "big") % self.dimensions
            sign = 1.0 if digest[8] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return vector

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        if isinstance(texts, (str, bytes)):
            raise EmbeddingError("Batch embedding requires a sequence of texts.")
        try:
            return [self.embed(text) for text in texts]
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError("Could not create embeddings for the batch.") from exc
