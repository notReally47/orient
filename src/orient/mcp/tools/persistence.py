"""The write boundary: where prose becomes a stored summary, or is refused.

Every check that must not be skippable lives here rather than in whoever is driving the loop. A
caller cannot forget the grounding check, because the only way to finish is to pass it, and a
refusal is a tool result the model can act on rather than an error somebody has to catch.

The evidence is re-derived rather than remembered. Signals, backdrop and calendar for a session
are deterministic and, after the first run, come from the bar cache, so the check can be run
against exactly what the tools would have served without the server holding per-run state.
"""

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Annotated, Final

from mcp.server import MCPServer
from pydantic import Field

from orient.domain import grounding, sections
from orient.domain.models import (
    Claim,
    Instrument,
    ReadingLevel,
    Summary,
)
from orient.domain.signals import compute_signals
from orient.llm import extraction, judge
from orient.llm.chat import Answered, SystemMessage, UserMessage
from orient.llm.embeddings import EmbeddingError
from orient.mcp.deps import ToolDeps
from orient.mcp.results import SaveOutcome

SIGNALS_LOOKBACK: Final = timedelta(days=400)
CALENDAR_DAYS: Final = 7
WATCH_HORIZON: Final = timedelta(days=7)

EXTRACTION_FRAMING: Final = """\
Read the summary below and return JSON only.

`annotations` are terms the summary used that a reader at this level may not know, each defined
for the way this summary used it rather than generically.

`claims` are only what could not be recomputed from the measurements. Do not restate a figure:
"the index rose 0.65%" is already in the numbers and is not a claim. Record a cause the summary
asserted, with `attribution` naming it. Record a forward-looking statement only when it says what
would have to happen for it to be judged, not that a scheduled event is scheduled. Record an
anomaly whenever the summary said something could not be explained.

`mentioned_symbols` are tickers, never company names.
"""


async def _measured(deps: ToolDeps, symbol: str, session_date: date) -> tuple[Mapping[str, object], ...]:
    """Everything a summary may quote, re-derived rather than remembered across the run.

    The profile counts as evidence even though it is reference data rather than a measurement.
    It carries the instrument's name and its 52-week range, and to a check that cannot tell a
    name from a figure, "S&P 500" is a numeral the summary has to be allowed to write.
    """
    bars = await deps.prices.bars(symbol, session_date - SIGNALS_LOOKBACK, session_date)
    signals = compute_signals(symbol, bars)
    profile = await deps.reference.profile(symbol)
    backdrop = await deps.market.backdrop(session_date)
    calendar = await deps.calendars.entries(session_date, session_date + timedelta(days=CALENDAR_DAYS))
    measured = (signals, profile, backdrop, calendar)
    return tuple(item.model_dump(mode="json") for item in measured if item is not None)


def register(server: MCPServer, deps: ToolDeps) -> None:
    @server.tool()
    async def save_summary(
        symbol: Annotated[str, Field(description="The instrument the summary is about")],
        session_date: Annotated[date, Field(description="The session it describes")],
        level: Annotated[ReadingLevel, Field(description="The reading level it was written for")],
        markdown: Annotated[str, Field(description="The finished summary, thesis then four sections")],
    ) -> SaveOutcome:
        """Store the finished summary, once every figure in it reconciles with what was measured.

        This is the only way a summary comes into existence. The markdown is parsed into its
        sections, every numeral in the prose is checked against the measurements for this session,
        and prose quoting a figure nobody measured is refused rather than stored. A refusal names
        the figures: fix those and call this again.

        A figure from a news article is not a measurement and will be refused. A summary that
        reconciles but reads badly for its level is refused too, on the same terms.
        """
        draft = sections.parse(markdown)
        evidence = await _measured(deps, symbol, session_date)
        verdict = grounding.check(sections.prose(draft), grounding.measured(evidence), session_date)
        if isinstance(verdict, grounding.Ungrounded):
            return SaveOutcome(
                outcome="refused",
                reason="grounding",
                figures=verdict.figures,
                detail=(
                    "These figures appear in the summary but were not measured: "
                    f"{', '.join(verdict.figures)}. Rewrite so every figure quoted is one the "
                    "tools returned, dropping any sentence that cannot be written without one."
                ),
            )

        review = await deps.judge.review(sections.prose(draft))
        if isinstance(review, judge.Blocked):
            return SaveOutcome(outcome="refused", reason="quality", detail=review.detail)

        profile = await deps.reference.profile(symbol)
        signals = compute_signals(symbol, await deps.prices.bars(symbol, session_date - SIGNALS_LOOKBACK, session_date))
        if signals is None or profile.asset_class is None:
            return SaveOutcome(
                outcome="refused",
                reason="unfiled",
                detail=f"{symbol} has no price history or no asset class",
            )

        await deps.instruments.upsert(
            Instrument(
                symbol=symbol,
                asset_class=profile.asset_class,
                name=profile.name or symbol,
                sector=profile.sector,
                exchange=profile.exchange,
                currency=profile.currency,
            )
        )
        await deps.sessions.upsert(signals)

        extracted = await _extract(deps, markdown)
        calendar = await deps.calendars.entries(session_date, session_date + timedelta(days=CALENDAR_DAYS))
        summary = Summary(
            id=deps.new_id(),
            symbol=symbol,
            session_date=signals.session_date,
            level=level,
            status="ok",
            thesis=draft.thesis,
            sections=draft.sections,
            calendar=calendar.entries,
            signals_snapshot=signals,
            annotations=extracted.annotations,
        )
        await deps.summaries.add(summary)
        await _remember(deps, summary, extracted)
        return SaveOutcome(
            outcome="saved",
            summary_id=summary.id,
            session_date=signals.session_date,
            sections=len(draft.sections),
            claims=len(extracted.claims),
        )

    _ = save_summary


async def _extract(deps: ToolDeps, markdown: str) -> extraction.Extraction:
    answer: Final = await deps.chat.complete(
        model=deps.fast_model,
        messages=[SystemMessage(content=EXTRACTION_FRAMING), UserMessage(content=markdown)],
        schema=extraction.SCHEMA,
    )
    if not isinstance(answer, Answered):
        return extraction.Extraction()
    return extraction.parse(answer.message.content)


async def _remember(deps: ToolDeps, summary: Summary, extracted: extraction.Extraction) -> None:
    """An embedding the proxy would not serve costs the claims, never the summary."""
    claims: Final = tuple(
        Claim(
            id=deps.new_id(),
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
        vectors = await deps.embeddings.embed([claim.statement for claim in claims])
    except EmbeddingError:
        return
    await deps.claims.add(claims, vectors)


def _due(target: date | None, expected: bool, session_date: date) -> date | None:
    if target is not None or not expected:
        return target
    return session_date + WATCH_HORIZON
