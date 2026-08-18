"""What a run says about itself while it happens.

Every event is a frozen model tagged with a `kind` and threaded through the loop as an injected
emitter, so a nested step reports progress by returning a value rather than by reaching for a
logger. A worker whose tool calls were invisible is exactly what made `workflow` undebuggable.
"""

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Annotated, Final, Literal
from uuid import UUID

from pydantic import Field
from sse_starlette import ServerSentEvent

from orient.domain.models import Frozen, Phase, ReadingLevel, RunStatus, SummaryStatus

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


class PhaseStarted(Frozen):
    kind: Literal["phase_started"] = "phase_started"
    phase: Phase


class PhaseFinished(Frozen):
    kind: Literal["phase_finished"] = "phase_finished"
    phase: Phase
    seconds: float


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


class DraftRejected(Frozen):
    """Why a draft is being written again, so the caller sees a revise rather than a stall."""

    kind: Literal["draft_rejected"] = "draft_rejected"
    reason: Rejection
    detail: str
    attempt: int


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
    | PhaseStarted
    | PhaseFinished
    | ToolStarted
    | ToolFinished
    | ThesisReady
    | SectionReady
    | DraftRejected
    | RunFinished
    | RunFailed,
    Field(discriminator="kind"),
]

Emit = Callable[[Event], Awaitable[None]]

ARGUMENT_PREVIEW: Final = 200


def as_sse(event: Event) -> ServerSentEvent:
    """The tag becomes the SSE event name, so a client subscribes per kind rather than parsing."""
    return ServerSentEvent(event=event.kind, data=event.model_dump_json())
