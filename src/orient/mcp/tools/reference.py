"""What an instrument is, what analysts expect of it, and what is scheduled."""

from datetime import date, timedelta
from typing import Annotated, Final

from mcp.server import MCPServer
from pydantic import Field

from orient.domain import signals
from orient.domain.market import EarningsDetail, EarningsReaction, InstrumentProfile
from orient.domain.models import Bar, Calendar
from orient.mcp.deps import ToolDeps

REACTION_MARGIN = timedelta(days=10)

DEFAULT_CALENDAR_DAYS = 7
MAX_CALENDAR_DAYS = 60


async def _reactions(deps: ToolDeps, symbol: str, detail: EarningsDetail) -> tuple[EarningsReaction, ...]:
    """How the shares took the last few reports, from the dates and the bars already in hand.

    No new vendor surface: the report dates arrived with the rest of the earnings detail and the
    closes are the same series every other measurement is built from. What it adds is the only
    earnings fact that is about the trade rather than about the business — a name sold on three
    of its last four prints is carrying something into the next one.
    """
    reported: Final[tuple[date, ...]] = tuple(
        event.event_date for event in detail.events if event.reported_eps is not None
    )
    if not reported:
        return ()
    bars: Final[tuple[Bar, ...]] = await deps.prices.bars(
        symbol, min(reported) - REACTION_MARGIN, max(reported) + REACTION_MARGIN
    )
    return signals.reactions(reported, bars)


def register(server: MCPServer, deps: ToolDeps) -> None:
    @server.tool()
    async def get_instrument_profile(
        symbol: Annotated[str, Field(description="A ticker such as 'AAPL' or 'SPY'")],
    ) -> InstrumentProfile:
        """What an instrument is: asset class, sector, size, valuation, and what a fund holds.

        Call this first. It depends on nothing, and the asset class it returns decides which of
        the remaining tools this instrument's session needs and which guidance applies to it.

        What comes back follows the class: a fund carries holdings and sector weights, an equity
        carries sector, industry, beta and the two price-to-earnings ratios. There is no income
        statement, balance sheet or short interest in any of them.
        """
        return await deps.reference.profile(symbol)

    @server.tool()
    async def get_earnings_detail(
        symbol: Annotated[str, Field(description="An equity ticker. Indices and funds have no earnings")],
        spot: Annotated[
            float | None,
            Field(description="Current price. Supplying it adds the implied move to the nearest expiry"),
        ] = None,
    ) -> EarningsDetail:
        """Earnings history, forward estimates, EPS revisions, price targets and rating changes.

        Only worth calling when an earnings event falls inside the window being summarised. A move
        driven by a headline rather than results does not need estimate revisions. Passing the
        current price adds one implied-move figure from the nearest expiry, which is all this
        should ever say about options.
        """
        detail = await deps.earnings.detail(symbol)
        detail = detail.model_copy(update={"reactions": await _reactions(deps, symbol, detail)})
        if spot is None or spot <= 0:
            return detail

        move = await deps.reference.implied_move(symbol, spot, deps.clock())
        return detail.model_copy(update={"implied_move": move})

    @server.tool()
    async def get_calendar(
        session_date: Annotated[
            date,
            Field(description="The session being summarised. The window runs forward from it"),
        ],
        days: Annotated[
            int,
            Field(description="How far ahead to look", ge=1, le=MAX_CALENDAR_DAYS),
        ] = DEFAULT_CALENDAR_DAYS,
    ) -> Calendar:
        """Company results scheduled in the days ahead, soonest first.

        Earnings and nothing else: the vendor's economic, IPO and split surfaces answered too
        badly to serve. A thin answer therefore means a quiet week *for earnings*, and "nothing is
        scheduled this week" overstates what was checked. Inflation, employment and policy are
        published rather than scheduled and live in `get_market_context` under `macro`.

        `unreadable` above zero means rows arrived in a shape this layer could not read, so the
        list is short: describe it as incomplete rather than as a quiet week.
        """
        end = session_date + timedelta(days=days)
        return await deps.calendars.entries(session_date, end)

    _ = (get_instrument_profile, get_earnings_detail, get_calendar)
