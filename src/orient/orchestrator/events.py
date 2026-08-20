"""What a run says about itself while it happens.

Every event is a frozen model tagged with a `kind` and threaded through the loop as an injected
emitter, so a nested step reports progress by returning a value rather than by reaching for a
logger. A step that reports nothing is indistinguishable from a step that hung.
"""

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Annotated, Final, Literal
from uuid import UUID

from pydantic import Field
from sse_starlette import ServerSentEvent

from orient.domain.models import Frozen, ReadingLevel, RunStatus, SummaryStatus

Rejection = Literal["grounding", "judge"]


class RunStarted(Frozen):
    kind: Literal["run_started"] = "run_started"
    run_id: UUID
    symbol: str
    session_date: date
    level: ReadingLevel


class CacheHit(Frozen):
    kind: Literal["cache_hit"] = "cache_hit"
    summary_id: UUID


class TurnFinished(Frozen):
    """One model turn: what it cost and which tools it asked for.

    A run's shape is decided by the model, so a turn is the unit a caller can count, and this is
    the only place spend is visible while the run is still going."""

    kind: Literal["turn_finished"] = "turn_finished"
    turn: int
    seconds: float
    prompt_tokens: int
    completion_tokens: int
    tools: tuple[str, ...] = ()


class SkillLoaded(Frozen):
    """Which tier of which skill the model chose to pay for, so on-demand loading is observable."""

    kind: Literal["skill_loaded"] = "skill_loaded"
    skill: str
    tier: Literal["body", "reference"]
    characters: int
    path: str | None = None


class SummaryRefused(Frozen):
    """The write boundary turned a draft away. The model sees the same detail and tries again."""

    kind: Literal["summary_refused"] = "summary_refused"
    reason: str
    detail: str


class ToolStarted(Frozen):
    kind: Literal["tool_started"] = "tool_started"
    tool: str
    arguments: str


class ToolFinished(Frozen):
    kind: Literal["tool_finished"] = "tool_finished"
    tool: str
    ok: bool
    detail: str


class ThesisReady(Frozen):
    kind: Literal["thesis_ready"] = "thesis_ready"
    thesis: str


class SectionReady(Frozen):
    kind: Literal["section_ready"] = "section_ready"
    heading: str
    body: str


class RunFinished(Frozen):
    kind: Literal["run_finished"] = "run_finished"
    status: SummaryStatus
    summary_id: UUID


class RunFailed(Frozen):
    kind: Literal["run_failed"] = "run_failed"
    status: RunStatus
    detail: str


Event = Annotated[
    RunStarted
    | CacheHit
    | TurnFinished
    | SkillLoaded
    | SummaryRefused
    | ToolStarted
    | ToolFinished
    | ThesisReady
    | SectionReady
    | RunFinished
    | RunFailed,
    Field(discriminator="kind"),
]

Emit = Callable[[Event], Awaitable[None]]

ARGUMENT_PREVIEW: Final = 600


def as_sse(event: Event) -> ServerSentEvent:
    """The tag becomes the SSE event name, so a client subscribes per kind rather than parsing."""
    return ServerSentEvent(event=event.kind, data=event.model_dump_json())
