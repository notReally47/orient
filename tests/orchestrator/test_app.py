"""The HTTP surface, driven through the real routes over fakes.

The stream is the contract the GUI is built against, so what gets asserted is that a run's events
reach the wire in order, under their own event names, and that the whole thing ends.
"""

from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from typing import Final

import httpx
from pydantic import TypeAdapter

from orient.orchestrator.app import create_app
from orient.orchestrator.deps import RunDeps
from orient.orchestrator.events import Event
from tests.orchestrator.fakes import SESSION_DATE, Cache, ScriptedChat, answered, run_deps, saving

BODY: Final = {"symbol": "^GSPC", "session_date": SESSION_DATE.isoformat(), "level": "beginner"}
_EVENT: Final[TypeAdapter[Event]] = TypeAdapter(Event)


def _named(lines: Sequence[str]) -> tuple[str, ...]:
    """The event names off the wire, which is what a client subscribes to."""
    return tuple(line.removeprefix("event: ").strip() for line in lines if line.startswith("event: "))


@asynccontextmanager
async def _client(deps: RunDeps) -> AsyncGenerator[httpx.AsyncClient, None]:
    @asynccontextmanager
    async def build() -> AsyncGenerator[RunDeps, None]:
        yield deps

    application: Final = create_app(build)
    transport: Final = httpx.ASGITransport(app=application)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://orchestrator") as client,
        application.router.lifespan_context(application),
    ):
        yield client


async def test_health_reports_the_tools_it_can_see() -> None:
    """The probe reads this, so a service that booted without the tool server has to say so."""
    async with run_deps(ScriptedChat(), Cache()) as deps, _client(deps) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["tools"] > 0


async def test_health_says_it_is_starting_before_the_lifespan_has_run() -> None:
    async with run_deps(ScriptedChat(), Cache()) as deps:

        @asynccontextmanager
        async def build() -> AsyncGenerator[RunDeps, None]:
            yield deps

        application = create_app(build)
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://orchestrator") as client:
            response = await client.get("/health")

    assert response.json()["status"] == "starting"


async def test_a_run_streams_its_events_under_their_own_names() -> None:
    chat: Final = ScriptedChat(answered(calls=saving()))

    async with run_deps(chat, Cache()) as deps, _client(deps) as client:
        response = await client.post("/runs", json=BODY)
        lines = response.text.splitlines()

    names: Final = _named(lines)
    assert response.status_code == 200
    assert names[0] == "run_started"
    assert names[-1] == "run_finished"
    assert "section_ready" in names


async def test_a_failing_run_still_closes_the_stream() -> None:
    """A stream that never ends is a client that hangs, which is worse than a reported failure."""
    async with run_deps(ScriptedChat(), Cache()) as deps, _client(deps) as client:
        response = await client.post("/runs", json=BODY)

    assert _named(response.text.splitlines())[-1] == "run_failed"


async def test_a_malformed_request_is_rejected_before_a_run_starts() -> None:
    async with run_deps(ScriptedChat(), Cache()) as deps, _client(deps) as client:
        response = await client.post("/runs", json={**BODY, "level": "expert"})

    assert response.status_code == 422


async def test_every_streamed_payload_validates_back_into_the_event_union() -> None:
    """A client reads the stream through the same union, so a payload it cannot parse is a dead end."""
    chat: Final = ScriptedChat(answered(calls=saving()))

    async with run_deps(chat, Cache()) as deps, _client(deps) as client:
        response = await client.post("/runs", json=BODY)

    lines: Final = response.text.splitlines()
    payloads: Final = tuple(line.removeprefix("data: ") for line in lines if line.startswith("data: "))
    parsed: Final = tuple(_EVENT.validate_json(payload) for payload in payloads)

    assert parsed
    assert tuple(event.kind for event in parsed) == _named(lines)
    assert _named(lines).count("phase_started") == _named(lines).count("phase_finished")
