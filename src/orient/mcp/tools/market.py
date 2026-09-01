"""Prices, the signals derived from them, and the backdrop they moved against."""

from datetime import date, timedelta
from typing import Annotated, Final

from mcp.server import MCPServer
from pydantic import Field

from orient.domain.market import MarketContext
from orient.domain.models import CONDITIONAL, Signals, commodities_bear_on
from orient.mcp.deps import ToolDeps
from orient.mcp.measure import gathered as _gathered
from orient.mcp.measure import session_signals
from orient.mcp.results import PriceHistory

MAX_BARS: Final = 400

SESSION_DATE = Annotated[
    date,
    Field(description="The session being summarised. Figures are measured as of its close, never later"),
]


def register(server: MCPServer, deps: ToolDeps) -> None:
    @server.tool()
    async def get_price_history(
        symbol: Annotated[str, Field(description="A ticker such as '^GSPC', 'AAPL' or 'EURUSD=X'")],
        session_date: SESSION_DATE,
        days: Annotated[int, Field(description="Calendar days of history ending at the session", ge=1, le=800)] = 30,
    ) -> PriceHistory:
        """Daily open, high, low, close and volume for one instrument.

        Prefer compute_instrument_signals when the question is how an instrument behaved; this
        returns the raw series and is for a calculation the signals do not already cover. Ask for
        the shortest window that answers the question: a year is hundreds of rows.
        """
        bars = await deps.prices.bars(symbol, session_date - timedelta(days=days), session_date)
        return PriceHistory(
            symbol=symbol,
            start=session_date - timedelta(days=days),
            end=session_date,
            bars=bars[-MAX_BARS:],
        )

    @server.tool()
    async def compute_instrument_signals(
        symbol: Annotated[str, Field(description="A ticker such as '^GSPC' or 'AAPL'")],
        session_date: SESSION_DATE,
    ) -> Signals:
        """Everything one instrument's own price history says about its session, in one call.

        Depends on nothing: issue it in the same turn as `get_instrument_profile`, not after it.

        Returns over five windows, distance from the 50 and 200 day averages and the direction the
        200 day average is itself moving, realised volatility, volume against its own average and
        which side that volume was on, where the close sat in the day's range, how the move split
        between the gap and the session, and the same day's move in this instrument's benchmark
        and sector.

        Read `relative` first: it decides whether there is anything to explain. An instrument that
        moved with its sector has not done anything a news search can account for.

        Anything the history was too short to support is left out rather than approximated, so a
        figure that is present was computed and one that is absent was not measurable. Instruments
        that price once a day have no gap or intraday move at all. `session_date` on the answer is
        the last session that actually traded on or before the one asked for.
        """
        measured = await session_signals(deps, symbol, session_date)
        if measured is None:
            message = f"no price history for {symbol} on or before {session_date}"
            raise ValueError(message)
        return measured

    @server.tool()
    async def get_market_context(
        session_date: SESSION_DATE,
        symbol: Annotated[
            str | None,
            Field(
                description=(
                    "The instrument being summarised, which decides whose sectors come back. "
                    "A Nifty summary gets the NSE's sectors and an S&P 500 summary the American "
                    "ones. Omitted, the sectors are American, matching the rest of the backdrop."
                )
            ),
        ] = None,
    ) -> MarketContext:
        """The backdrop a move happened against: cross-asset levels, macro and sector performance.

        Pass the symbol. The sectors are that instrument's own market's, named the way the market
        names them: the NSE publishes FMCG and PSU Bank, neither a GICS category. Breadth and
        contribution are counted across those sector series and never across index constituents,
        because no constituent list exists, so describe them as sector breadth.

        A sector carrying no move was not measured, which is not the same as one that finished
        flat: neither prose nor panel may treat it as one. `sector_breadth` counts only what was
        measured, so a total of zero means the board says nothing about this session. Contribution
        needs published sector weights, which only some markets have.

        `macro` holds what the agencies last published, each with the month it describes.
        """
        profile = None if symbol is None else await _gathered(deps.reference.profile(symbol))
        context = await deps.market.backdrop(session_date, getattr(profile, "exchange", None))
        return _bearing_on(context, getattr(profile, "asset_class", None), getattr(profile, "sector", None))

    _ = (get_price_history, compute_instrument_signals, get_market_context)


def _bearing_on(context: MarketContext, asset_class: str | None, sector: str | None) -> MarketContext:
    """The backdrop with the readings that have nothing to do with this instrument taken out.

    The page already declined to draw the dollar and commodity block beside a memory chipmaker.
    The writer went on quoting crude oil at one anyway, because the figure was still in the tool
    result and a measurement in front of a model is an invitation to use it. Withholding it is the
    only version of this rule that works: a summary cannot reach for a connection it was never
    shown, and the grounding check would now refuse the sentence if it tried.

    An instrument the commodities genuinely bear on — an energy producer, a currency pair, a
    commodity future — keeps every reading it had.
    """
    if commodities_bear_on(asset_class, sector):
        return context
    return context.model_copy(update={"cross_asset": context.cross_asset.model_copy(update=dict.fromkeys(CONDITIONAL))})
