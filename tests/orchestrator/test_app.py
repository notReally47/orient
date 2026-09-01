"""The HTTP surface, driven through the real routes over fakes.

The stream is the contract the GUI is built against, so what gets asserted is that a run's events
reach the wire in order, under their own event names, and that the whole thing ends.
"""

from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from datetime import date
from typing import Final, cast
from uuid import UUID

import httpx
from pydantic import TypeAdapter

from orient.domain.models import Returns, Section, Signals, Summary, TrendDistance
from orient.orchestrator.app import create_app
from orient.orchestrator.deps import RunDeps
from orient.orchestrator.events import Event
from tests.orchestrator.fakes import (
    SESSION_DATE,
    SYMBOL,
    Cache,
    RecordingTools,
    RefusingTools,
    ScriptedChat,
    answered,
    run_deps,
    saving,
)


def _summary() -> Summary:
    """One stored row, as a revisit would find it."""
    return Summary(
        id=UUID(int=42),
        symbol=SYMBOL,
        session_date=SESSION_DATE,
        level="beginner",
        status="ok",
        thesis="The index gave back Monday's gain",
        sections=(Section(heading="The big picture", body="It fell with the market."),),
        signals_snapshot=Signals(
            symbol=SYMBOL,
            session_date=SESSION_DATE,
            close=100.0,
            returns=Returns(),
            trend=TrendDistance(),
        ),
    )


BODY: Final = {"symbol": "^GSPC", "session_date": SESSION_DATE.isoformat(), "level": "beginner"}
_EVENT: Final[TypeAdapter[Event]] = TypeAdapter(Event)
_SUMMARY: Final[TypeAdapter[Summary]] = TypeAdapter(Summary)
_DAYS: Final[TypeAdapter[list[str]]] = TypeAdapter(list[str])
_BODY: Final[TypeAdapter[dict[str, object]]] = TypeAdapter(dict[str, object])
_ROWS: Final[TypeAdapter[list[dict[str, object]]]] = TypeAdapter(list[dict[str, object]])


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


async def test_instruments_are_searched_through_the_tool_server() -> None:
    """The browser never holds an MCP client of its own, so search comes back through here."""
    async with run_deps(ScriptedChat(), Cache()) as deps, _client(deps) as client:
        response = await client.get("/instruments", params={"q": "apple", "limit": 3})

    assert response.status_code == 200
    matches: Final = _ROWS.validate_python(_BODY.validate_json(response.content)["matches"])
    assert matches
    assert matches[0]["symbol"]


async def test_a_price_window_is_served_for_the_chart() -> None:
    async with run_deps(ScriptedChat(), Cache()) as deps, _client(deps) as client:
        response = await client.get("/prices/^GSPC", params={"session_date": SESSION_DATE.isoformat(), "days": 30})

    assert response.status_code == 200
    assert _BODY.validate_json(response.content)["bars"]


async def test_a_tool_that_will_not_answer_is_a_gateway_error_rather_than_a_crash() -> None:
    """A dead tool server must reach the browser as something it can show, not a stack trace."""
    async with (
        run_deps(ScriptedChat(), Cache(), catalog=RefusingTools("the tool server is down")) as deps,
        _client(deps) as client,
    ):
        response = await client.get("/instruments", params={"q": "apple"})

    assert response.status_code == 502
    assert "down" in str(_BODY.validate_json(response.content)["detail"])


async def test_stored_summaries_are_listed_without_their_prose() -> None:
    """A picker needs the thesis and the key, not four sections and a snapshot per row."""
    async with run_deps(ScriptedChat(), Cache(_summary())) as deps, _client(deps) as client:
        response = await client.get("/summaries")

    page: Final = _BODY.validate_json(response.content)
    listed: Final = _ROWS.validate_python(page["entries"])
    assert [entry["symbol"] for entry in listed] == [SYMBOL]
    assert "sections" not in listed[0]


async def test_a_listing_says_how_many_matched_so_a_page_can_be_counted_against_it() -> None:
    """A reader shown twelve rows has no way to tell whether that is all of them."""
    async with run_deps(ScriptedChat(), Cache(_summary())) as deps, _client(deps) as client:
        response = await client.get("/summaries", params={"limit": 1})

    assert _BODY.validate_json(response.content)["total"] == 1


async def test_a_listing_can_be_narrowed_to_one_instrument_and_one_reading_level() -> None:
    """Filtering after the fact means fetching everything first, which is the thing to avoid."""
    async with run_deps(ScriptedChat(), Cache(_summary())) as deps, _client(deps) as client:
        missed = await client.get("/summaries", params={"symbol": "NOPE"})
        wrong_level = await client.get("/summaries", params={"level": "advanced"})

    assert _BODY.validate_json(missed.content)["total"] == 0
    assert _BODY.validate_json(wrong_level.content)["total"] == 0


async def test_the_instruments_with_something_on_file_are_served_for_the_filter() -> None:
    """A filter offering an instrument nothing was written about is a dead end."""
    async with run_deps(ScriptedChat(), Cache(_summary())) as deps, _client(deps) as client:
        response = await client.get("/written")

    assert [entry["symbol"] for entry in _ROWS.validate_json(response.content)] == [SYMBOL]


async def test_one_stored_summary_is_served_in_full_for_a_revisit() -> None:
    """Revisiting renders from the row alone, so everything the page draws has to be in it."""
    stored: Final = _summary()

    async with run_deps(ScriptedChat(), Cache(stored)) as deps, _client(deps) as client:
        response = await client.get(f"/summaries/{stored.id}")

    assert response.status_code == 200
    body: Final = _SUMMARY.validate_json(response.content)
    assert body.thesis == stored.thesis
    assert body.signals_snapshot.close == stored.signals_snapshot.close


async def test_a_summary_that_was_never_written_is_a_clean_not_found() -> None:
    async with run_deps(ScriptedChat(), Cache()) as deps, _client(deps) as client:
        response = await client.get(f"/summaries/{UUID(int=7)}")

    assert response.status_code == 404


async def test_the_sessions_offered_are_the_ones_the_instrument_actually_traded() -> None:
    """Which days exist belongs to the instrument, not the calendar: an index skips weekends and a
    crypto pair skips nothing, and offering a day that never traded files the summary elsewhere."""
    async with run_deps(ScriptedChat(), Cache()) as deps, _client(deps) as client:
        response = await client.get(f"/sessions/{SYMBOL}", params={"limit": 5})

    assert response.status_code == 200
    traded: Final = [date.fromisoformat(day) for day in _DAYS.validate_json(response.content)]
    assert traded
    assert traded == sorted(traded, reverse=True)


async def test_searching_can_be_narrowed_to_one_asset_class() -> None:
    """A phrase matches across kinds: "S&P 500" alone returns the futures ahead of the index."""
    async with run_deps(ScriptedChat(), Cache(), catalog=RecordingTools()) as deps, _client(deps) as client:
        _ = await client.get("/instruments", params={"q": "s&p", "asset_class": "index"})

    asked: Final = cast("RecordingTools", deps.tools).calls[-1]
    assert '"asset_class": "index"' in asked
