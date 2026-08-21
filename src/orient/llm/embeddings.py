"""Embeddings through the proxy rather than a provider SDK.

Going through the proxy is what puts their cost and latency in the same traces and spend
records as every other model call, which is the whole reason the proxy is in the path.
"""

from collections.abc import Sequence
from typing import Final

import httpx
from pydantic import BaseModel, ConfigDict

from orient import correlation

Vectors = tuple[tuple[float, ...], ...]

# An embeddings row reports its tokens but not what asked for them. The tag is what
# separates their spend from the completions beside it in the same run.
TAGS: Final = ("phase:embed",)


class _Entry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    embedding: list[float]
    index: int = 0


class _Payload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data: list[_Entry] = []


class EmbeddingError(RuntimeError):
    """Raised at the boundary so the orchestrator converts it into a typed outcome once."""


class EmbeddingClient:
    def __init__(self, client: httpx.AsyncClient, model: str, dimensions: int) -> None:
        self._client: Final = client
        self._model: Final = model
        self._dimensions: Final = dimensions

    async def embed(self, texts: Sequence[str], session: str | None = None) -> Vectors:
        if not texts:
            return ()

        request: Final = {"model": self._model, "input": list(texts), "dimensions": self._dimensions}
        response: Final = await self._client.post("/v1/embeddings", json=request, headers=correlation.headers(session))
        if not response.is_success:
            message = f"embeddings returned HTTP {response.status_code}: {response.text[:200]}"
            raise EmbeddingError(message)

        payload: Final = _Payload.model_validate_json(response.content)
        # Ordered by the provider's own index rather than arrival: a reordered response would
        # otherwise attach each vector to the wrong claim, and nothing downstream could detect it.
        ordered: Final = sorted(payload.data, key=lambda entry: entry.index)
        vectors: Final = tuple(tuple(entry.embedding) for entry in ordered)

        if len(vectors) != len(texts):
            message = f"asked for {len(texts)} embeddings and got {len(vectors)}"
            raise EmbeddingError(message)

        wrong: Final = tuple(len(vector) for vector in vectors if len(vector) != self._dimensions)
        if wrong:
            message = f"expected {self._dimensions} dimensions, got {wrong[0]}; the pgvector column would reject it"
            raise EmbeddingError(message)

        return vectors
