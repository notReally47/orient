"""A read-through price cache, expressed as a `Prices` implementation over another one.

A fallback between two sources is a composition over two objects of the same port rather than
anything either of them is aware of, and this is the working instance of that: it satisfies
`Prices`, answers from the bars table, and asks the source behind it only for what the table is
missing. Nothing above learns a cache exists.

A daily bar for a past session never changes, which is what makes this safe to cache without an
expiry. Only the near edge moves, as today's session closes, so only the near edge is refetched.
"""

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Final, Protocol

from orient.domain.models import Bar
from orient.providers.protocols import Prices

# A stored window is complete when it reaches this close to each end. Markets shut for weekends
# and holidays, so the absence of a bar is not evidence that one is missing.
GAP_TOLERANCE: Final = timedelta(days=4)


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
    head: Final = stored[0].session_date > start + GAP_TOLERANCE
    tail: Final = stored[-1].session_date < end - GAP_TOLERANCE
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
