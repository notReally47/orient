"""Everything a run reaches for, passed in rather than imported.

Storage is named by Protocol rather than by class. The loop is meant to be liftable by another
department, and a loop that names `psycopg` in its type signatures is not; it also lets a test
drive the real code path over records held in memory rather than over canned SQL rows in order.

The `psycopg`-backed repositories satisfy these structurally, so nothing implements them by name.
"""

from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from orient.config import Settings
from orient.domain.models import (
    Claim,
    Instrument,
    ModelUsage,
    Run,
    RunStatus,
    Signals,
    Summary,
    SummaryKey,
)
from orient.llm.chat import ChatModel
from orient.orchestrator.skills import Skills
from orient.orchestrator.tools import ToolCatalog


class Summaries(Protocol):
    async def find(self, key: SummaryKey, /) -> Summary | None: ...

    async def add(self, summary: Summary, /) -> None: ...


class Sessions(Protocol):
    async def recent(self, symbol: str, version: str, /) -> tuple[Signals, ...]: ...

    async def upsert(self, signals: Signals, /) -> None: ...


class Claims(Protocol):
    async def open_for(self, symbol: str, /) -> tuple[Claim, ...]: ...

    async def add(self, claims: Sequence[Claim], embeddings: Sequence[Sequence[float]], /) -> None: ...


class Instruments(Protocol):
    async def upsert(self, instrument: Instrument, /) -> None: ...


class Runs(Protocol):
    async def start(self, run: Run, /) -> None: ...

    async def finish(
        self,
        run_id: UUID,
        status: RunStatus,
        phase_timings: Mapping[str, float],
        model_usage: Sequence[ModelUsage],
        /,
    ) -> None: ...


class Embeddings(Protocol):
    async def embed(self, texts: Sequence[str], /) -> tuple[tuple[float, ...], ...]: ...


def now() -> datetime:
    return datetime.now(tz=UTC)


def no_trace() -> str | None:
    return None


@contextmanager
def no_span(name: str) -> Generator[None]:
    del name
    yield


Span = Callable[[str], AbstractContextManager[None]]


@dataclass(frozen=True, slots=True)
class RunDeps:
    settings: Settings
    chat: ChatModel
    tools: ToolCatalog
    skills: Skills
    embeddings: Embeddings
    instruments: Instruments
    sessions: Sessions
    summaries: Summaries
    claims: Claims
    runs: Runs
    clock: Callable[[], datetime] = now
    new_id: Callable[[], UUID] = uuid4
    trace_id: Callable[[], str | None] = no_trace
    span: Span = no_span
