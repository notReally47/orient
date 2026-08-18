"""One run: the phases, the tool loop and the revise loop.

Deterministic work happens before and after the model, never through it. Code fetches the
measurements, code reconciles the figures that came back, and the model chooses what to research
and writes the prose in between.

Nothing here raises at the caller. Every way a run can end, cancellation and a judge that would
not accept another draft included, is a value the caller receives as an event.
"""

import json
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from types import MappingProxyType
from typing import Final

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from orient.domain.models import (
    SIGNALS_VERSION,
    AssetClass,
    Calendar,
    CalendarEntry,
    Claim,
    Instrument,
    ModelUsage,
    Phase,
    ReadingLevel,
    Run,
    RunStatus,
    Signals,
    Summary,
    SummaryKey,
    SummaryStatus,
)
from orient.llm.chat import (
    Answered,
    Message,
    Rejected,
    Spend,
    SystemMessage,
    ToolCall,
    ToolResult,
    Unavailable,
    UserMessage,
)
from orient.llm.embeddings import EmbeddingError
from orient.orchestrator import extraction, grounding, prompts, sections
from orient.orchestrator.deps import RunDeps
from orient.orchestrator.events import (
    ARGUMENT_PREVIEW,
    CacheHit,
    DraftRejected,
    Emit,
    PhaseFinished,
    PhaseStarted,
    Rejection,
    RunFailed,
    RunFinished,
    RunStarted,
    SectionReady,
    ThesisReady,
    ToolFinished,
    ToolStarted,
)
from orient.orchestrator.extraction import Extraction
from orient.orchestrator.sections import Draft
from orient.orchestrator.skills import rendered
from orient.orchestrator.tools import Refused, Succeeded

Cancelled = Callable[[], Awaitable[bool]]
Payloads = Mapping[str, Mapping[str, object]]

SIGNALS_TOOL: Final = "compute_instrument_signals"
PROFILE_TOOL: Final = "get_instrument_profile"
CONTEXT_TOOL: Final = "get_market_context"
CALENDAR_TOOL: Final = "get_calendar"

# News is somebody's claim about the market rather than a measurement, so its figures never
# join the set a draft may quote from.
UNQUOTABLE: Final = frozenset({"search_news"})

GATHER_GUARDRAILS: Final = ("headroom-compression",)
WRITE_GUARDRAILS: Final = ("headroom-compression", "quality-judge")

# "What to watch this week" is the section an expectation comes from, so that is when it is due.
WATCH_HORIZON: Final = timedelta(days=7)

_SIGNALS: Final = TypeAdapter(Signals)
_CALENDAR: Final = TypeAdapter(Calendar)


@dataclass(frozen=True, slots=True)
class RunRequest:
    symbol: str
    session_date: date
    level: ReadingLevel


class _Profile(BaseModel):
    """Read leniently: the profile carries far more than the instruments table stores."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    asset_class: AssetClass | None = None
    sector: str | None = None
    exchange: str | None = None
    currency: str | None = None


@dataclass(frozen=True, slots=True)
class _Measured:
    signals: Signals
    instrument: Instrument
    calendar: tuple[CalendarEntry, ...]
    payloads: Payloads


@dataclass(frozen=True, slots=True)
class _Gathered:
    transcript: tuple[Message, ...]
    quotable: tuple[Mapping[str, object], ...]


@dataclass(frozen=True, slots=True)
class _Accepted:
    draft: Draft
    status: SummaryStatus


@dataclass(frozen=True, slots=True)
class _Stopped:
    status: RunStatus
    detail: str


class _Ledger:
    """Timings and spend, accumulated across a run and written once at its end.

    Spend is keyed by phase as well as model, so the record says where a run's tokens went rather
    than only how many there were.
    """

    def __init__(self) -> None:
        self._timings: dict[str, float] = {}
        self._usage: dict[tuple[Phase, str], ModelUsage] = {}

    def timed(self, phase: Phase, seconds: float) -> None:
        self._timings[phase] = self._timings.get(phase, 0.0) + seconds

    def spent(self, phase: Phase, model: str, spend: Spend) -> None:
        entry: Final = ModelUsage(
            phase=phase,
            model=model,
            calls=spend.calls,
            prompt_tokens=spend.prompt_tokens,
            completion_tokens=spend.completion_tokens,
        )
        running: Final = self._usage.get((phase, model))
        self._usage[phase, model] = entry if running is None else running.plus(entry)

    @property
    def timings(self) -> Mapping[str, float]:
        return MappingProxyType(dict(self._timings))

    @property
    def usage(self) -> tuple[ModelUsage, ...]:
        return tuple(self._usage.values())


def _instrument(symbol: str, payload: Mapping[str, object]) -> Instrument | None:
    """None when the profile did not classify it, since an unclassified instrument cannot be filed."""
    profile: Final = _Profile.model_validate(payload)
    if profile.asset_class is None:
        return None
    return Instrument(
        symbol=symbol,
        asset_class=profile.asset_class,
        name=profile.name or symbol,
        sector=profile.sector,
        exchange=profile.exchange,
        currency=profile.currency,
    )


def _reply(call: ToolCall, outcome: Succeeded | Refused) -> ToolResult:
    """A refusal answers the call rather than vanishing: a transcript missing one confuses the model."""
    body: Final = outcome.payload if isinstance(outcome, Succeeded) else f"error: {outcome.detail}"
    return ToolResult(tool_call_id=call.id, content=body)


async def never_cancelled() -> bool:
    return False


class _Run:
    def __init__(self, request: RunRequest, deps: RunDeps, emit: Emit, cancelled: Cancelled) -> None:
        self._request: Final = request
        self._deps: Final = deps
        self._emit: Final = emit
        self._cancelled: Final = cancelled
        self._ledger: Final = _Ledger()
        self._id: Final = deps.new_id()
        self._subject: Final = prompts.Subject(
            symbol=request.symbol,
            session_date=request.session_date,
            level=request.level,
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

        async with self._phase("cache"):
            cached = await self._deps.summaries.find(self._key())
        if cached is not None:
            await self._replay(cached)
            return

        await self._deps.runs.start(
            Run(
                id=self._id,
                symbol=self._request.symbol,
                session_date=self._request.session_date,
                level=self._request.level,
                status="running",
                trace_id=self._deps.trace_id(),
            )
        )

        produced: Final = await self._produce()
        if isinstance(produced, _Stopped):
            await self._finish(produced.status)
            await self._emit(RunFailed(status=produced.status, detail=produced.detail))
            return

        accepted, measured = produced
        summary: Final = await self._persist(accepted, measured)
        await self._finish(accepted.status)
        await self._emit(RunFinished(status=accepted.status, summary_id=summary.id))

    def _key(self) -> SummaryKey:
        return SummaryKey(
            symbol=self._request.symbol,
            session_date=self._request.session_date,
            level=self._request.level,
        )

    async def _finish(self, status: RunStatus) -> None:
        await self._deps.runs.finish(self._id, status, self._ledger.timings, self._ledger.usage)

    @asynccontextmanager
    async def _phase(self, phase: Phase) -> AsyncGenerator[None, None]:
        await self._emit(PhaseStarted(phase=phase))
        started: Final = self._deps.clock()
        try:
            with self._deps.span(f"phase.{phase}"):
                yield
        finally:
            elapsed = (self._deps.clock() - started).total_seconds()
            self._ledger.timed(phase, elapsed)
            await self._emit(PhaseFinished(phase=phase, seconds=elapsed))

    async def _replay(self, summary: Summary) -> None:
        await self._emit(CacheHit(summary_id=summary.id))
        await self._announce(Draft(thesis=summary.thesis, sections=summary.sections))
        await self._emit(RunFinished(status=summary.status, summary_id=summary.id))

    async def _announce(self, draft: Draft) -> None:
        await self._emit(ThesisReady(thesis=draft.thesis))
        for section in draft.sections:
            await self._emit(SectionReady(heading=section.heading, body=section.body))

    async def _produce(self) -> tuple[_Accepted, _Measured] | _Stopped:
        async with self._phase("recall"):
            history = await self._deps.sessions.recent(self._request.symbol, SIGNALS_VERSION)
            open_claims = await self._deps.claims.open_for(self._request.symbol)

        async with self._phase("prefetch"):
            prefetched = await self._prefetch()
        if isinstance(prefetched, _Stopped):
            return prefetched

        opening: Final = (
            SystemMessage(
                content=prompts.RESEARCH_FRAMING
                + "\n\n"
                + rendered(self._deps.skills.research(prefetched.instrument.asset_class))
            ),
            UserMessage(
                content="\n\n".join(
                    (
                        prompts.brief(self._subject),
                        prompts.evidence(prefetched.payloads),
                        prompts.recall(history, open_claims),
                    )
                )
            ),
        )

        async with self._phase("gather"):
            gathered = await self._gather(opening, tuple(prefetched.payloads.values()))
        if isinstance(gathered, _Stopped):
            return gathered

        async with self._phase("write"):
            written = await self._write(gathered)
        if isinstance(written, _Stopped):
            return written
        return written, prefetched

    async def _prefetch(self) -> _Measured | _Stopped:
        subject: Final = json.dumps({"symbol": self._request.symbol})
        requested: Final = (
            (SIGNALS_TOOL, subject),
            (PROFILE_TOOL, subject),
            (CONTEXT_TOOL, "{}"),
            (CALENDAR_TOOL, "{}"),
        )
        outcomes: Final = tuple([(name, await self._call(name, arguments)) for name, arguments in requested])

        refused: Final = tuple(
            f"{name}: {outcome.detail}" for name, outcome in outcomes if isinstance(outcome, Refused)
        )
        if refused:
            return _Stopped(status="failed", detail="; ".join(refused))

        payloads: Final[Payloads] = MappingProxyType(
            {name: outcome.structured or {} for name, outcome in outcomes if isinstance(outcome, Succeeded)}
        )
        try:
            signals = _SIGNALS.validate_python(payloads[SIGNALS_TOOL])
        except ValidationError as exc:
            return _Stopped(status="failed", detail=f"signals did not validate: {exc.error_count()} problem(s)")

        instrument: Final = _instrument(self._request.symbol, payloads[PROFILE_TOOL])
        if instrument is None:
            return _Stopped(
                status="failed",
                detail=f"{self._request.symbol} came back with no asset class, so it cannot be filed",
            )
        return _Measured(
            signals=signals,
            instrument=instrument,
            calendar=_CALENDAR.validate_python(payloads[CALENDAR_TOOL]).entries,
            payloads=payloads,
        )

    async def _call(self, name: str, arguments: str) -> Succeeded | Refused:
        await self._emit(ToolStarted(tool=name, arguments=arguments[:ARGUMENT_PREVIEW]))
        with self._deps.span(f"tool.{name}"):
            outcome = await self._deps.tools.execute(name, arguments)
        match outcome:
            case Succeeded():
                await self._emit(ToolFinished(tool=name, ok=True, detail=f"{len(outcome.payload)} characters"))
            case Refused():
                await self._emit(ToolFinished(tool=name, ok=False, detail=outcome.detail))
        return outcome

    async def _gather(
        self,
        opening: Sequence[Message],
        measured: Sequence[Mapping[str, object]],
    ) -> _Gathered | _Stopped:
        transcript: tuple[Message, ...] = tuple(opening)
        quotable: tuple[Mapping[str, object], ...] = tuple(measured)

        for _ in range(self._deps.settings.gather_max_iterations):
            if await self._cancelled():
                return _Stopped(status="cancelled", detail="the caller disconnected")

            answer = await self._deps.chat.complete(
                model=self._deps.settings.primary_model,
                messages=transcript,
                tools=self._deps.tools.schemas(),
                guardrails=GATHER_GUARDRAILS,
            )
            match answer:
                case Unavailable():
                    return _Stopped(status="failed", detail=answer.detail)
                case Rejected():
                    return _Stopped(status="failed", detail=answer.feedback)
                case Answered():
                    self._ledger.spent("gather", self._deps.settings.primary_model, answer.spend)

            transcript = (*transcript, answer.message)
            if not answer.message.tool_calls:
                return _Gathered(transcript=transcript, quotable=quotable)

            replies, gained = await self._round(answer.message.tool_calls)
            transcript = (*transcript, *replies)
            quotable = (*quotable, *gained)

        return _Gathered(transcript=transcript, quotable=quotable)

    async def _round(
        self,
        calls: Sequence[ToolCall],
    ) -> tuple[tuple[ToolResult, ...], tuple[Mapping[str, object], ...]]:
        outcomes: Final = tuple([(call, await self._call(call.name, call.arguments)) for call in calls])
        gained: Final = tuple(
            outcome.structured
            for call, outcome in outcomes
            if isinstance(outcome, Succeeded) and outcome.structured and call.name not in UNQUOTABLE
        )
        return tuple(_reply(call, outcome) for call, outcome in outcomes), gained

    async def _write(self, gathered: _Gathered) -> _Accepted | _Stopped:
        quotable: Final = grounding.measured(gathered.quotable)
        instruction: Final = UserMessage(
            content=prompts.WRITING_FRAMING + "\n\n" + rendered(self._deps.skills.writing(self._request.level))
        )
        transcript: tuple[Message, ...] = (*gathered.transcript, instruction)
        latest: Draft | None = None

        for attempt in range(self._deps.settings.revise_max_attempts + 1):
            final = attempt == self._deps.settings.revise_max_attempts
            answer = await self._deps.chat.complete(
                model=self._deps.settings.primary_model,
                messages=transcript,
                guardrails=WRITE_GUARDRAILS,
            )
            match answer:
                case Unavailable():
                    return _Stopped(status="failed", detail=answer.detail)
                case Rejected():
                    if final:
                        return self._exhausted(latest, "judge", answer.feedback)
                    await self._emit(DraftRejected(reason="judge", detail=answer.feedback, attempt=attempt + 1))
                    transcript = (*transcript, UserMessage(content=prompts.revise("judge", answer.feedback)))
                    continue
                case Answered():
                    self._ledger.spent("write", self._deps.settings.primary_model, answer.spend)

            draft = sections.parse(answer.message.content)
            latest = draft
            async with self._phase("check"):
                verdict = grounding.check(sections.prose(draft), quotable, self._request.session_date)
            if isinstance(verdict, grounding.Grounded):
                return _Accepted(draft=draft, status="ok")

            unmatched = ", ".join(verdict.figures)
            if final:
                return _Accepted(draft=draft, status="caveated")
            await self._emit(DraftRejected(reason="grounding", detail=unmatched, attempt=attempt + 1))
            transcript = (
                *transcript,
                answer.message,
                UserMessage(content=prompts.revise("grounding", unmatched)),
            )

        return _Stopped(status="failed", detail="the write phase produced nothing")

    def _exhausted(self, latest: Draft | None, reason: Rejection, detail: str) -> _Accepted | _Stopped:
        """A blocked answer carries no prose, so exhaustion can only be caveated if a draft survived."""
        if latest is None:
            return _Stopped(status="failed", detail=f"rejected on {reason} with nothing to fall back on: {detail}")
        return _Accepted(draft=latest, status="caveated")

    async def _extract(self, draft: Draft) -> Extraction:
        async with self._phase("extract"):
            answer = await self._deps.chat.complete(
                model=self._deps.settings.fast_model,
                messages=[
                    SystemMessage(content=prompts.EXTRACTION_FRAMING),
                    UserMessage(content=sections.as_markdown(draft)),
                ],
                schema=extraction.SCHEMA,
            )
        if not isinstance(answer, Answered):
            return Extraction()
        self._ledger.spent("extract", self._deps.settings.fast_model, answer.spend)
        return extraction.parse(answer.message.content)

    async def _persist(self, accepted: _Accepted, measured: _Measured) -> Summary:
        await self._announce(accepted.draft)
        extracted: Final = await self._extract(accepted.draft)

        async with self._phase("persist"):
            await self._deps.instruments.upsert(measured.instrument)
            await self._deps.sessions.upsert(measured.signals)
            summary = Summary(
                id=self._deps.new_id(),
                symbol=self._request.symbol,
                session_date=self._request.session_date,
                level=self._request.level,
                status=accepted.status,
                thesis=accepted.draft.thesis,
                sections=accepted.draft.sections,
                calendar=measured.calendar,
                signals_snapshot=measured.signals,
                annotations=extracted.annotations,
                run_id=self._id,
            )
            await self._deps.summaries.add(summary)
            await self._remember(summary, extracted)
        return summary

    async def _remember(self, summary: Summary, extracted: Extraction) -> None:
        """The narrative layer. An embedding the proxy would not serve costs the claims, not the summary."""
        claims: Final = tuple(
            Claim(
                id=self._deps.new_id(),
                summary_id=summary.id,
                subject_symbol=summary.symbol,
                session_date=summary.session_date,
                kind=entry.kind,
                statement=entry.statement,
                mentioned_symbols=entry.mentioned_symbols,
                attribution=entry.attribution,
                target_date=_due(entry.target_date, entry.kind == "expectation", summary.session_date),
            )
            for entry in extracted.claims
        )
        if not claims:
            return
        try:
            vectors = await self._deps.embeddings.embed([claim.statement for claim in claims])
        except EmbeddingError:
            return
        await self._deps.claims.add(claims, vectors)


def _due(target: date | None, expected: bool, session_date: date) -> date | None:
    if target is not None or not expected:
        return target
    return session_date + WATCH_HORIZON


async def run(request: RunRequest, deps: RunDeps, emit: Emit, cancelled: Cancelled = never_cancelled) -> None:
    """The whole run. Every way it can end reaches the caller as an event, never as an exception."""
    try:
        await _Run(request, deps, emit, cancelled).execute()
    except Exception as exc:  # noqa: BLE001  # the caller is a stream, and a stream cannot catch
        await emit(RunFailed(status="failed", detail=f"{type(exc).__name__}: {' '.join(str(exc).split())[:300]}"))
