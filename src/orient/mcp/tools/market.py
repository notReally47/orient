"""Prices, the signals derived from them, and the backdrop they moved against."""

from datetime import date, timedelta
from typing import Annotated, Final

from mcp.server import MCPServer
from pydantic import Field

from orient.domain.market import MarketContext
from orient.domain.models import Signals
from orient.domain.signals import compute_signals
from orient.mcp.deps import ToolDeps
from orient.mcp.results import PriceHistory

# A year of sessions needs more than a year of dates: 252 trading days fall inside roughly 370,
# and the year-to-date figure is measured from the final close of the previous year.
SIGNALS_LOOKBACK: Final = timedelta(days=400)
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
        """Returns, trend, volatility, volume and drawdown for one instrument, in one call.

        Every window that the history is too short to support comes back null rather than
        approximated, so a figure that is present is a figure that was actually computed.
        `session_date` on the answer is the last session that actually traded on or before the
        one asked for, which is not the same date when the market was shut.
        """
        bars = await deps.prices.bars(symbol, session_date - SIGNALS_LOOKBACK, session_date)
        signals = compute_signals(symbol, bars)
        if signals is None:
            message = f"no price history for {symbol} on or before {session_date}"
            raise ValueError(message)
        return signals

    @server.tool()
    async def get_market_context(session_date: SESSION_DATE) -> MarketContext:
        """The backdrop a move happened against: session state, cross-asset levels and sectors.

        Breadth and contribution here are counted across a basket of sector funds, not across index
        constituents, because no constituent list is available. Describe them as sector breadth.
        `session` is null for a past date, because live status says nothing about a closed session.
        """
        return await deps.market.backdrop(session_date)

    _ = (get_price_history, compute_instrument_signals, get_market_context)
