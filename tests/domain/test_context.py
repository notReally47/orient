"""Assembling the backdrop. Pure functions, so the edge cases are cheap to pin.

The sector-level framing is the thing under test as much as the arithmetic: these counts must
never be presentable as index breadth, because no constituent list exists to compute that from.
"""

from datetime import date, timedelta
from typing import TYPE_CHECKING, Final

import pytest

from orient.domain.context import (
    CROSS_ASSET_SERIES,
    CROSS_ASSET_TICKERS,
    SECTOR_ETFS,
    VIX,
    build_cross_asset,
    build_sector_breadth,
    build_sector_moves,
)
from orient.domain.models import Bar, Observation

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_START: Final = date(2026, 8, 10)


def _bars(*closes: float) -> tuple[Bar, ...]:
    return tuple(
        Bar(
            session_date=_START + timedelta(days=offset),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1,
        )
        for offset, close in enumerate(closes)
    )


def _series(value: float) -> tuple[Observation, ...]:
    return (Observation(observation_date=_START, value=value),)


def test_eleven_sectors_are_tracked() -> None:
    """One batched download covers them all, so the count is also the request budget."""
    assert len(SECTOR_ETFS) == 11


def test_cross_asset_reads_levels_from_prices_and_rates_from_series() -> None:
    bars: Final[Mapping[str, Sequence[Bar]]] = {VIX: _bars(16.0, 18.0), "GC=F": _bars(2400.0)}
    series: Final = {"DGS10": _series(4.25), "DGS2": _series(3.75)}

    cross: Final = build_cross_asset(bars, series)

    assert cross.vix == pytest.approx(18.0)
    assert cross.vix_change == pytest.approx(0.125)
    assert cross.gold == pytest.approx(2400.0)
    assert cross.yield_10y == pytest.approx(4.25)
    assert cross.spread_10s2s == pytest.approx(0.5)


def test_a_missing_ticker_leaves_its_field_null_rather_than_zero() -> None:
    """Zero is a price. Absent is not, and a summary must be able to tell them apart."""
    cross: Final = build_cross_asset({}, {})
    assert cross.vix is None
    assert cross.crude_oil is None
    assert cross.yield_10y is None
    assert cross.spread_10s2s is None


def test_the_curve_spread_needs_both_legs() -> None:
    assert build_cross_asset({}, {"DGS10": _series(4.25)}).spread_10s2s is None


def test_every_cross_asset_field_is_sourced_from_somewhere() -> None:
    """A field with no ticker or series behind it would always be null and quietly mislead."""
    sourced: Final = {*CROSS_ASSET_TICKERS.values(), *CROSS_ASSET_SERIES.values(), "vix_change", "spread_10s2s"}
    assert set(build_cross_asset({}, {}).model_dump()) == sourced


def test_sector_moves_come_back_strongest_first() -> None:
    bars: Final = {"XLK": _bars(100.0, 105.0), "XLE": _bars(100.0, 95.0), "XLF": _bars(100.0, 101.0)}
    moves: Final = build_sector_moves(bars)

    priced = [move.symbol for move in moves if move.change_percent is not None]
    assert priced == ["XLK", "XLF", "XLE"]


def test_sectors_without_prices_sort_last_rather_than_vanishing() -> None:
    moves: Final = build_sector_moves({"XLK": _bars(100.0, 105.0)})
    assert len(moves) == len(SECTOR_ETFS)
    assert moves[0].symbol == "XLK"
    assert moves[-1].change_percent is None


def test_breadth_counts_only_sectors_that_actually_priced() -> None:
    bars: Final = {"XLK": _bars(100.0, 105.0), "XLE": _bars(100.0, 95.0), "XLF": _bars(100.0, 100.0)}
    breadth: Final = build_sector_breadth(build_sector_moves(bars))

    assert (breadth.advancers, breadth.decliners, breadth.unchanged) == (1, 1, 1)
    assert breadth.top[0].symbol == "XLK"
    assert breadth.bottom[0].symbol == "XLE"


def test_breadth_of_nothing_priced_is_all_zero() -> None:
    breadth: Final = build_sector_breadth(build_sector_moves({}))
    assert (breadth.advancers, breadth.decliners, breadth.unchanged) == (0, 0, 0)
    assert breadth.top == ()


def test_a_single_close_yields_no_change_rather_than_zero() -> None:
    """One bar cannot express a move, and reporting it as flat would be a fabricated figure."""
    assert build_sector_moves({"XLK": _bars(100.0)})[0].change_percent is None
