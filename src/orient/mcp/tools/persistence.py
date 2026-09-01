"""The write boundary: where prose becomes a stored summary, or is turned back.

Two tools rather than one. `check_summary` answers what is wrong and writes nothing, so a draft
can be fixed for the cost of the checks; `save_summary` re-runs them, asks the judge, and stores.
Every check that must not be skippable lives on this side, because the only way to finish is to
pass it.
"""

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Annotated, Final

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context
from pydantic import Field

from orient import correlation
from orient.domain import faults, sections
from orient.domain.market import EarningsReaction
from orient.domain.models import Calendar, Instrument, Panel, ReadingLevel, Summary, Term
from orient.llm import judge
from orient.mcp import drafts, knowledge
from orient.mcp.deps import ToolDeps
from orient.mcp.drafts import CALENDAR_DAYS
from orient.mcp.measure import gathered
from orient.mcp.results import Checked, Explained, Fault, Page, SaveOutcome, Settled

MARKDOWN = Annotated[str, Field(description="The finished summary, thesis then four sections")]
SYMBOL = Annotated[str, Field(description="The instrument the summary is about")]
SESSION = Annotated[date, Field(description="The session it describes")]
LEVEL = Annotated[ReadingLevel, Field(description="The reading level it was written for")]

BLANK_PAGE: Final = Page()


async def _reactions(deps: ToolDeps, symbol: str, asset_class: str | None) -> tuple[EarningsReaction, ...]:
    if asset_class != "equity":
        return ()
    detail: Final = await gathered(deps.earnings.detail(symbol))
    return getattr(detail, "reactions", ())


def _reported(found: Sequence[faults.Fault]) -> tuple[Fault, ...]:
    return tuple(Fault(kind=fault.kind, items=fault.items, detail=fault.detail) for fault in found)


def register(server: MCPServer, deps: ToolDeps) -> None:
    @server.tool()
    async def check_summary(
        symbol: SYMBOL,
        session_date: SESSION,
        markdown: MARKDOWN,
        glossary: Annotated[
            tuple[Explained, ...],
            Field(
                description=(
                    "The definitions you intend to submit, so they are checked here rather than "
                    "refused at the save. A definition is held to the same figure rule as the "
                    "prose."
                )
            ),
        ] = (),
    ) -> Checked:
        """Everything wrong with a draft, without storing anything.

        Cheap and repeatable: call it as often as you like while the summary is taking shape. It
        finds every mechanical fault at once rather than the first one, so a rewrite can fix them
        together instead of discovering the next only after the last is gone.

        `ok` means nothing mechanical is wrong with the draft. Call `save_summary` next rather
        than checking again: it re-runs these, and the only thing left is a reviewer reading the
        prose for its level, which this cannot tell you and a second check will not either.
        """
        against = await drafts.grounds(deps, symbol, session_date)
        if against is None:
            return Checked(ok=False)
        found = drafts.wrong_with(
            sections.prose(sections.parse(markdown)),
            against,
            session_date,
            tuple(entry.meaning for entry in glossary),
        )
        return Checked(ok=not found, faults=_reported(found))

    @server.tool()
    async def save_summary(
        symbol: SYMBOL,
        session_date: SESSION,
        level: LEVEL,
        markdown: MARKDOWN,
        context: Context,
        page: Annotated[
            Page,
            Field(
                description=(
                    "How the summary is presented: the figures beside it, the ones that lead it, "
                    "and the terms it explains. Read references/page.md and references/visuals.md."
                )
            ),
        ] = BLANK_PAGE,
        settles: Annotated[
            tuple[Settled, ...],
            Field(
                description=(
                    "Verdicts on expectations earlier summaries left open, by the id "
                    "`recall_history` returned. An expectation nobody settles is handed to every "
                    "later summary forever, so close the ones this session answers."
                )
            ),
        ] = (),
    ) -> SaveOutcome:
        """Store the finished summary. The only way one comes into existence.

        Runs the same checks as `check_summary`, then asks a reviewer whether the prose reads for
        its level, then writes. A refusal names what to fix and stores nothing.

        Cite measurements rather than typing them: `{{close}}` in the prose becomes the measured
        close, formatted for this instrument. A figure you cite cannot be wrong, and a figure you
        type has to survive the check.
        """
        session = correlation.of(context)
        draft = sections.parse(markdown)
        prose = sections.prose(draft)

        against = await drafts.grounds(deps, symbol, session_date)
        filed = None if against is None else against.filed()
        if against is None or filed is None:
            return SaveOutcome(
                outcome="refused",
                reason="unfiled",
                detail=f"{symbol} has no price history or no asset class",
            )

        found = drafts.wrong_with(prose, against, session_date, tuple(entry.meaning for entry in page.glossary))
        if found:
            return SaveOutcome(
                outcome="refused",
                reason="faults",
                figures=tuple(item for fault in found for item in fault.items),
                detail=" ".join(fault.detail for fault in found),
                faults=_reported(found),
            )

        review = await deps.judge.review(against.rendered(prose), session)
        if isinstance(review, judge.Blocked):
            return SaveOutcome(outcome="refused", reason="quality", detail=review.detail)

        profile, signals = filed, against.signals
        await deps.instruments.add(
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

        calendar = await gathered(deps.calendars.entries(session_date, session_date + timedelta(days=CALENDAR_DAYS)))
        summary = Summary(
            id=deps.new_id(),
            symbol=symbol,
            session_date=signals.session_date,
            level=level,
            status="ok",
            thesis=draft.thesis,
            sections=draft.sections,
            calendar=calendar.entries if isinstance(calendar, Calendar) else (),
            holdings=profile.holdings,
            reactions=await _reactions(deps, symbol, profile.asset_class),
            layout=tuple(Panel(name=panel.name, section=panel.section) for panel in page.layout),
            tiles=page.tiles,
            glossary=tuple(Term(term=entry.term, meaning=entry.meaning) for entry in page.glossary),
            signals_snapshot=signals,
        )
        stored = await deps.summaries.add(summary)
        closed = await deps.claims.settle({entry.claim_id: entry.resolution for entry in settles}, stored)
        extracted = await knowledge.read_back(deps, against.rendered(prose), session)
        kept = await knowledge.remember(deps, summary.model_copy(update={"id": stored}), extracted, session)

        asked = tuple(dict.fromkeys(panel.name for panel in page.layout))
        ready = summary.drawable
        return SaveOutcome(
            outcome="saved",
            summary_id=stored,
            session_date=signals.session_date,
            sections=len(draft.sections),
            claims=kept,
            drawn=tuple(name for name in asked if name in ready),
            dropped=tuple(name for name in asked if name not in ready),
            settled=closed,
        )

    _ = (check_summary, save_summary)
