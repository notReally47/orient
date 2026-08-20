"""The read-through price cache: what it serves, and what it refuses to spend a request on.

The source here counts its calls, because the whole point of this layer is the requests it does
not make. A cache that returned the right bars while still asking the vendor every time would
pass a correctness test and fail at its job.
"""

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Final

from orient.domain.models import Bar
from orient.providers.cache import GAP_TOLERANCE, CachedPrices

SYMBOL: Final = "^GSPC"
OTHER: Final = "^VIX"
START: Final = date(2026, 8, 3)
END: Final = date(2026, 8, 12)


def _bar(day: date, close: float = 100.0) -> Bar:
    return Bar(session_date=day, open=close, high=close, low=close, close=close, volume=1_000)


def _span(first: date, last: date, close: float = 100.0) -> tuple[Bar, ...]:
    days: Final = (last - first).days
    return tuple(_bar(first + timedelta(days=offset), close) for offset in range(days + 1))


class _Store:
    def __init__(self, held: Mapping[str, tuple[Bar, ...]] | None = None) -> None:
        self.held: dict[str, tuple[Bar, ...]] = dict(held or {})
        self.written: list[tuple[str, int]] = []

    async def between(self, symbol: str, start: date, end: date) -> tuple[Bar, ...]:
        return tuple(bar for bar in self.held.get(symbol, ()) if start <= bar.session_date <= end)

    async def add(self, symbol: str, bars: Sequence[Bar]) -> None:
        self.written.append((symbol, len(bars)))
        merged: Final = {bar.session_date: bar for bar in (*self.held.get(symbol, ()), *bars)}
        self.held[symbol] = tuple(bar for _, bar in sorted(merged.items()))


class _Source:
    def __init__(self, series: Mapping[str, tuple[Bar, ...]] | None = None) -> None:
        self._series: Final = dict(series or {})
        self.windows: list[tuple[str, date, date]] = []
        self.batches: list[tuple[str, ...]] = []

    async def bars(self, symbol: str, start: date, end: date) -> tuple[Bar, ...]:
        self.windows.append((symbol, start, end))
        return tuple(bar for bar in self._series.get(symbol, ()) if start <= bar.session_date <= end)

    async def multi_bars(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
    ) -> Mapping[str, tuple[Bar, ...]]:
        self.batches.append(tuple(symbols))
        return {symbol: await self.bars(symbol, start, end) for symbol in symbols}


async def test_a_fully_stored_window_costs_the_vendor_nothing() -> None:
    """This is the whole point: the second run for an instrument is a database read."""
    source: Final = _Source()
    cache: Final = CachedPrices(source, _Store({SYMBOL: _span(START, END)}))

    bars: Final = await cache.bars(SYMBOL, START, END)

    assert source.windows == []
    assert len(bars) == (END - START).days + 1


async def test_an_empty_table_asks_for_the_whole_window_and_writes_it_back() -> None:
    store: Final = _Store()
    source: Final = _Source({SYMBOL: _span(START, END)})

    bars: Final = await CachedPrices(source, store).bars(SYMBOL, START, END)

    assert source.windows == [(SYMBOL, START, END)]
    assert store.written == [(SYMBOL, len(bars))]
    assert await store.between(SYMBOL, START, END) == bars


async def test_only_the_missing_tail_is_fetched_when_the_table_stops_short() -> None:
    """A window that already reaches back far enough must not refetch the part it has."""
    stored_last: Final = END - GAP_TOLERANCE - timedelta(days=3)
    store: Final = _Store({SYMBOL: _span(START, stored_last)})
    source: Final = _Source({SYMBOL: _span(START, END)})

    _ = await CachedPrices(source, store).bars(SYMBOL, START, END)

    assert source.windows == [(SYMBOL, stored_last + timedelta(days=1), END)]


async def test_only_the_missing_head_is_fetched_when_the_table_starts_late() -> None:
    stored_first: Final = START + GAP_TOLERANCE + timedelta(days=3)
    store: Final = _Store({SYMBOL: _span(stored_first, END)})
    source: Final = _Source({SYMBOL: _span(START, END)})

    _ = await CachedPrices(source, store).bars(SYMBOL, START, END)

    assert source.windows == [(SYMBOL, START, stored_first - timedelta(days=1))]


async def test_a_weekend_shaped_hole_is_not_mistaken_for_missing_data() -> None:
    """Markets shut. A bar that never existed must not cost a request on every later run."""
    stored: Final = _span(START, END - timedelta(days=2))
    source: Final = _Source({SYMBOL: _span(START, END)})

    _ = await CachedPrices(source, _Store({SYMBOL: stored})).bars(SYMBOL, START, END)

    assert source.windows == []


async def test_a_stored_bar_wins_over_a_refetched_one() -> None:
    """A bar already written is the one an earlier summary cited, so a vendor revision cannot move it."""
    wide_start: Final = date(2026, 8, 1)
    wide_end: Final = date(2026, 8, 20)
    held: Final = date(2026, 8, 10)
    store: Final = _Store({SYMBOL: (_bar(held, 6000.0),)})
    source: Final = _Source({SYMBOL: (_bar(held, 1.0), _bar(wide_end, 2.0))})

    bars: Final = await CachedPrices(source, store).bars(SYMBOL, wide_start, wide_end)

    assert source.windows == [(SYMBOL, wide_start, wide_end)]
    assert [bar.close for bar in bars] == [6000.0, 2.0]


async def test_a_batch_asks_only_for_the_symbols_that_need_one() -> None:
    store: Final = _Store({SYMBOL: _span(START, END)})
    source: Final = _Source({OTHER: _span(START, END)})

    fetched: Final = await CachedPrices(source, store).multi_bars((SYMBOL, OTHER), START, END)

    assert source.batches == [(OTHER,)]
    assert set(fetched) == {SYMBOL, OTHER}


async def test_a_batch_with_nothing_missing_makes_no_request_at_all() -> None:
    store: Final = _Store({SYMBOL: _span(START, END), OTHER: _span(START, END)})
    source: Final = _Source()

    _ = await CachedPrices(source, store).multi_bars((SYMBOL, OTHER), START, END)

    assert source.batches == []


async def test_a_symbol_the_source_had_nothing_for_is_empty_rather_than_absent() -> None:
    """A caller iterating its own list of symbols must never get a KeyError from this layer."""
    fetched: Final = await CachedPrices(_Source(), _Store()).multi_bars((SYMBOL, OTHER), START, END)

    assert fetched == {SYMBOL: (), OTHER: ()}
