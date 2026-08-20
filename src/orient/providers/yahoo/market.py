"""The market backdrop, assembled from the symbols this vendor uses to name it.

Which instruments a summary should mention is an editorial choice; spelling them `^VIX`, `CL=F`
and `XLK` is this vendor's. The baskets therefore live here, and nothing above learns that the
yields come from a second source because Yahoo publishes no two year index.

One call returns session state, the cross-asset block and sector performance together, because an
analyst always wants all three and at fifteen requests per minute round trips are the scarce
resource. The batched download that makes that one request rather than three stays inside.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from functools import partial
from types import MappingProxyType
from typing import Final

from anyio import to_thread
from pydantic import TypeAdapter

from orient.domain.market import MarketContext, MarketSession, SectorMove
from orient.domain.models import Bar, Breadth, CrossAsset, Observation
from orient.providers._untyped import market_status_fields, yahoo_market_status
from orient.providers.protocols import Prices, Series

VIX: Final = "^VIX"
DEFAULT_REGION: Final = "US"
BACKDROP_LOOKBACK: Final = timedelta(days=30)
SERIES_LOOKBACK: Final = timedelta(days=30)
CLOSES_FOR_A_CHANGE: Final = 2

CROSS_ASSET_TICKERS: Final[Mapping[str, str]] = MappingProxyType(
    {
        VIX: "vix",
        "DX-Y.NYB": "dollar_index",
        "CL=F": "crude_oil",
        "GC=F": "gold",
    }
)

CROSS_ASSET_SERIES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "DGS10": "yield_10y",
        "DGS2": "yield_2y",
        "BAMLH0A0HYM2": "high_yield_spread",
    }
)

SECTOR_ETFS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "XLB": "Materials",
        "XLC": "Communication Services",
        "XLE": "Energy",
        "XLF": "Financials",
        "XLI": "Industrials",
        "XLK": "Technology",
        "XLP": "Consumer Staples",
        "XLRE": "Real Estate",
        "XLU": "Utilities",
        "XLV": "Health Care",
        "XLY": "Consumer Discretionary",
    }
)

_SESSION: Final = TypeAdapter(MarketSession)


def _today() -> date:
    return datetime.now(tz=UTC).date()


def _last_close(bars: Sequence[Bar]) -> float | None:
    return bars[-1].close if bars else None


def _session_change(bars: Sequence[Bar]) -> float | None:
    if len(bars) < CLOSES_FOR_A_CHANGE or bars[-2].close == 0:
        return None
    return bars[-1].close / bars[-2].close - 1


def _latest(observations: Sequence[Observation]) -> float | None:
    return observations[-1].value if observations else None


class YahooMarket:
    def __init__(
        self,
        prices: Prices,
        series: Series,
        status: Callable[[str], Mapping[str, object] | None] = yahoo_market_status,
        clock: Callable[[], date] = _today,
        region: str = DEFAULT_REGION,
    ) -> None:
        self._prices: Final = prices
        self._series: Final = series
        self._status: Final = status
        self._clock: Final = clock
        self._region: Final = region

    async def backdrop(self, as_of: date) -> MarketContext:
        bars: Final = await self._prices.multi_bars(
            (*CROSS_ASSET_TICKERS, *SECTOR_ETFS),
            as_of - BACKDROP_LOOKBACK,
            as_of,
        )
        moves: Final = self._sectors(bars)
        return MarketContext(
            session=await self._session(as_of),
            cross_asset=await self._cross_asset(bars, as_of),
            sectors=moves,
            sector_breadth=Breadth.over({move.symbol: move.change_percent for move in moves}),
        )

    async def _session(self, as_of: date) -> MarketSession | None:
        """Live status describes now, so it says nothing true about a session already closed."""
        if as_of < self._clock():
            return None
        status: Final = await to_thread.run_sync(partial(self._status, self._region))
        return _SESSION.validate_python(market_status_fields(status))

    async def _cross_asset(self, bars: Mapping[str, Sequence[Bar]], as_of: date) -> CrossAsset:
        levels: Final = {field: _last_close(bars.get(ticker, ())) for ticker, field in CROSS_ASSET_TICKERS.items()}
        rates: Final = {
            field: _latest(await self._series.observations(name, as_of - SERIES_LOOKBACK, as_of))
            for name, field in CROSS_ASSET_SERIES.items()
        }
        return CrossAsset(**levels, **rates, vix_change=_session_change(bars.get(VIX, ())))

    def _sectors(self, bars: Mapping[str, Sequence[Bar]]) -> tuple[SectorMove, ...]:
        """Strongest first, so nothing downstream has to sort to find what led."""
        moves: Final = tuple(
            SectorMove(symbol=symbol, name=name, change_percent=_session_change(bars.get(symbol, ())))
            for symbol, name in SECTOR_ETFS.items()
        )
        return tuple(sorted(moves, key=lambda move: (move.change_percent is None, -(move.change_percent or 0.0))))
