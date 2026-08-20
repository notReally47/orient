"""The contract every vendor satisfies, asserted once and run against each of them.

Nothing here names a payload, a column or an endpoint. These are the promises the tools, the
orchestrator and the domain are written against, so a second vendor that passes them is a drop-in
rather than a hope, and one that does not fails before anything above it learns the difference.

The vendor-specific suites sit beside this one and do the opposite job: they assert that a
particular vendor's payload is read correctly, which is exactly what a shared test cannot say.
"""

from typing import Final

import pytest

from tests.providers.conformance import (
    ADAPTERS,
    LATER,
    OTHER,
    SESSIONS,
    SOONER,
    SYMBOL,
    UNDATED,
    VENDORS,
    WINDOW_END,
    WINDOW_START,
    Vendor,
)

WINDOW: Final = (WINDOW_START, WINDOW_END)


def _vendor_id(vendor: Vendor) -> str:
    return vendor.name


def _class_id(cls: type) -> str:
    return cls.__name__


_VENDORS: Final = pytest.mark.parametrize("vendor", VENDORS, ids=_vendor_id)


@_VENDORS
async def test_bars_come_back_oldest_first(vendor: Vendor) -> None:
    """Every window calculation reads the last bar as the latest, so the order is the contract."""
    bars: Final = await vendor.unordered_prices().bars(SYMBOL, *WINDOW)

    assert tuple(bar.session_date for bar in bars) == SESSIONS


@_VENDORS
async def test_a_batched_fetch_orders_every_symbol_the_same_way(vendor: Vendor) -> None:
    """One symbol arriving reversed would give the backdrop yesterday's close for that one alone."""
    fetched: Final = await vendor.unordered_prices().multi_bars((SYMBOL, OTHER), *WINDOW)

    for symbol in (SYMBOL, OTHER):
        assert tuple(bar.session_date for bar in fetched[symbol]) == SESSIONS


@_VENDORS
async def test_a_symbol_the_vendor_had_nothing_for_is_empty_rather_than_absent(vendor: Vendor) -> None:
    """A caller iterating its own basket must not get a KeyError because one fund did not price."""
    fetched: Final = await vendor.one_symbol_prices().multi_bars((SYMBOL, OTHER), *WINDOW)

    assert set(fetched) == {SYMBOL, OTHER}
    assert fetched[OTHER] == ()


@_VENDORS
async def test_a_vendor_with_nothing_to_say_returns_empty_rather_than_raising(vendor: Vendor) -> None:
    prices: Final = vendor.silent_prices()

    assert await prices.bars(SYMBOL, *WINDOW) == ()
    assert await prices.multi_bars((SYMBOL,), *WINDOW) == {SYMBOL: ()}


@_VENDORS
async def test_calendar_entries_sort_by_date_with_the_undated_last(vendor: Vendor) -> None:
    """An event with no date still matters; sorting it first would bury what happens tomorrow."""
    calendar: Final = await vendor.mixed_calendar().entries(WINDOW_START, WINDOW_END)

    assert tuple(entry.symbol for entry in calendar.entries) == (SOONER, LATER, UNDATED)


@_VENDORS
async def test_a_calendar_says_how_much_it_could_not_read(vendor: Vendor) -> None:
    """A list short by a third looks exactly like a quiet week unless the answer says so."""
    calendar: Final = await vendor.mixed_calendar().entries(WINDOW_START, WINDOW_END)

    assert calendar.unreadable == 0


@_VENDORS
async def test_an_empty_week_is_an_empty_calendar_rather_than_a_failure(vendor: Vendor) -> None:
    calendar: Final = await vendor.silent_calendar().entries(WINDOW_START, WINDOW_END)

    assert calendar.entries == ()
    assert calendar.unreadable == 0


@_VENDORS
async def test_a_backdrop_with_nothing_to_report_yields_nulls_rather_than_raising(vendor: Vendor) -> None:
    """A dead upstream must degrade to a summary that says less, never to a run that says nothing."""
    context: Final = await vendor.silent_market().backdrop(WINDOW_END)

    assert context.cross_asset.vix is None
    assert context.cross_asset.yield_10y is None
    assert context.cross_asset.spread_10s2s is None
    assert all(move.change_percent is None for move in context.sectors)


@_VENDORS
async def test_a_backdrop_with_nothing_to_report_still_counts_its_denominator(vendor: Vendor) -> None:
    """Zero advancers out of zero measured is a different statement from zero out of eleven."""
    breadth: Final = (await vendor.silent_market().backdrop(WINDOW_END)).sector_breadth

    assert breadth is not None
    assert (breadth.advancers, breadth.decliners, breadth.unchanged, breadth.total) == (0, 0, 0, 0)


@pytest.mark.parametrize(("port", "adapter"), ADAPTERS, ids=_class_id)
def test_an_adapter_exposes_its_port_and_nothing_more(port: type, adapter: type) -> None:
    """A vendor-only method is a way for a caller above to depend on a vendor without noticing.

    That the adapter satisfies the port is settled statically, at every site one is constructed.
    What static checking cannot say is that it offers nothing else, which is the half that keeps
    a swap seamless.
    """

    def surface(cls: type) -> frozenset[str]:
        return frozenset(name for name in dir(cls) if not name.startswith("_"))

    assert surface(adapter) == surface(port)
