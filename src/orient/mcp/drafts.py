"""What a draft is checked against, gathered once and shared by both write tools.

Evidence is re-derived rather than remembered across calls. Signals, backdrop and calendar for a
session are deterministic and, after the first fetch, come from the cache, so a check runs against
exactly what the tools would have served without the server holding per-run state.
"""

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Final, NamedTuple

from orient.domain import faults, figures, grounding
from orient.domain.faults import Fault
from orient.domain.figures import Figure
from orient.domain.market import InstrumentProfile, MarketContext
from orient.domain.models import AssetClass, Holding, Signals
from orient.mcp.deps import ToolDeps
from orient.mcp.measure import gathered, session_signals

CALENDAR_DAYS: Final = 7


class Filed(NamedTuple):
    """An instrument that can be written down, which needs an asset class and a name."""

    asset_class: AssetClass
    name: str | None
    sector: str | None
    exchange: str | None
    currency: str | None
    holdings: tuple[Holding, ...]


class Grounds(NamedTuple):
    """The measured world one draft is judged against."""

    signals: Signals
    profile: InstrumentProfile | None
    figures: Mapping[str, Figure]
    evidence: frozenset[float]

    def rendered(self, prose: str) -> str:
        """The prose as a reader meets it, which is what a reviewer has to judge."""
        return figures.render(prose, self.figures)

    def filed(self) -> "Filed | None":
        """The profile, once it carries the one field a summary cannot be stored without."""
        profile: Final = self.profile
        if profile is None or profile.asset_class is None:
            return None
        return Filed(
            asset_class=profile.asset_class,
            name=profile.name,
            sector=profile.sector,
            exchange=profile.exchange,
            currency=profile.currency,
            holdings=profile.holdings,
        )


async def grounds(deps: ToolDeps, symbol: str, session_date: date) -> Grounds | None:
    """None when the instrument has no history, which is the one thing no draft can survive.

    The profile is fetched first because the exchange on it decides whose sectors the backdrop is
    built from, and it counts as evidence in its own right: the instrument's name is a numeral to
    a check that cannot tell a name from a figure, so "S&P 500" has to be allowed through.
    """
    profile: Final = await gathered(deps.reference.profile(symbol))
    exchange: Final = getattr(profile, "exchange", None)
    backdrop: Final = await gathered(deps.market.backdrop(session_date, exchange))
    context: Final = backdrop if isinstance(backdrop, MarketContext) else None
    signals: Final = await session_signals(deps, symbol, session_date, context)
    if signals is None:
        return None
    calendar: Final = await gathered(deps.calendars.entries(session_date, session_date + timedelta(days=CALENDAR_DAYS)))
    measured: Final = tuple(
        item.model_dump(mode="json") for item in (signals, profile, backdrop, calendar) if item is not None
    )
    return Grounds(
        signals=signals,
        profile=profile if isinstance(profile, InstrumentProfile) else None,
        figures=figures.addressable(signals),
        evidence=grounding.measured(measured),
    )


def wrong_with(
    prose: str,
    against: Grounds,
    session_date: date,
    glossary: Sequence[str] = (),
) -> tuple[Fault, ...]:
    return faults.found(prose, against.figures, against.evidence, against.signals, session_date, glossary)
