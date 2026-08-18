"""What an instrument is, what analysts expect of it, and what is scheduled."""

from datetime import timedelta
from functools import partial
from typing import Annotated

from anyio import to_thread
from mcp.server import MCPServer
from pydantic import Field

from orient.domain.market import EarningsDetail, InstrumentProfile
from orient.domain.models import Calendar, CalendarKind
from orient.mcp.deps import ToolDeps

DEFAULT_CALENDAR_DAYS = 7
MAX_CALENDAR_DAYS = 60


def register(server: MCPServer, deps: ToolDeps) -> None:
    @server.tool()
    async def get_instrument_profile(
        symbol: Annotated[str, Field(description="A ticker such as 'AAPL' or 'SPY'")],
    ) -> InstrumentProfile:
        """What an instrument is: its classification, sector, size and valuation.

        Dispatches on asset class inside the call, so an ETF comes back with its holdings and
        sector weights while an equity comes back with its fundamentals. Fields a vendor does not
        publish for a given class are null rather than missing.
        """
        return await to_thread.run_sync(partial(deps.reference.profile, symbol))

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
        detail = await to_thread.run_sync(partial(deps.earnings.detail, symbol))
        if spot is None or spot <= 0:
            return detail

        move = await to_thread.run_sync(partial(deps.reference.implied_move, symbol, spot, deps.clock()))
        return detail.model_copy(update={"implied_move": move})

    @server.tool()
    async def get_calendar(
        days: Annotated[
            int,
            Field(description="How far ahead to look", ge=1, le=MAX_CALENDAR_DAYS),
        ] = DEFAULT_CALENDAR_DAYS,
        kinds: Annotated[
            tuple[CalendarKind, ...] | None,
            Field(description="Limit to some of earnings, economic, ipo, split. All four when unset"),
        ] = None,
    ) -> Calendar:
        """What is scheduled in the days ahead, across earnings, economic releases, IPOs and splits.

        One list sorted soonest first and tagged by kind, so there is no need to choose a calendar
        before knowing what is on it. `unreadable` counts rows the vendor sent in a shape this layer
        could not read: above zero, the list is short and should be described as incomplete rather
        than as a quiet week.
        """
        start = deps.clock()
        end = start + timedelta(days=days)
        fetch = (
            partial(deps.calendars.entries, start, end)
            if kinds is None
            else partial(deps.calendars.entries, start, end, kinds)
        )
        return await to_thread.run_sync(fetch)

    _ = (get_instrument_profile, get_earnings_detail, get_calendar)
