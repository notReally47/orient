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
from zoneinfo import ZoneInfo

from anyio import to_thread
from pydantic import TypeAdapter

from orient.domain.market import Macro, MacroReading, MarketContext, MarketSession, SectorMove
from orient.domain.models import Bar, Breadth, CalendarDate, CrossAsset, Frozen, Observation, Relative
from orient.domain.signals import compare
from orient.providers._untyped import (
    market_status_fields,
    yahoo_fund_sector_weights,
    yahoo_market_status,
    yahoo_session_quote,
)
from orient.providers.protocols import Prices, Series
from orient.providers.yahoo import boards

VIX: Final = "^VIX"
DEFAULT_REGION: Final = "US"
BACKDROP_LOOKBACK: Final = timedelta(days=30)
SERIES_LOOKBACK: Final = timedelta(days=30)
CLOSES_FOR_A_CHANGE: Final = 2
MONTHS_IN_A_YEAR: Final = 12

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

BREAKEVEN: Final = "T10YIE"

MACRO_SERIES: Final[Mapping[str, tuple[str, str, bool]]] = MappingProxyType(
    {
        "CPIAUCSL": ("Consumer prices, year over year", "%", True),
        "CPILFESL": ("Core consumer prices, year over year", "%", True),
        "UNRATE": ("Unemployment rate", "%", False),
        "DFF": ("Fed funds effective rate", "%", False),
        "NFCI": ("Chicago Fed financial conditions", "index", False),
    }
)

MACRO_LOOKBACK: Final = timedelta(days=560)
NFCI: Final = "NFCI"

BENCHMARKS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "equity": "SPY",
        "etf": "SPY",
        "fund": "SPY",
        "index": "^GSPC",
        "crypto": "BTC-USD",
        "currency": "DX-Y.NYB",
    }
)

_SESSION: Final = TypeAdapter(MarketSession)


class _Quote(Frozen):
    """The one session a quote-only series can speak for, and what it did in it."""

    symbol: str
    session_date: CalendarDate | None = None
    close: float | None = None
    previous_close: float | None = None
    timezone: str | None = None

    def settled(self) -> bool:
        """Whether the session this describes has actually finished.

        A quote taken while the market is open carries a partial bar, and the date on it is
        today's. Comparing dates alone would accept it as that day's close, which is a figure
        nobody has measured yet.
        """
        if self.session_date is None:
            return False
        here: Final = datetime.now(tz=ZoneInfo(self.timezone) if self.timezone else UTC).date()
        return self.session_date < here


_QUOTE: Final = TypeAdapter(_Quote)


def _session_quotes(symbols: Sequence[str]) -> Sequence[Mapping[str, object]]:
    """One quote per symbol, serially, because there is no batched surface for them.

    Fourteen requests where the American board costs one. Only markets whose sector series carry
    no history pay it, and the alternative is no board for those markets at all.
    """
    return tuple(quote for symbol in symbols if (quote := yahoo_session_quote(symbol)))


def _today() -> date:
    return datetime.now(tz=UTC).date()


def _last_close(bars: Sequence[Bar]) -> float | None:
    return bars[-1].close if bars else None


def _session_change(bars: Sequence[Bar], on: date | None = None) -> float | None:
    """The move on one session, or nothing when these bars do not reach it.

    A vendor publishes sector funds and index levels on its own schedule, so a series can be a day
    behind the instrument being summarised. Taking the last two closes regardless would label
    yesterday's move as today's, which is the one error a reader cannot catch.
    """
    if len(bars) < CLOSES_FOR_A_CHANGE or bars[-2].close == 0:
        return None
    if on is not None and bars[-1].session_date != on:
        return None
    return bars[-1].close / bars[-2].close - 1


def _latest(observations: Sequence[Observation]) -> float | None:
    return observations[-1].value if observations else None


def _level(series: str, label: str, observed: Sequence[Observation]) -> MacroReading | None:
    """The last published value and the one before it, so a direction is visible without a chart."""
    if not observed:
        return None
    return MacroReading(
        series=series,
        label=label,
        value=round(observed[-1].value, 3),
        previous=round(observed[-2].value, 3) if len(observed) > 1 else None,
        observed_on=observed[-1].observation_date,
    )


def _year_over_year(series: str, label: str, observed: Sequence[Observation]) -> MacroReading | None:
    """A price index turned into the inflation rate everybody actually quotes.

    Twelve monthly observations back, not twelve rows back: a series that skipped a month would
    otherwise silently become a thirteen-month change wearing a twelve-month label.
    """
    if len(observed) <= MONTHS_IN_A_YEAR:
        return None
    latest: Final = observed[-1]
    year_ago: Final = observed[-1 - MONTHS_IN_A_YEAR]
    prior: Final = observed[-2] if len(observed) > MONTHS_IN_A_YEAR + 1 else None
    if year_ago.value == 0:
        return None
    return MacroReading(
        series=series,
        label=label,
        value=round((latest.value / year_ago.value - 1) * 100, 2),
        previous=(
            round((prior.value / observed[-2 - MONTHS_IN_A_YEAR].value - 1) * 100, 2)
            if prior is not None and observed[-2 - MONTHS_IN_A_YEAR].value
            else None
        ),
        observed_on=latest.observation_date,
    )


class YahooMarket:
    def __init__(
        self,
        prices: Prices,
        series: Series,
        status: Callable[[str], Mapping[str, object] | None] = yahoo_market_status,
        clock: Callable[[], date] = _today,
        region: str = DEFAULT_REGION,
        weights: Callable[[str], Mapping[str, object]] = yahoo_fund_sector_weights,
        quotes: Callable[[Sequence[str]], Sequence[Mapping[str, object]]] = _session_quotes,
    ) -> None:
        self._prices: Final = prices
        self._series: Final = series
        self._status: Final = status
        self._clock: Final = clock
        self._region: Final = region
        self._weights: Final = weights
        self._quotes: Final = quotes
        self._weights_cache: Final[dict[str, Mapping[str, float]]] = {}

    async def backdrop(self, as_of: date, exchange: str | None = None) -> MarketContext:
        board: Final = boards.of(exchange)
        wanted: Final = (*CROSS_ASSET_TICKERS, *(board.sectors if board.from_history else ()))
        bars: Final = await self._prices.multi_bars(wanted, as_of - BACKDROP_LOOKBACK, as_of)
        moves: Final = await self._weighted(board, await self._sectors(board, bars, as_of))
        cross_asset: Final = await self._cross_asset(bars, as_of)
        return MarketContext(
            session=await self._session(as_of),
            cross_asset=cross_asset,
            macro=await self._macro(cross_asset, as_of),
            sectors=moves,
            sector_breadth=Breadth.over({move.symbol: move.change_percent for move in moves}),
            sector_market=board.market,
        )

    async def _macro(self, cross_asset: CrossAsset, as_of: date) -> Macro | None:
        """What the agencies last published, and the real yield the two rate series imply."""
        readings: Final[list[MacroReading]] = []
        for series, (label, unit, as_year_over_year) in MACRO_SERIES.items():
            observed = await self._series.observations(series, as_of - MACRO_LOOKBACK, as_of)
            reading = _year_over_year(series, label, observed) if as_year_over_year else _level(series, label, observed)
            if reading is not None:
                readings.append(reading.model_copy(update={"unit": unit}))
        breakeven: Final = _latest(await self._series.observations(BREAKEVEN, as_of - SERIES_LOOKBACK, as_of))
        real: Final = (
            None if breakeven is None or cross_asset.yield_10y is None else round(cross_asset.yield_10y - breakeven, 2)
        )
        if not readings and real is None:
            return None
        return Macro(readings=tuple(readings), real_yield_10y=real)

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
        return CrossAsset(**levels, **rates, vix_change=_session_change(bars.get(VIX, ()), as_of))

    async def relative(
        self,
        symbol: str,
        session_return: float | None,
        as_of: date,
        asset_class: str | None = None,
        sector: str | None = None,
        exchange: str | None = None,
    ) -> Relative | None:
        """The same session's move in the instrument's benchmark and its sector, for subtraction.

        Both series are fetched in the one batched request the cache already serves, so on any run
        that also builds the backdrop this costs nothing: the sector funds are already stored.
        An instrument compared against itself is dropped, because "the S&P 500 matched the S&P
        500 by 0.00%" is not a finding.
        """
        board: Final = boards.of(exchange)
        benchmark: Final = BENCHMARKS.get(asset_class or "")
        peer: Final = board.proxies.get(sector or "")
        wanted: Final = tuple({ticker for ticker in (benchmark, peer) if ticker and ticker != symbol})
        if session_return is None or not wanted:
            return None
        bars: Final = await self._prices.multi_bars(wanted, as_of - BACKDROP_LOOKBACK, as_of)
        moved: Final = {ticker: _session_change(bars.get(ticker, ()), as_of) for ticker in wanted}
        if peer in wanted and moved.get(peer) is None and not board.from_history:
            moved[peer] = (await self._quoted((peer,), as_of)).get(peer)
        return compare(
            session_return,
            benchmark=(benchmark, moved.get(benchmark)) if benchmark in wanted else None,
            peer=(peer, board.sectors.get(peer or ""), moved.get(peer)) if peer in wanted else None,
        )

    async def _weighted(self, board: boards.Board, moves: Sequence[SectorMove]) -> tuple[SectorMove, ...]:
        """Each sector's move multiplied by what it weighs, so the panel can rank by what mattered.

        A missing weight costs that sector its contribution and nothing else: the move is still
        measured and the bar is still drawn, it simply cannot say how much of the index it carried.
        A market whose weights this vendor does not publish costs every contribution and no move,
        and the panel drops that reading rather than ranking by a figure most of it lacks.
        """
        weights: Final = await self._market_weights(board)
        if not weights:
            return tuple(moves)
        return tuple(
            move
            if (share := weights.get(move.symbol)) is None or move.change_percent is None
            else move.model_copy(update={"weight": share, "contribution": share * move.change_percent})
            for move in moves
        )

    async def _market_weights(self, board: boards.Board) -> Mapping[str, float]:
        """The tracker's published sector weights, asked for once per market and kept.

        Sector weights move with the market and are republished slowly, so refetching them for
        every backdrop would spend a request on a number that has not changed.
        """
        if board.weights_from is None:
            return {}
        if board.weights_from not in self._weights_cache:
            raw = await to_thread.run_sync(partial(self._weights, board.weights_from))
            self._weights_cache[board.weights_from] = {
                ticker: float(value)
                for key, value in raw.items()
                if (ticker := board.weight_keys.get(key)) is not None and isinstance(value, int | float)
            }
        return self._weights_cache[board.weights_from]

    async def _sectors(
        self, board: boards.Board, bars: Mapping[str, Sequence[Bar]], as_of: date
    ) -> tuple[SectorMove, ...]:
        """Strongest first, so nothing downstream has to sort to find what led.

        A sector the session could not be measured for is still named, carrying no change. Leaving
        it out would read as a sector that did not move, which is a different claim from one
        nobody measured.
        """
        changes: Final = (
            {symbol: _session_change(bars.get(symbol, ()), as_of) for symbol in board.sectors}
            if board.from_history
            else await self._quoted(tuple(board.sectors), as_of)
        )
        moves: Final = tuple(
            SectorMove(symbol=symbol, name=name, change_percent=changes.get(symbol))
            for symbol, name in board.sectors.items()
        )
        return tuple(sorted(moves, key=lambda move: (move.change_percent is None, -(move.change_percent or 0.0))))

    async def _quoted(self, symbols: Sequence[str], as_of: date) -> Mapping[str, float | None]:
        """One session's move for sectors this vendor publishes no history for.

        Every Indian sector index is like this: a live quote, a complete bar for the most recent
        session, and nothing behind it whatever window is asked for. That answers the question a
        board asks, and only for the day it describes — so the date comes back with it, and a
        request for any other session gets nothing rather than the wrong day's move relabelled.
        """
        quotes: Final = await to_thread.run_sync(partial(self._quotes, tuple(symbols)))
        moved: Final[dict[str, float | None]] = {}
        for quote in quotes:
            fields = _QUOTE.validate_python(quote)
            usable = fields.session_date == as_of and fields.settled()
            moved[fields.symbol] = (
                None
                if not usable or fields.previous_close in (None, 0.0) or fields.close is None
                else fields.close / fields.previous_close - 1
            )
        return moved
