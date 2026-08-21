"""One run: a cache lookup, then a model deciding what to do until the summary is accepted.

Nothing is fetched before the model has spoken. What an instrument's session needs is a
judgement, and the instrument skill is where that judgement is written down: an index and a
currency pair want different evidence, so the choice belongs to whoever read the skill.

The run ends on an outcome rather than a step count. Prose existing is not enough; the run is over
when `save_summary` accepts it, which happens on the tool server behind the grounding check. A
caller cannot skip that check, because passing it is the only way to finish.

Nothing here raises at the caller. Every way a run can end, cancellation and an unreachable proxy
included, is a value the caller receives as an event.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final

import anyio
from pydantic import TypeAdapter, ValidationError

from orient.domain import sections
from orient.domain.models import ReadingLevel, RunStatus, Section, SummaryKey
from orient.llm.chat import (
    Answered,
    Message,
    Rejected,
    SystemMessage,
    ToolCall,
    ToolResult,
    Unavailable,
    UserMessage,
)
from orient.orchestrator import prompts
from orient.orchestrator.deps import RunDeps
from orient.orchestrator.events import (
    ARGUMENT_PREVIEW,
    CacheHit,
    Emit,
    RunFailed,
    RunFinished,
    RunStarted,
    SectionReady,
    SkillLoaded,
    SummaryRefused,
    ThesisReady,
    ToolFinished,
    ToolStarted,
    TurnFinished,
)
from orient.orchestrator.tools import Refused, Succeeded
from orient.skills.loader import as_catalog

Cancelled = Callable[[], Awaitable[bool]]

SAVE_TOOL: Final = "save_summary"
ACTIVATE_TOOL: Final = "activate_skill"
RESOURCE_TOOL: Final = "read_skill_resource"

# Quality review happens inside `save_summary`, because a summary travels as a tool-call
# argument and the proxy's post-call judge only ever sees assistant text.
GUARDRAILS: Final = ("headroom-compression", "tool-budget")

_JSON: Final = TypeAdapter(dict[str, object])


@dataclass(frozen=True, slots=True)
class RunRequest:
    symbol: str
    session_date: date
    level: ReadingLevel


@dataclass(frozen=True, slots=True)
class _Done:
    summary_id: str
    markdown: str


@dataclass(frozen=True, slots=True)
class _Stopped:
    status: RunStatus
    detail: str


async def never_cancelled() -> bool:
    return False


def _arguments(raw: str) -> Mapping[str, object]:
    try:
        return _JSON.validate_json(raw or "{}")
    except ValidationError:
        return {}


def _reply(call: ToolCall, outcome: Succeeded | Refused) -> ToolResult:
    """A refusal answers the call rather than vanishing: a transcript missing one confuses the model."""
    body: Final = outcome.payload if isinstance(outcome, Succeeded) else f"error: {outcome.detail}"
    return ToolResult(tool_call_id=call.id, content=body)


class _Run:
    def __init__(self, request: RunRequest, deps: RunDeps, emit: Emit, cancelled: Cancelled) -> None:
        self._request: Final = request
        self._deps: Final = deps
        self._emit: Final = emit
        self._cancelled: Final = cancelled
        self._id: Final = deps.new_id()
        self._session: Final = str(self._id)
        self._tags: Final = (
            f"symbol:{request.symbol}",
            f"session:{request.session_date:%Y-%m-%d}",
            f"level:{request.level}",
            "phase:agent",
        )

    async def execute(self) -> None:
        await self._emit(
            RunStarted(
                run_id=self._id,
                symbol=self._request.symbol,
                session_date=self._request.session_date,
                level=self._request.level,
            )
        )

        cached: Final = await self._deps.summaries.find(self._key())
        if cached is not None:
            await self._emit(CacheHit(summary_id=cached.id))
            await self._announce(cached.thesis, cached.sections)
            await self._emit(RunFinished(status=cached.status, summary_id=cached.id))
            return

        outcome: Final = await self._drive()
        if isinstance(outcome, _Stopped):
            await self._emit(RunFailed(status=outcome.status, detail=outcome.detail))
            return

        draft: Final = sections.parse(outcome.markdown)
        await self._announce(draft.thesis, draft.sections)
        await self._emit(RunFinished(status="ok", summary_id=self._deps.as_uuid(outcome.summary_id)))

    def _key(self) -> SummaryKey:
        return SummaryKey(
            symbol=self._request.symbol,
            session_date=self._request.session_date,
            level=self._request.level,
        )

    async def _announce(self, thesis: str, parts: Sequence[Section]) -> None:
        await self._emit(ThesisReady(thesis=thesis))
        for part in parts:
            await self._emit(SectionReady(heading=part.heading, body=part.body))

    def _opening(self) -> tuple[Message, ...]:
        """Tier one and nothing else. The bodies are the model's to ask for."""
        catalog: Final = as_catalog(self._deps.skills.catalog())
        subject: Final = prompts.Subject(
            symbol=self._request.symbol,
            session_date=self._request.session_date,
            level=self._request.level,
        )
        return (
            SystemMessage(content=f"{prompts.AGENT_FRAMING}\n\n{catalog}"),
            UserMessage(content=prompts.brief(subject)),
        )

    async def _drive(self) -> _Done | _Stopped:
        transcript: tuple[Message, ...] = self._opening()
        nudged = False

        for turn in range(1, self._deps.settings.max_turns + 1):
            if await self._cancelled():
                return _Stopped(status="cancelled", detail="the caller disconnected")

            started = self._deps.clock()
            answer = await self._deps.chat.complete(
                model=self._deps.settings.gather_model,
                messages=transcript,
                tools=self._deps.tools.schemas(),
                guardrails=GUARDRAILS,
                tags=self._tags,
                session=self._session,
            )
            match answer:
                case Unavailable():
                    return _Stopped(status="failed", detail=answer.detail)
                case Rejected():
                    transcript = (*transcript, UserMessage(content=prompts.blocked(answer.feedback)))
                    continue
                case Answered():
                    pass

            await self._emit(
                TurnFinished(
                    turn=turn,
                    seconds=(self._deps.clock() - started).total_seconds(),
                    prompt_tokens=answer.spend.prompt_tokens,
                    completion_tokens=answer.spend.completion_tokens,
                    tools=tuple(call.name for call in answer.message.tool_calls),
                )
            )
            transcript = (*transcript, answer.message)

            if not answer.message.tool_calls:
                if nudged:
                    return _Stopped(status="failed", detail="the model stopped without saving a summary")
                nudged = True
                transcript = (*transcript, UserMessage(content=prompts.UNFINISHED))
                continue

            replies, done = await self._round(answer.message.tool_calls)
            transcript = (*transcript, *replies)
            if done is not None:
                return done

        return _Stopped(status="failed", detail=f"no summary after {self._deps.settings.max_turns} turns")

    async def _round(self, calls: Sequence[ToolCall]) -> tuple[tuple[ToolResult, ...], _Done | None]:
        """A turn's calls run together. The model issued them at once because they do not depend
        on each other, and running them in series spends that for nothing."""
        outcomes: Final[dict[str, Succeeded | Refused]] = {}

        async def one(call: ToolCall) -> None:
            outcomes[call.id] = await self._call(call.name, call.arguments)

        async with anyio.create_task_group() as group:
            for call in calls:
                group.start_soon(one, call)

        replies: Final = tuple(_reply(call, outcomes[call.id]) for call in calls)
        finished: Final = next(
            (done for call in calls if (done := _finished(call, outcomes[call.id])) is not None),
            None,
        )
        return replies, finished

    async def _call(self, name: str, arguments: str) -> Succeeded | Refused:
        await self._emit(ToolStarted(tool=name, arguments=arguments[:ARGUMENT_PREVIEW]))
        with self._deps.span(f"tool.{name}"):
            outcome = await self._deps.tools.execute(name, arguments, self._session)
        match outcome:
            case Succeeded():
                await self._emit(ToolFinished(tool=name, ok=True, detail=f"{len(outcome.payload)} characters"))
                await self._noticed(name, arguments, outcome)
            case Refused():
                await self._emit(ToolFinished(tool=name, ok=False, detail=outcome.detail))
        return outcome

    async def _noticed(self, name: str, arguments: str, outcome: Succeeded) -> None:
        """Two things earn their own event: which tier of a skill the model chose to pay for, and
        the grounding gate turning a summary away."""
        asked: Final = _arguments(arguments)
        if name in {ACTIVATE_TOOL, RESOURCE_TOOL}:
            path = asked.get("path")
            await self._emit(
                SkillLoaded(
                    skill=str(asked.get("skill") or asked.get("name") or "?"),
                    tier="body" if name == ACTIVATE_TOOL else "reference",
                    path=str(path) if path is not None else None,
                    characters=len(outcome.payload),
                )
            )
        structured: Final = outcome.structured or {}
        if name == SAVE_TOOL and structured.get("outcome") == "refused":
            await self._emit(
                SummaryRefused(
                    reason=str(structured.get("reason")),
                    detail=str(structured.get("detail", "")),
                )
            )


def _finished(call: ToolCall, outcome: Succeeded | Refused) -> _Done | None:
    """A save that came back with an id is the run's terminating condition; a refusal is not."""
    if call.name != SAVE_TOOL or not isinstance(outcome, Succeeded) or outcome.structured is None:
        return None
    if outcome.structured.get("outcome") != "saved":
        return None
    saved: Final = outcome.structured.get("summary_id")
    if saved is None:
        return None
    return _Done(summary_id=str(saved), markdown=str(_arguments(call.arguments).get("markdown", "")))


async def run(request: RunRequest, deps: RunDeps, emit: Emit, cancelled: Cancelled = never_cancelled) -> None:
    """The whole run. Every way it can end reaches the caller as an event, never as an exception."""
    try:
        await _Run(request, deps, emit, cancelled).execute()
    except Exception as exc:  # noqa: BLE001  # the caller is a stream, and a stream cannot catch
        await emit(RunFailed(status="failed", detail=f"{type(exc).__name__}: {' '.join(str(exc).split())[:300]}"))
