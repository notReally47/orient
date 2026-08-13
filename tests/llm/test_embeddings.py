"""Embedding client behaviour, driven through a MockTransport so the parsing path is real."""

import json
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Final

import httpx
import pytest
from pydantic import TypeAdapter

from orient.llm.embeddings import EmbeddingClient, EmbeddingError

Handler = Callable[[httpx.Request], httpx.Response]
DIMENSIONS: Final = 4

_REQUEST: Final = TypeAdapter(dict[str, object])


@asynccontextmanager
async def _client(handler: Handler, dimensions: int = DIMENSIONS) -> AsyncGenerator[EmbeddingClient, None]:
    transport: Final = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as http:
        yield EmbeddingClient(http, model="embedding-model", dimensions=dimensions)


def _responder(payload: object, status: int = 200) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(status, content=json.dumps(payload).encode())

    return handler


def _entry(index: int, fill: float, width: int = DIMENSIONS) -> dict[str, object]:
    return {"index": index, "embedding": [fill] * width}


async def test_vectors_come_back_in_the_order_the_inputs_went_in() -> None:
    """A response listing entries out of order would attach each vector to the wrong claim."""
    shuffled: Final = {"data": [_entry(2, 0.3), _entry(0, 0.1), _entry(1, 0.2)]}
    async with _client(_responder(shuffled)) as client:
        vectors = await client.embed(["a", "b", "c"])
    assert tuple(vector[0] for vector in vectors) == (0.1, 0.2, 0.3)


async def test_the_request_carries_the_model_and_the_configured_width() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(_REQUEST.validate_json(request.content))
        return httpx.Response(200, content=json.dumps({"data": [_entry(0, 0.1)]}).encode())

    async with _client(handler) as client:
        _ = await client.embed(["only"])
    assert seen == [{"model": "embedding-model", "input": ["only"], "dimensions": DIMENSIONS}]


async def test_no_input_makes_no_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        message = "the client should not have called out"
        raise AssertionError(message)

    async with _client(handler) as client:
        assert await client.embed([]) == ()


async def test_a_short_response_is_an_error_rather_than_a_silent_gap() -> None:
    payload: Final = {"data": [_entry(0, 0.1)]}
    async with _client(_responder(payload)) as client:
        with pytest.raises(EmbeddingError, match="asked for 2 embeddings and got 1"):
            _ = await client.embed(["a", "b"])


async def test_the_wrong_width_names_the_pgvector_column() -> None:
    payload: Final = {"data": [_entry(0, 0.1, width=768)]}
    async with _client(_responder(payload)) as client:
        with pytest.raises(EmbeddingError, match="expected 4 dimensions, got 768"):
            _ = await client.embed(["a"])


@pytest.mark.parametrize("status", [401, 429, 500])
async def test_an_http_failure_is_reported_with_its_status(status: int) -> None:
    async with _client(_responder({}, status=status)) as client:
        with pytest.raises(EmbeddingError, match=str(status)):
            _ = await client.embed(["a"])


async def test_every_returned_vector_keeps_its_full_width() -> None:
    payload: Final = {"data": [_entry(0, 0.1), _entry(1, 0.2)]}
    async with _client(_responder(payload)) as client:
        vectors = await client.embed(["a", "b"])
    assert [len(vector) for vector in vectors] == [DIMENSIONS, DIMENSIONS]


async def test_returned_vectors_cannot_be_edited_in_place() -> None:
    """Claims are persisted from these, and pydantic hands back a list unless we convert."""
    async with _client(_responder({"data": [_entry(0, 0.1)]})) as client:
        vectors = await client.embed(["a"])
    assert isinstance(vectors, tuple)
    assert isinstance(vectors[0], tuple)
