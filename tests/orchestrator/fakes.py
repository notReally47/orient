"""A whole run's dependencies, with only the model and the storage replaced.

The tool catalog is the real one over the real tool server, connected in process, so a run's
prefetch goes through the same schemas, the same validation and the same structured content the
container would. The model is scripted because a run's control flow is what these tests are for.

Storage is held in memory rather than as canned SQL rows, so an assertion reads what the run
stored rather than which statement it issued. What the SQL does is tested against a real Postgres.
"""

from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Final, TypeVar
from uuid import UUID

from pydantic import BaseModel

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
from orient.llm.chat import (
    Answered,
    AssistantMessage,
    Completion,
    Message,
    Spend,
    ToolCall,
    ToolSchema,
    Unavailable,
)
from orient.mcp.server import create_server
from orient.orchestrator.deps import RunDeps
from orient.orchestrator.events import Event
from orient.orchestrator.skills import Skills
from orient.orchestrator.tools import Refused, ToolCatalog, connect
from tests.mcp.fakes import tool_deps

SESSION_DATE: Final = date(2026, 8, 12)
DIMENSIONS: Final = 4
TICK: Final = timedelta(milliseconds=250)


@dataclass(frozen=True, slots=True)
class Asked:
    model: str
    messages: tuple[Message, ...]
    tools: tuple[str, ...]
    guardrails: tuple[str, ...]
    schema: Mapping[str, object] | None

    @property
    def last(self) -> str:
        return self.messages[-1].content


class ScriptedChat:
    """Answers from a queue and records every request, which is how the transcript gets asserted."""

    def __init__(self, *answers: Completion) -> None:
        self._answers: Final[list[Completion]] = list(answers)
        self.asked: Final[list[Asked]] = []

    async def complete(
        self,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema] = (),
        guardrails: Sequence[str] = (),
        schema: Mapping[str, object] | None = None,
    ) -> Completion:
        self.asked.append(
            Asked(
                model=model,
                messages=tuple(messages),
                tools=tuple(entry.name for entry in tools),
                guardrails=tuple(guardrails),
                schema=schema,
            )
        )
        if not self._answers:
            return Unavailable("the script ran out")
        return self._answers.pop(0)


@dataclass(slots=True)
class Store:
    """Every repository the run writes through, so one object is the whole record of what it did."""

    summaries: list[Summary] = field(default_factory=list)
    instruments: list[Instrument] = field(default_factory=list)
    sessions: list[Signals] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    vectors: list[tuple[float, ...]] = field(default_factory=list)
    runs: list[Run] = field(default_factory=list)
    finished: list[tuple[UUID, RunStatus, Mapping[str, float], Sequence[ModelUsage]]] = field(default_factory=list)
    cached: Summary | None = None
    history: tuple[Signals, ...] = ()
    open_claims: tuple[Claim, ...] = ()

    async def find(self, key: SummaryKey) -> Summary | None:
        return self.cached if self.cached is not None and self.cached.key == key else None

    async def add(self, summary: Summary) -> None:
        self.summaries.append(summary)

    async def recent(self, symbol: str, version: str) -> tuple[Signals, ...]:
        del symbol, version
        return self.history

    async def upsert(self, value: Signals | Instrument) -> None:
        if isinstance(value, Signals):
            self.sessions.append(value)
        else:
            self.instruments.append(value)

    async def open_for(self, symbol: str) -> tuple[Claim, ...]:
        del symbol
        return self.open_claims

    async def add_claims(self, claims: Sequence[Claim], embeddings: Sequence[Sequence[float]]) -> None:
        self.claims.extend(claims)
        self.vectors.extend(tuple(vector) for vector in embeddings)

    async def start(self, run: Run) -> None:
        self.runs.append(run)

    async def finish(
        self,
        run_id: UUID,
        status: RunStatus,
        phase_timings: Mapping[str, float],
        model_usage: Sequence[ModelUsage],
    ) -> None:
        self.finished.append((run_id, status, phase_timings, model_usage))

    async def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return tuple((float(len(text)),) * DIMENSIONS for text in texts)


class _Claims:
    """`add` differs in name between the claim and summary repositories, so it gets its own face."""

    def __init__(self, store: Store) -> None:
        self._store: Final = store

    async def open_for(self, symbol: str) -> tuple[Claim, ...]:
        return await self._store.open_for(symbol)

    async def add(self, claims: Sequence[Claim], embeddings: Sequence[Sequence[float]]) -> None:
        await self._store.add_claims(claims, embeddings)


class RefusingTools:
    """A catalog whose every call fails, for the paths where the tool server is the thing broken."""

    def __init__(self, detail: str = "the tool server is not answering") -> None:
        self._detail: Final = detail

    def schemas(self) -> tuple[ToolSchema, ...]:
        return ()

    async def execute(self, name: str, arguments: str) -> Refused:
        del arguments
        return Refused(tool=name, detail=self._detail)


class _Ids:
    def __init__(self) -> None:
        self._next: int = 0

    def __call__(self) -> UUID:
        self._next += 1
        return UUID(int=self._next)


class _Clock:
    """Advances a fixed tick per read, so phase timings are deterministic and non-zero."""

    def __init__(self) -> None:
        self._now: datetime = datetime(2026, 8, 12, 21, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self._now += TICK
        return self._now


def settings(**overrides: object) -> Settings:
    return Settings.model_validate(
        {
            "database_url": "postgresql://unused/unused",
            "proxy_api_key": "sk-test",
            "gather_max_iterations": 3,
            "revise_max_attempts": 1,
            **overrides,
        }
    )


Emitted = TypeVar("Emitted", bound=BaseModel)


class Recorder:
    def __init__(self) -> None:
        self.events: Final[list[Event]] = []

    async def __call__(self, event: Event) -> None:
        self.events.append(event)

    def kinds(self) -> tuple[str, ...]:
        return tuple(event.kind for event in self.events)

    def only(self, kind: type[Emitted]) -> tuple[Emitted, ...]:
        """Narrowed by class rather than by tag, so an assertion reads the event's own fields."""
        return tuple(event for event in self.events if isinstance(event, kind))


@asynccontextmanager
async def run_deps(
    chat: ScriptedChat,
    store: Store,
    catalog: ToolCatalog | None = None,
    **overrides: object,
) -> AsyncGenerator[RunDeps, None]:
    async with tool_deps() as tools, connect(create_server(tools)) as served:
        yield RunDeps(
            settings=settings(**overrides),
            chat=chat,
            tools=catalog if catalog is not None else served,
            skills=Skills(),
            embeddings=store,
            instruments=store,
            sessions=store,
            summaries=store,
            claims=_Claims(store),
            runs=store,
            clock=_Clock(),
            new_id=_Ids(),
        )


GROUNDED: Final = """\
# Apple gave back Monday's gain alongside its sector

## The big picture

It fell with the rest of technology rather than on anything of its own.

## What moved, and why

The sector led the decline, and nothing company specific explains the rest.
"""

UNGROUNDED: Final = """\
# Apple fell 1.93% on the day

## The big picture

It fell 1.93%, its worst session in weeks.
"""

EXTRACTED: Final = """\
{
  "annotations": [{"term": "breadth", "definition": "how many sectors rose against how many fell"}],
  "claims": [
    {"kind": "observation", "statement": "Apple fell with its sector", "attribution": "sector wide decline"},
    {"kind": "expectation", "statement": "Earnings land next week"}
  ]
}
"""


def answered(content: str = "", calls: tuple[ToolCall, ...] = ()) -> Answered:
    return Answered(
        message=AssistantMessage(content=content, tool_calls=calls),
        spend=Spend(prompt_tokens=10, completion_tokens=5),
    )


def calls_calendar() -> tuple[ToolCall, ...]:
    return (ToolCall(id="call_1", name="get_calendar", arguments="{}"),)
