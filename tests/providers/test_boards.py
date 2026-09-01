"""Whose sectors a summary gets, and what happens where a market publishes less than the US does.

The failure these guard against is silent. An eleven-bar board of American sector funds and a
fourteen-bar board of NSE indices render identically, so a Nifty summary carrying the American set
looks exactly like a Nifty summary carrying the right one.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

import pytest

from orient.domain.models import Bar, Observation
from orient.providers.yahoo import boards
from orient.providers.yahoo.market import YahooMarket

pytestmark = pytest.mark.anyio

SESSION: Final = date(2026, 8, 26)
NSE_QUOTED: Final = "^CNXAUTO"


class _Prices:
    def __init__(self, series: Mapping[str, tuple[Bar, ...]] | None = None) -> None:
        self._series: Final = series or {}
        self.asked: Final[list[tuple[str, ...]]] = []

    async def bars(self, symbol: str, start: date, end: date) -> tuple[Bar, ...]:
        del start, end
        return self._series.get(symbol, ())

    async def multi_bars(self, symbols: Sequence[str], start: date, end: date) -> Mapping[str, tuple[Bar, ...]]:
        del start, end
        self.asked.append(tuple(symbols))
        return {symbol: self._series[symbol] for symbol in symbols if symbol in self._series}


class _NoSeries:
    async def observations(self, series_id: str, start: date, end: date) -> tuple[Observation, ...]:
        del series_id, start, end
        return ()


Quotes = Callable[[Sequence[str]], Sequence[Mapping[str, object]]]


def _quotes(session: date = SESSION, previous: float = 100.0, close: float = 102.0) -> Quotes:
    def answer(symbols: Sequence[str]) -> Sequence[Mapping[str, object]]:
        return tuple(
            {
                "symbol": symbol,
                "session_date": session,
                "close": close,
                "previous_close": previous,
                "timezone": "Asia/Kolkata",
            }
            for symbol in symbols
        )

    return answer


def _market(prices: _Prices | None = None, quotes: Quotes | None = None) -> YahooMarket:
    return YahooMarket(
        prices or _Prices(),
        _NoSeries(),
        lambda _: None,
        lambda: SESSION,
        "US",
        lambda _: {},
        quotes or _quotes(),
    )


def test_an_indian_instrument_gets_the_nses_sectors_and_not_the_american_ones() -> None:
    indian: Final = boards.of("NSI")

    assert indian is not boards.BOARDS[boards.US]
    assert "FMCG" in indian.sectors.values()
    assert "PSU Bank" in indian.sectors.values()
    assert not any(ticker.startswith("XL") for ticker in indian.sectors)


def test_an_exchange_nobody_mapped_falls_back_rather_than_failing() -> None:
    """A currency pair reports an exchange belonging to no equity market. Every cross-asset
    reading beside it is American, so the American sectors are the set that matches."""
    assert boards.of("CCY") is boards.BOARDS[boards.DEFAULT_MARKET]
    assert boards.of(None) is boards.BOARDS[boards.DEFAULT_MARKET]


def test_every_board_names_the_market_it_describes() -> None:
    """The caption under the chart is the only thing telling a reader which continent it is."""
    assert all(board.market for board in boards.BOARDS.values())
    assert boards.of("NSI").market != boards.of("SNP").market


def test_a_sector_a_market_has_no_index_for_gets_no_peer_rather_than_a_foreign_one() -> None:
    """Yahoo calls an Indian utility 'Utilities' and the NSE publishes no utilities index. Pairing
    it with the American fund would compare a Mumbai session against a New York one."""
    indian: Final = boards.of("NSI")

    assert "Utilities" not in indian.proxies
    assert all(ticker in indian.sectors for ticker in indian.proxies.values())


def test_every_proxy_on_every_board_points_at_a_sector_that_board_actually_carries() -> None:
    for market, board in boards.BOARDS.items():
        unknown = {ticker for ticker in board.proxies.values() if ticker not in board.sectors}
        assert not unknown, f"{market} pairs a company sector with {unknown}, which is not on its board"


def test_every_weighted_board_maps_its_weights_onto_its_own_sectors() -> None:
    """A weight key pointing at a ticker the board does not carry silently drops that sector's
    contribution, and the board then ranks by a figure most of it lacks."""
    for market, board in boards.BOARDS.items():
        if board.weights_from is None:
            assert not board.weight_keys, f"{market} carries weight keys with nothing to fetch them from"
            continue
        stray = {ticker for ticker in board.weight_keys.values() if ticker not in board.sectors}
        assert not stray, f"{market} weights {stray}, which is not on its board"


async def test_a_market_whose_sectors_have_no_history_is_read_from_the_quote() -> None:
    """Every NSE sector index returns one row for any window asked of it, so bars answer nothing
    and the quote answers the only question a board asks."""
    prices: Final = _Prices()

    context: Final = await _market(prices).backdrop(SESSION, "NSI")

    assert len(context.sectors) == len(boards.of("NSI").sectors)
    assert all(move.change_percent == pytest.approx(0.02) for move in context.sectors)
    assert not any(symbol.startswith("^CNX") for asked in prices.asked for symbol in asked)


async def test_a_quote_only_board_measures_nothing_for_a_session_it_cannot_speak_for() -> None:
    """The quote describes one day. Asked about any other, it must answer nothing rather than
    relabel today's move as last Tuesday's — which is the error a reader cannot possibly catch.
    """
    context: Final = await _market().backdrop(SESSION - timedelta(days=7), "NSI")

    assert context.sectors
    assert all(move.change_percent is None for move in context.sectors)


async def test_a_market_with_no_published_weights_carries_moves_and_no_contributions() -> None:
    context: Final = await _market().backdrop(SESSION, "NSI")

    assert all(move.change_percent is not None for move in context.sectors)
    assert all(move.contribution is None for move in context.sectors)


async def test_the_american_board_still_reads_from_bars() -> None:
    """The generalisation must not have quietly moved the one market that works properly onto the
    slower path: fourteen serial quotes where one batched request would do."""
    prices: Final = _Prices()

    _ = await _market(prices).backdrop(SESSION, "SNP")

    assert set(boards.BOARDS[boards.US].sectors) <= set(prices.asked[0])


async def test_a_session_still_being_traded_is_not_read_as_its_own_close() -> None:
    """A quote taken while the market is open carries a partial bar dated today. Comparing dates
    alone would accept it as that day's close, which is a figure nobody has measured yet."""
    today: Final = datetime.now(tz=ZoneInfo("Asia/Kolkata")).date()

    context: Final = await _market(quotes=_quotes(session=today)).backdrop(today, "NSI")

    assert context.sectors
    assert all(move.change_percent is None for move in context.sectors)
