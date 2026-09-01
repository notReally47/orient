"""A read-through price cache, expressed as a `Prices` implementation over another one.

A fallback between two sources is a composition over two objects of the same port rather than
anything either of them is aware of, and this is the working instance of that: it satisfies
`Prices`, answers from the bars table, and asks the source behind it only for what the table is
missing. Nothing above learns a cache exists.

A daily bar for a past session never changes, which is what makes this safe to cache without an
expiry. Only the near edge moves, as today's session closes, so only the near edge is refetched,
and the two ends are given different amounts of slack because they fail in different directions:
missing history is a shorter chart, while a missing newest bar is a wrong answer to "when did
this last trade".
"""

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Final, Protocol

from orient.domain.models import Bar
from orient.providers.protocols import Prices

HEAD_TOLERANCE: Final = timedelta(days=4)

SATURDAY: Final = 5


def _trades_weekends(stored: Sequence[Bar]) -> bool:
    """Whether this instrument has ever closed on a Saturday or Sunday.

    The instrument's own history is the only calendar available here, and for this question it is
    enough: an equity index has no weekend bars and a cryptocurrency has nothing but. Reading it
    off the rows keeps the cache from having to be told which is which.
    """
    return any(bar.session_date.weekday() >= SATURDAY for bar in stored)


def _sessions_missed(stored: Sequence[Bar], end: date) -> bool:
    """Whether a day this instrument would have traded has gone by since the newest stored bar.

    The near edge cannot be given the same slack as the far one. Four days of it is enough to
    swallow a whole session: a Tuesday asking for a window that ends today accepts a stored tail
    of Friday, never fetches Monday, and leaves the newest session on file a day behind for most
    of the week — which is how the front end came to offer a Friday as the last close.

    `end` itself is excluded because it is usually today, and today's bar does not exist until
    today's session closes. Counting it would mean a vendor request on every page view. What is
    counted instead is the days in between, against this instrument's own trading week, so a
    weekend costs an equity index nothing and still lets a cryptocurrency pick up its Saturday.
    """
    weekends: Final = _trades_weekends(stored)
    day = stored[-1].session_date + timedelta(days=1)
    while day < end:
        if weekends or day.weekday() < SATURDAY:
            return True
        day += timedelta(days=1)
    return False


class BarStore(Protocol):
    async def between(self, symbol: str, start: date, end: date, /) -> tuple[Bar, ...]: ...

    async def add(self, symbol: str, bars: Sequence[Bar], /) -> None: ...


def _gap(stored: Sequence[Bar], start: date, end: date) -> tuple[date, date] | None:
    """The one window worth asking for, or None when what is stored already reaches both ends.

    Two separate holes would need two requests, and requests are the scarce resource, so a
    stored middle with both ends missing is refetched whole rather than twice.
    """
    if not stored:
        return (start, end)
    head: Final = stored[0].session_date > start + HEAD_TOLERANCE
    tail: Final = _sessions_missed(stored, end)
    match (head, tail):
        case (True, True):
            return (start, end)
        case (True, False):
            return (start, stored[0].session_date - timedelta(days=1))
        case (False, True):
            return (stored[-1].session_date + timedelta(days=1), end)
        case _:
            return None


def _merged(stored: Sequence[Bar], fetched: Sequence[Bar], start: date, end: date) -> tuple[Bar, ...]:
    """Stored rows win, since a bar already written is the one every earlier summary cited."""
    by_date: Final = {bar.session_date: bar for bar in (*fetched, *stored)}
    return tuple(bar for _, bar in sorted(by_date.items()) if start <= bar.session_date <= end)


class CachedPrices:
    def __init__(self, source: Prices, store: BarStore) -> None:
        self._source: Final = source
        self._store: Final = store

    async def bars(self, symbol: str, start: date, end: date) -> tuple[Bar, ...]:
        """Bars for the window, fetching only the part the store does not already hold."""
        stored: Final = await self._store.between(symbol, start, end)
        window: Final = _gap(stored, start, end)
        if window is None:
            return stored

        fetched: Final = await self._source.bars(symbol, *window)
        await self._store.add(symbol, fetched)
        return _merged(stored, fetched, start, end)

    async def multi_bars(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
    ) -> Mapping[str, tuple[Bar, ...]]:
        """One batched request for whichever symbols need one, and none at all when none do."""
        stored: Final = {symbol: await self._store.between(symbol, start, end) for symbol in symbols}
        wanted: Final = tuple(symbol for symbol in symbols if _gap(stored[symbol], start, end) is not None)
        if not wanted:
            return stored

        fetched: Final = await self._source.multi_bars(wanted, start, end)
        for symbol, bars in fetched.items():
            await self._store.add(symbol, bars)
        return {symbol: _merged(stored[symbol], fetched.get(symbol, ()), start, end) for symbol in symbols}
