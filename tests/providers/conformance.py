"""Every vendor, described in the terms the contract is written in.

A conformance test may not know a payload. That is the point of it: it asserts what callers above
are allowed to rely on, and no caller above can see a vendor. So a vendor entry here does not hand
over records, it hands over ports already built, each wired to a named situation the contract has
something to say about.

Adding a vendor means adding one entry. Whatever it gets wrong, it gets wrong here rather than in
a summary weeks later.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final

from orient.providers._untyped import Records
from orient.providers.fred import FredProvider
from orient.providers.protocols import (
    Calendars,
    Discovery,
    Earnings,
    MarketData,
    Prices,
    Reference,
    Series,
)
from orient.providers.yahoo import (
    YahooCalendars,
    YahooDiscovery,
    YahooEarnings,
    YahooMarket,
    YahooPrices,
    YahooReference,
)

FIRST: Final = date(2026, 8, 10)
SECOND: Final = date(2026, 8, 11)
THIRD: Final = date(2026, 8, 12)
SESSIONS: Final = (FIRST, SECOND, THIRD)

WINDOW_START: Final = date(2026, 8, 10)
WINDOW_END: Final = date(2026, 8, 17)

SYMBOL: Final = "^GSPC"
OTHER: Final = "^VIX"
SOONER: Final = "SOONER"
LATER: Final = "LATER"
UNDATED: Final = "UNDATED"


@dataclass(frozen=True, slots=True)
class Vendor:
    """One vendor's ports, each built over a situation rather than over a payload.

    `unordered_prices` exists because a vendor's own ordering is not a contract. What matters is
    that whatever order it sends, the port hands back the one every window calculation reads in.
    """

    name: str
    unordered_prices: Callable[[], Prices]
    one_symbol_prices: Callable[[], Prices]
    silent_prices: Callable[[], Prices]
    mixed_calendar: Callable[[], Calendars]
    silent_calendar: Callable[[], Calendars]
    silent_market: Callable[[], MarketData]


def _yahoo_bar(session_date: date, close: float) -> Mapping[str, object]:
    return {
        "session_date": session_date,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1_000,
    }


def _yahoo_prices(series: Mapping[str, Records]) -> YahooPrices:
    def fetch_one(symbol: str, period: str) -> Records:
        del period
        return series.get(symbol, ())

    def fetch_many(symbols: Sequence[str], period: str) -> Mapping[str, Records]:
        del period
        return {symbol: series[symbol] for symbol in symbols if symbol in series}

    return YahooPrices(fetch_one, fetch_many)


def _yahoo_unordered() -> YahooPrices:
    """A frame arrives in whatever order its index happens to be in, which is not a promise."""
    rows: Final = (_yahoo_bar(THIRD, 102.0), _yahoo_bar(FIRST, 100.0), _yahoo_bar(SECOND, 101.0))
    return _yahoo_prices({SYMBOL: rows, OTHER: tuple(reversed(rows))})


def _no_rows(start: date, end: date) -> Records:
    del start, end
    return ()


def _yahoo_mixed_calendar() -> YahooCalendars:
    def ipos(start: date, end: date) -> Records:
        del start, end
        return (
            {"symbol": UNDATED, "company": "Not Priced Yet", "exchange": "NMS", "event_date": None},
            {"symbol": LATER, "company": "Later Co", "exchange": "NMS", "event_date": WINDOW_END},
            {"symbol": SOONER, "company": "Sooner Co", "exchange": "NMS", "event_date": WINDOW_START},
        )

    return YahooCalendars(_no_rows, _no_rows, ipos, _no_rows)


class _SilentSeries:
    def observations(self, series_id: str, start: date, end: date) -> tuple[()]:
        del series_id, start, end
        return ()


YAHOO: Final = Vendor(
    name="yahoo",
    unordered_prices=_yahoo_unordered,
    one_symbol_prices=lambda: _yahoo_prices({SYMBOL: (_yahoo_bar(FIRST, 100.0),)}),
    silent_prices=lambda: _yahoo_prices({}),
    mixed_calendar=_yahoo_mixed_calendar,
    silent_calendar=lambda: YahooCalendars(_no_rows, _no_rows, _no_rows, _no_rows),
    silent_market=lambda: YahooMarket(_yahoo_prices({}), _SilentSeries(), lambda _: None, lambda: THIRD),
)

VENDORS: Final[tuple[Vendor, ...]] = (YAHOO,)

ADAPTERS: Final[tuple[tuple[type, type], ...]] = (
    (Prices, YahooPrices),
    (Series, FredProvider),
    (Discovery, YahooDiscovery),
    (Reference, YahooReference),
    (Earnings, YahooEarnings),
    (MarketData, YahooMarket),
    (Calendars, YahooCalendars),
)
