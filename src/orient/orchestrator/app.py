"""The HTTP surface: one streaming run, and the reads a front end needs to build a request.

Dependencies are built by an injected async context manager, so a test drives the real routes over
fakes without a database or a proxy behind them.

This is the only surface the browser talks to. The tool server stays behind it, which is what
keeps `save_summary` unreachable from a client: the reads below expose searching, listing and
price history, and nothing that writes. Instrument search and price history are served by asking
the tool catalog this process already holds, so the front end needs no MCP client of its own.

Cancellation needs no token of its own. The client disconnecting is the signal, and it is checked
between tool calls by the loop itself.
"""

import asyncio
import json
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from datetime import date
from typing import Final
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from pydantic import TypeAdapter, ValidationError
from sse_starlette import EventSourceResponse, ServerSentEvent

from orient.domain.models import AssetClass, Frozen, ReadingLevel, Shelf, Summary, Written
from orient.mcp.results import PriceHistory
from orient.orchestrator.agent import RunRequest, run
from orient.orchestrator.deps import RunDeps
from orient.orchestrator.events import Event, as_sse
from orient.orchestrator.tools import Succeeded

TITLE: Final = "orient orchestrator"
UNREADY: Final = 503
UNAVAILABLE: Final = 502
NOT_FOUND: Final = 404

DISCOVER_TOOL: Final = "discover_instruments"
PRICES_TOOL: Final = "get_price_history"
DEFAULT_MATCHES: Final = 8
DEFAULT_SESSIONS: Final = 60
DEFAULT_LISTED: Final = 12
MAX_LISTED: Final = 100
DEFAULT_WINDOW: Final = 180

_PAYLOAD: Final[TypeAdapter[dict[str, object]]] = TypeAdapter(dict[str, object])
_HISTORY: Final = TypeAdapter(PriceHistory)

Build = Callable[[], AbstractAsyncContextManager[RunDeps]]


class RunBody(Frozen):
    symbol: str
    session_date: date
    level: ReadingLevel


class Health(Frozen):
    status: str
    tools: int
    max_turns: int = 0


class _Ready:
    """Holds what the lifespan built, so a route reads a typed value rather than untyped app state."""

    def __init__(self) -> None:
        self.deps: RunDeps | None = None


def _ready(deps: RunDeps | None) -> RunDeps:
    if deps is None:
        raise HTTPException(status_code=UNREADY, detail="the orchestrator is still starting")
    return deps


async def _through_tools(deps: RunDeps, tool: str, arguments: dict[str, object]) -> dict[str, object]:
    """One tool call, answered as JSON or refused as a gateway error the caller can show."""
    outcome: Final = await deps.tools.execute(tool, json.dumps(arguments))
    if not isinstance(outcome, Succeeded):
        raise HTTPException(status_code=UNAVAILABLE, detail=outcome.detail)
    try:
        return _PAYLOAD.validate_json(outcome.payload)
    except ValidationError as exc:
        raise HTTPException(status_code=UNAVAILABLE, detail=f"{tool} answered unreadably") from exc


def _traded(window: dict[str, object]) -> list[date]:
    """The dates a price window holds bars for, newest first, read back as the tool's own type."""
    try:
        history: Final = _HISTORY.validate_python(window)
    except ValidationError:
        return []
    return sorted({bar.session_date for bar in history.bars}, reverse=True)


async def _stream(request: Request, body: RunBody, deps: RunDeps) -> AsyncGenerator[ServerSentEvent, None]:
    queue: Final[asyncio.Queue[Event | None]] = asyncio.Queue()

    async def emit(event: Event) -> None:
        await queue.put(event)

    async def drive() -> None:
        try:
            await run(
                RunRequest(symbol=body.symbol, session_date=body.session_date, level=body.level),
                deps,
                emit,
                request.is_disconnected,
            )
        finally:
            await queue.put(None)

    driver: Final = asyncio.create_task(drive())
    try:
        while (event := await queue.get()) is not None:
            yield as_sse(event)
    finally:
        _ = driver.cancel()
        with suppress(asyncio.CancelledError):
            await driver


def create_app(build: Build) -> FastAPI:
    """The service, over a factory that yields its dependencies for the lifetime of the process.

    Taking the factory rather than the dependencies is what lets a test drive every route against
    fakes through the real ASGI app.
    """
    ready: Final = _Ready()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        del app
        async with build() as deps:
            ready.deps = deps
            yield
        ready.deps = None

    application: Final = FastAPI(title=TITLE, lifespan=lifespan)

    @application.get("/health")
    async def health() -> Health:
        """The probe's fourteenth check: booted, and able to see the tool server it will call."""
        deps = ready.deps
        if deps is None:
            return Health(status="starting", tools=0)
        return Health(status="ok", tools=len(deps.tools.schemas()), max_turns=deps.settings.max_turns)

    @application.post("/runs")
    async def start(request: Request, body: RunBody) -> EventSourceResponse:
        deps = ready.deps
        if deps is None:
            return EventSourceResponse(iter(()), status_code=UNREADY)
        return EventSourceResponse(_stream(request, body, deps))

    @application.get("/instruments")
    async def instruments(
        q: str = "",
        screen: str | None = None,
        asset_class: AssetClass | None = None,
        limit: int = DEFAULT_MATCHES,
    ) -> dict[str, object]:
        """Search for something to summarise, or list a screen of what is moving today."""
        deps = _ready(ready.deps)
        asked: dict[str, object] = {"limit": limit}
        if screen:
            asked["screen"] = screen
        else:
            asked["query"] = q
            if asset_class:
                asked["asset_class"] = asset_class
        return await _through_tools(deps, DISCOVER_TOOL, asked)

    @application.get("/prices/{symbol:path}")
    async def prices(symbol: str, session_date: date, days: int = DEFAULT_WINDOW) -> dict[str, object]:
        """The series behind a price chart. Served from stored bars once a session has been read."""
        deps = _ready(ready.deps)
        return await _through_tools(
            deps, PRICES_TOOL, {"symbol": symbol, "session_date": session_date.isoformat(), "days": days}
        )

    @application.get("/sessions/{symbol:path}")
    async def sessions(symbol: str, limit: int = DEFAULT_SESSIONS) -> list[date]:
        """The sessions this instrument actually traded, newest first.

        Which days exist is a property of the instrument rather than of the calendar: an index
        skips weekends and public holidays, a crypto pair skips nothing. Offering a day that never
        traded produces a summary filed under a different date than the one that was asked for,
        which then never matches on the way back out.
        """
        deps = _ready(ready.deps)
        window = await _through_tools(
            deps,
            PRICES_TOOL,
            {"symbol": symbol, "session_date": date.today().isoformat(), "days": DEFAULT_WINDOW},  # noqa: DTZ011
        )
        return _traded(window)[:limit]

    @application.get("/written")
    async def written() -> list[Written]:
        """Which instruments have something on file, so a filter offers only what exists."""
        deps = _ready(ready.deps)
        return list(await deps.summaries.written())

    @application.get("/summaries")
    async def summaries(
        symbol: str | None = None,
        level: ReadingLevel | None = None,
        limit: int = DEFAULT_LISTED,
        offset: int = 0,
    ) -> Shelf:
        """One screen of what has been written, newest first, with the total.

        The page is cut in SQL rather than here. An archive grows without bound and a screen does
        not, so what leaves this route is the size of the screen and a count of what is behind it.
        """
        deps = _ready(ready.deps)
        return await deps.summaries.browse(symbol, level, min(limit, MAX_LISTED), max(offset, 0))

    @application.get("/summaries/{summary_id}")
    async def summary(summary_id: UUID) -> Summary:
        """One stored summary in full, which is everything a reader can be shown without a run."""
        deps = _ready(ready.deps)
        found = await deps.summaries.by_id(summary_id)
        if found is None:
            raise HTTPException(status_code=NOT_FOUND, detail=f"no summary with id {summary_id}")
        return found

    _ = (health, start, instruments, prices, sessions, written, summaries, summary)
    return application
