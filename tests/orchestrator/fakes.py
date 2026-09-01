"""What a run is driven over when there is no proxy and no database.

The tool surface is real: a server built over canned providers, reached through the same MCP
client the container uses. Only the model is scripted, because the thing under test is what the
loop does with the answers rather than what a model would produce.
"""

from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Final, TypeVar
from uuid import UUID

from pydantic import BaseModel

from orient.config import Settings
from orient.domain.models import Listing, Shelf, Summary, SummaryKey, Written
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
from orient.orchestrator.tools import Outcome, Refused, Succeeded, connect
from orient.skills.loader import Skills
from tests.mcp.fakes import TODAY, tool_deps
from tests.store.fakes import FakePool

SYMBOL: Final = "^GSPC"
SESSION_DATE: Final = TODAY
TICK: Final = timedelta(milliseconds=250)


@dataclass(frozen=True, slots=True)
class Asked:
    model: str
    messages: tuple[Message, ...]
    tools: tuple[str, ...]
    guardrails: tuple[str, ...]
    tags: tuple[str, ...]
    session: str | None

    @property
    def system(self) -> str:
        return self.messages[0].content if self.messages else ""


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
        tags: Sequence[str] = (),
        session: str | None = None,
    ) -> Completion:
        del schema
        self.asked.append(
            Asked(
                model=model,
                messages=tuple(messages),
                tools=tuple(entry.name for entry in tools),
                guardrails=tuple(guardrails),
                tags=tuple(tags),
                session=session,
            )
        )
        if not self._answers:
            return Answered(message=AssistantMessage(content="nothing further"), spend=Spend())
        return self._answers.pop(0)


class Cache:
    """The reads the orchestrator owns: the loop's cache lookup and the listings a front end asks
    for. Writing happens behind `save_summary` on the tool server, so nothing here can store."""

    def __init__(self, cached: Summary | None = None) -> None:
        self.cached: Final = cached
        self.asked: Final[list[SummaryKey]] = []

    def _all(self) -> tuple[Summary, ...]:
        return () if self.cached is None else (self.cached,)

    async def find(self, key: SummaryKey) -> Summary | None:
        self.asked.append(key)
        return self.cached if self.cached is not None and self.cached.key == key else None

    async def browse(
        self,
        symbol: str | None = None,
        level: str | None = None,
        limit: int = 12,
        offset: int = 0,
    ) -> Shelf:
        matched: Final = tuple(
            entry
            for entry in self._all()
            if (symbol is None or entry.symbol == symbol) and (level is None or entry.level == level)
        )
        window: Final = matched[offset : offset + limit]
        return Shelf(
            total=len(matched),
            entries=tuple(
                Listing(
                    id=entry.id,
                    symbol=entry.symbol,
                    session_date=entry.session_date,
                    level=entry.level,
                    thesis=entry.thesis,
                )
                for entry in window
            ),
        )

    async def written(self) -> tuple[Written, ...]:
        return tuple(Written(symbol=entry.symbol, count=1, latest=entry.session_date) for entry in self._all())

    async def by_id(self, summary_id: UUID) -> Summary | None:
        return next((entry for entry in self._all() if entry.id == summary_id), None)


class RefusingTools:
    """A catalog whose every call fails, for the paths where the tool server is the broken thing."""

    def __init__(self, detail: str = "the tool server is not answering") -> None:
        self._detail: Final = detail

    def schemas(self) -> tuple[ToolSchema, ...]:
        return ()

    async def execute(self, name: str, arguments: str, session: str | None = None) -> Outcome:
        del arguments, session
        return Refused(tool=name, detail=self._detail)


class RecordingTools:
    """A catalog that answers emptily and keeps the arguments it was handed, for asserting what
    a route asked the tool server for rather than what it did with the answer."""

    def __init__(self) -> None:
        self.calls: Final[list[str]] = []

    def schemas(self) -> tuple[ToolSchema, ...]:
        return ()

    async def execute(self, name: str, arguments: str, session: str | None = None) -> Outcome:
        del session
        self.calls.append(arguments)
        return Succeeded(tool=name, payload="{}", structured={})


class _Ids:
    def __init__(self) -> None:
        self._next: int = 0

    def __call__(self) -> UUID:
        self._next += 1
        return UUID(int=self._next)


class _Clock:
    """Advances a fixed tick per read, so turn timings are deterministic and non-zero."""

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
            "max_turns": 6,
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
    cache: Cache | None = None,
    catalog: RefusingTools | RecordingTools | None = None,
    pool: FakePool | None = None,
    **overrides: object,
) -> AsyncGenerator[RunDeps, None]:
    async with tool_deps(pool) as tools, connect(create_server(tools)) as served:
        yield RunDeps(
            settings=settings(**overrides),
            chat=chat,
            tools=catalog if catalog is not None else served,
            skills=Skills(),
            summaries=cache if cache is not None else Cache(),
            clock=_Clock(),
            new_id=_Ids(),
        )


GROUNDED: Final = """\
# The index gave back Monday's gain alongside its sector

## The big picture

It fell with the rest of the market rather than on anything of its own.

## What moved, and why

The sector led the decline, and nothing instrument specific explains the rest.
"""

UNGROUNDED: Final = """\
# The index fell 41.93% on the day

## The big picture

It fell 41.93%, its worst session in weeks.
"""


def answered(content: str = "", calls: tuple[ToolCall, ...] = ()) -> Answered:
    return Answered(
        message=AssistantMessage(content=content, tool_calls=calls),
        spend=Spend(prompt_tokens=10, completion_tokens=5),
    )


def unavailable(detail: str = "the proxy is unreachable") -> Unavailable:
    return Unavailable(detail)


def calls(*wanted: tuple[str, str]) -> tuple[ToolCall, ...]:
    return tuple(
        ToolCall(id=f"call_{index}", name=name, arguments=arguments)
        for index, (name, arguments) in enumerate(wanted, start=1)
    )


def saving(markdown: str = GROUNDED, session: date = SESSION_DATE) -> tuple[ToolCall, ...]:
    import json  # noqa: PLC0415  # only the fixture needs to build wire arguments

    return calls(
        (
            "save_summary",
            json.dumps(
                {
                    "symbol": SYMBOL,
                    "session_date": session.isoformat(),
                    "level": "beginner",
                    "markdown": markdown,
                }
            ),
        )
    )
