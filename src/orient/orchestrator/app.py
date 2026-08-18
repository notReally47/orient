"""The HTTP surface: a health check and one streaming run.

Dependencies are built by an injected async context manager, so a test drives the real routes over
fakes without a database or a proxy behind them.

Cancellation needs no token of its own. The client disconnecting is the signal, and it is checked
between tool calls by the loop itself.
"""

import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from datetime import date
from typing import Final

from fastapi import FastAPI, Request
from sse_starlette import EventSourceResponse, ServerSentEvent

from orient.domain.models import Frozen, ReadingLevel
from orient.orchestrator.agent import RunRequest, run
from orient.orchestrator.deps import RunDeps
from orient.orchestrator.events import Event, as_sse

TITLE: Final = "orient orchestrator"
UNREADY: Final = 503

Build = Callable[[], AbstractAsyncContextManager[RunDeps]]


class RunBody(Frozen):
    symbol: str
    session_date: date
    level: ReadingLevel


class Health(Frozen):
    status: str
    tools: int


class _Ready:
    """Holds what the lifespan built, so a route reads a typed value rather than untyped app state."""

    def __init__(self) -> None:
        self.deps: RunDeps | None = None


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
        return Health(status="ok", tools=len(deps.tools.schemas()))

    @application.post("/runs")
    async def start(request: Request, body: RunBody) -> EventSourceResponse:
        deps = ready.deps
        if deps is None:
            return EventSourceResponse(iter(()), status_code=UNREADY)
        return EventSourceResponse(_stream(request, body, deps))

    _ = (health, start)
    return application
