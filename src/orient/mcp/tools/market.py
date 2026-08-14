"""Prices, the signals derived from them, and the backdrop they moved against."""

from datetime import timedelta
from functools import partial
from typing import Annotated

from anyio import to_thread
from mcp.server import MCPServer
from pydantic import Field

from orient.domain.context import (
    CROSS_ASSET_SERIES,
    CROSS_ASSET_TICKERS,
    SECTOR_ETFS,
    build_cross_asset,
    build_sector_breadth,
    build_sector_moves,
)
from orient.domain.market import MarketContext
from orient.domain.models import Signals
from orient.domain.signals import compute_signals
from orient.mcp.deps import ToolDeps
from orient.mcp.results import PriceHistory

DEFAULT_PERIOD = "1y"
CONTEXT_PERIOD = "1mo"
SERIES_LOOKBACK_DAYS = 30
MAX_BARS = 400


def register(server: MCPServer, deps: ToolDeps) -> None:
    @server.tool()
    async def get_price_history(
        symbol: Annotated[str, Field(description="A Yahoo ticker such as '^GSPC', 'AAPL' or 'EURUSD=X'")],
        period: Annotated[
            str,
            Field(description="How far back to fetch: 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, ytd or max"),
        ] = DEFAULT_PERIOD,
    ) -> PriceHistory:
        """Daily open, high, low, close and volume for one instrument.

        Prefer compute_signals when the question is how an instrument behaved; this returns the
        raw series and is for charting or for a calculation the signals do not already cover.
        """
        bars = await to_thread.run_sync(partial(deps.prices.daily_bars, symbol, period))
        return PriceHistory(symbol=symbol, period=period, bars=bars[-MAX_BARS:])

    @server.tool()
    async def compute_instrument_signals(
        symbol: Annotated[str, Field(description="A Yahoo ticker such as '^GSPC' or 'AAPL'")],
        period: Annotated[
            str,
            Field(description="History to compute from. A year is needed for the 200 day average"),
        ] = DEFAULT_PERIOD,
    ) -> Signals:
        """Returns, trend, volatility, volume and drawdown for one instrument, in one call.

        Every window that the history is too short to support comes back null rather than
        approximated, so a figure that is present is a figure that was actually computed.
        """
        bars = await to_thread.run_sync(partial(deps.prices.daily_bars, symbol, period))
        signals = compute_signals(symbol, bars)
        if signals is None:
            message = f"no price history returned for {symbol}"
            raise ValueError(message)
        return signals

    @server.tool()
    async def get_market_context() -> MarketContext:
        """The backdrop a move happened against: session state, cross-asset levels and sectors.

        Breadth and contribution here are counted across the eleven sector ETFs, not across index
        constituents, because no constituent list is available. Describe them as sector breadth.
        """
        tickers = (*CROSS_ASSET_TICKERS, *SECTOR_ETFS)
        bars = await to_thread.run_sync(partial(deps.prices.multi_bars, tickers, CONTEXT_PERIOD))

        end = deps.clock()
        start = end - timedelta(days=SERIES_LOOKBACK_DAYS)
        series = {
            name: await to_thread.run_sync(partial(deps.series.observations, name, start, end))
            for name in CROSS_ASSET_SERIES
        }

        session = await to_thread.run_sync(deps.context.session)
        moves = build_sector_moves(bars)
        return MarketContext(
            session=session,
            cross_asset=build_cross_asset(bars, series),
            sectors=moves,
            sector_breadth=build_sector_breadth(moves),
        )

    _ = (get_price_history, compute_instrument_signals, get_market_context)
