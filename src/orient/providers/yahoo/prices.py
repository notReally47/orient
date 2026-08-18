"""Yahoo prices, validated at the boundary."""

from collections.abc import Callable, Mapping, Sequence
from math import isnan
from typing import Final

from pydantic import TypeAdapter

from orient.domain.models import Bar
from orient.providers._untyped import Records, yahoo_daily_bars, yahoo_multi_bars

DEFAULT_PERIOD: Final = "1y"

_BARS: Final = TypeAdapter(tuple[Bar, ...])


def _traded(record: Mapping[str, object]) -> bool:
    """A batched download pads every symbol to a shared calendar, marking the gaps NaN.

    Only NaN is dropped. A close that is absent rather than not-a-number means the column
    moved, which must still fail validation instead of quietly shortening the series.
    """
    close: Final = record.get("close")
    return not (isinstance(close, float) and isnan(close))


def _bars(records: Records) -> tuple[Bar, ...]:
    """Oldest first, because every window calculation above reads the last row as the latest one."""
    validated: Final = _BARS.validate_python(tuple(row for row in records if _traded(row)))
    return tuple(sorted(validated, key=lambda bar: bar.session_date))


class YahooPrices:
    def __init__(
        self,
        fetch_one: Callable[[str, str], Records] = yahoo_daily_bars,
        fetch_many: Callable[[Sequence[str], str], Mapping[str, Records]] = yahoo_multi_bars,
    ) -> None:
        self._fetch_one: Final = fetch_one
        self._fetch_many: Final = fetch_many

    def daily_bars(self, symbol: str, period: str = DEFAULT_PERIOD) -> tuple[Bar, ...]:
        return _bars(self._fetch_one(symbol, period))

    def multi_bars(self, symbols: Sequence[str], period: str = DEFAULT_PERIOD) -> Mapping[str, tuple[Bar, ...]]:
        """One request for many symbols. A symbol with nothing usable maps to an empty tuple
        rather than disappearing, so a caller iterating its own list never gets a KeyError."""
        fetched: Final = self._fetch_many(symbols, period)
        return {symbol: _bars(fetched.get(symbol, ())) for symbol in symbols}
