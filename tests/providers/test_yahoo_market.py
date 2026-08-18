"""The market adapter, driven with the payloads Yahoo really returns.

The session payload is the one `make shapes` prints: the bounds already parsed into datetimes,
and the zone nested inside an object beside its offset rather than sitting flat as a string. The
value types are the point. A test written against the names alone passed while the live call
failed, which is why every field here carries the type Yahoo sends.
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from types import MappingProxyType
from typing import Final

from orient.domain.models import Bar, Observation
from orient.providers.yahoo.market import SECTOR_ETFS, YahooMarket

EASTERN: Final = timezone(timedelta(hours=-4), "EDT")
TODAY: Final = date(2026, 8, 12)

NO_BARS: Final[Mapping[str, tuple[Bar, ...]]] = MappingProxyType({})
NO_RATES: Final[Mapping[str, float]] = MappingProxyType({})

STATUS: Final[Mapping[str, object]] = {
    "id": "us",
    "name": "U.S. Markets",
    "status": "closed",
    "open": datetime(2026, 8, 12, 9, 30, tzinfo=EASTERN),
    "close": datetime(2026, 8, 12, 16, 0, tzinfo=EASTERN),
    "timezone": {"gmtoffset": -14400000, "short": "EDT", "long": "Eastern Daylight Time"},
    "tz": EASTERN,
}


def _bars(*closes: float) -> tuple[Bar, ...]:
    return tuple(
        Bar(session_date=date(2026, 8, 10 + offset), open=100.0, high=100.0, low=100.0, close=close, volume=1_000)
        for offset, close in enumerate(closes)
    )


class _Prices:
    def __init__(self, series: Mapping[str, tuple[Bar, ...]]) -> None:
        self._series: Final = series
        self.asked: Final[list[tuple[str, ...]]] = []

    def daily_bars(self, symbol: str, period: str) -> tuple[Bar, ...]:
        del period
        return self._series.get(symbol, ())

    def multi_bars(self, symbols: Sequence[str], period: str) -> Mapping[str, tuple[Bar, ...]]:
        del period
        self.asked.append(tuple(symbols))
        return {symbol: self._series[symbol] for symbol in symbols if symbol in self._series}


class _Series:
    def __init__(self, values: Mapping[str, float]) -> None:
        self._values: Final = values

    def observations(self, series_id: str, start: date, end: date) -> tuple[Observation, ...]:
        del start, end
        value: Final = self._values.get(series_id)
        return () if value is None else (Observation(observation_date=TODAY, value=value),)


def _market(
    series: Mapping[str, tuple[Bar, ...]] = NO_BARS,
    rates: Mapping[str, float] = NO_RATES,
    status: Mapping[str, object] | None = STATUS,
) -> YahooMarket:
    return YahooMarket(_Prices(series), _Series(rates), lambda _: status, lambda: TODAY)


def test_the_session_bounds_come_back_as_the_moments_yahoo_parsed() -> None:
    """They arrive as datetimes, so a model declaring them strings would reject the live payload."""
    session: Final = _market().backdrop().session

    assert session is not None
    assert session.opens_at == datetime(2026, 8, 12, 9, 30, tzinfo=EASTERN)
    assert session.closes_at == datetime(2026, 8, 12, 16, 0, tzinfo=EASTERN)


def test_the_zone_is_unwrapped_from_the_object_it_arrives_inside() -> None:
    """Yahoo nests the zone beside its offset; passing the object up would fail validation."""
    session: Final = _market().backdrop().session

    assert session is not None
    assert session.timezone == "EDT"
    assert session.status == "closed"
    assert session.name == "U.S. Markets"


def test_a_region_yahoo_will_not_serve_is_an_empty_session_rather_than_a_failure() -> None:
    """yfinance answers None both for an unserved region and for a parse failure in one it serves."""
    session: Final = _market(status=None).backdrop().session

    assert session is not None
    assert session.status is None
    assert session.opens_at is None


def test_the_whole_backdrop_is_fetched_in_one_request() -> None:
    """At fifteen requests a minute, three round trips for one bundle is the cost that matters."""
    prices: Final = _Prices({})
    _ = YahooMarket(prices, _Series({}), lambda _: STATUS, lambda: TODAY).backdrop()

    assert len(prices.asked) == 1
    assert set(SECTOR_ETFS) <= set(prices.asked[0])
    assert "^VIX" in prices.asked[0]


def test_the_volatility_index_carries_its_level_and_its_change() -> None:
    cross: Final = _market({"^VIX": _bars(16.0, 18.0)}).backdrop().cross_asset

    assert cross.vix == 18.0
    assert cross.vix_change is not None
    assert round(cross.vix_change, 4) == 0.125


def test_the_yields_come_from_the_series_source_and_the_spread_is_their_difference() -> None:
    """Yahoo publishes no two year index, so the rates come from elsewhere and nothing above knows."""
    cross: Final = _market(rates={"DGS10": 4.2, "DGS2": 3.7}).backdrop().cross_asset

    assert cross.yield_10y == 4.2
    assert cross.yield_2y == 3.7
    assert cross.spread_10s2s is not None
    assert round(cross.spread_10s2s, 4) == 0.5


def test_sectors_come_back_strongest_first_with_the_unpriced_ones_last() -> None:
    market: Final = _market({"XLK": _bars(100.0, 102.0), "XLE": _bars(100.0, 99.0), "XLF": _bars(100.0, 101.0)})

    moves: Final = market.backdrop().sectors

    assert tuple(move.symbol for move in moves)[:3] == ("XLK", "XLF", "XLE")
    assert all(move.change_percent is None for move in moves[3:])


def test_breadth_is_counted_over_the_sectors_that_were_priced() -> None:
    """An unpriced fund is neither an advancer nor a decliner, and the total says how many counted."""
    market: Final = _market({"XLK": _bars(100.0, 102.0), "XLE": _bars(100.0, 99.0), "XLF": _bars(100.0, 100.0)})

    breadth: Final = market.backdrop().sector_breadth

    assert breadth is not None
    assert (breadth.advancers, breadth.decliners, breadth.unchanged, breadth.total) == (1, 1, 1, 3)
    assert breadth.top[0].symbol == "XLK"


def test_every_sector_in_the_basket_is_named_whether_or_not_it_priced() -> None:
    """The prose says sector, so a fund missing from the answer would read as a sector that did not move."""
    moves: Final = _market().backdrop().sectors

    assert {move.symbol for move in moves} == set(SECTOR_ETFS)
    assert all(move.name == SECTOR_ETFS[move.symbol] for move in moves)


def test_the_region_asked_for_is_the_one_configured() -> None:
    asked: Final[list[str]] = []

    def status(region: str) -> Mapping[str, object]:
        asked.append(region)
        return STATUS

    _ = YahooMarket(_Prices({}), _Series({}), status, lambda: TODAY, "GB").backdrop()

    assert asked == ["GB"]
