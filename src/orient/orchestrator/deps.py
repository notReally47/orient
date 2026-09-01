"""Everything a run reaches for, passed in rather than imported.

Storage is named by Protocol rather than by class. The loop is meant to be liftable by another
department, and a loop that names `psycopg` in its type signatures is not; it also lets a test
drive the real code path over records held in memory rather than over canned SQL rows in order.

The `psycopg`-backed repositories satisfy these structurally, so nothing implements them by name.
"""

from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from orient.config import Settings
from orient.domain.models import Shelf, Summary, SummaryKey, Written
from orient.llm.chat import ChatModel
from orient.orchestrator.tools import ToolCatalog
from orient.skills.loader import Skills


class Summaries(Protocol):
    """Reading only. Writing happens behind `save_summary`, which this side cannot reach."""

    async def find(self, key: SummaryKey, /) -> Summary | None: ...

    async def browse(
        self,
        symbol: str | None = ...,
        level: str | None = ...,
        limit: int = ...,
        offset: int = ...,
        /,
    ) -> Shelf: ...

    async def written(self) -> tuple[Written, ...]: ...

    async def by_id(self, summary_id: UUID, /) -> Summary | None: ...


def now() -> datetime:
    return datetime.now(tz=UTC)


def no_trace() -> str | None:
    return None


def as_uuid(value: str) -> UUID:
    """The tool server answers with an id as text; a malformed one must not end the run."""
    try:
        return UUID(value)
    except ValueError:
        return uuid4()


@contextmanager
def no_span(name: str) -> Generator[None]:
    del name
    yield


Span = Callable[[str], AbstractContextManager[None]]


@dataclass(frozen=True, slots=True)
class RunDeps:
    """What one run reaches for: a model, a tool surface, the skill catalog and the cache.

    Storage is one read. Writing happens behind `save_summary` on the tool server, so the loop
    holds no repository it could write through and no guarantee it could forget to apply.
    """

    settings: Settings
    chat: ChatModel
    tools: ToolCatalog
    skills: Skills
    summaries: Summaries
    clock: Callable[[], datetime] = now
    new_id: Callable[[], UUID] = uuid4
    trace_id: Callable[[], str | None] = no_trace
    as_uuid: Callable[[str], UUID] = as_uuid
    span: Span = no_span
