"""Yahoo prices, validated at the boundary.

The fetchers block, so each call is handed to a worker thread here rather than in every tool that
reaches for one. That keeps the decision beside the code that knows it blocks.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from functools import partial
from math import isfinite
from typing import Final

from anyio import to_thread
from pydantic import TypeAdapter

from orient.domain.models import Bar
from orient.providers._untyped import Records, yahoo_daily_bars, yahoo_multi_bars

_BARS: Final = TypeAdapter(tuple[Bar, ...])

FetchOne = Callable[[str, date, date], Records]
FetchMany = Callable[[Sequence[str], date, date], Mapping[str, Records]]


PRICES: Final = ("open", "high", "low", "close")


def _priced(value: object) -> bool:
    """A cell holding a number, which excludes both ways a frame says it holds nothing.

    A single-symbol fetch maps the frame's NaN to None on the way out; a batched one does not, so
    NaN arrives intact. Both must be caught here: pydantic accepts NaN as a float, so a row that
    slips through becomes a bar whose close is NaN, and the first thing that notices is Postgres
    refusing to store a vector built from it, several layers away.
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def _traded(record: Mapping[str, object]) -> bool:
    """Whether this row is a session that printed prices.

    Two kinds of row are not. A batched download pads every symbol to a shared calendar, and the
    vendor also emits a stub for a session that has opened its books but not yet traded: volume
    populated, every price empty.

    A column that is missing entirely is a different thing, and still fails validation rather than
    quietly shortening the series.
    """
    return all(_priced(record[field]) for field in PRICES if field in record)


def _bars(records: Records) -> tuple[Bar, ...]:
    """Oldest first, because every window calculation above reads the last row as the latest one."""
    validated: Final = _BARS.validate_python(tuple(row for row in records if _traded(row)))
    return tuple(sorted(validated, key=lambda bar: bar.session_date))


class YahooPrices:
    def __init__(
        self,
        fetch_one: FetchOne = yahoo_daily_bars,
        fetch_many: FetchMany = yahoo_multi_bars,
    ) -> None:
        self._fetch_one: Final = fetch_one
        self._fetch_many: Final = fetch_many

    async def bars(self, symbol: str, start: date, end: date) -> tuple[Bar, ...]:
        return _bars(await to_thread.run_sync(partial(self._fetch_one, symbol, start, end)))

    async def multi_bars(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
    ) -> Mapping[str, tuple[Bar, ...]]:
        """One request for many symbols. A symbol with nothing usable maps to an empty tuple
        rather than disappearing, so a caller iterating its own list never gets a KeyError."""
        fetched: Final = await to_thread.run_sync(partial(self._fetch_many, symbols, start, end))
        return {symbol: _bars(fetched.get(symbol, ())) for symbol in symbols}
