"""Signal math is where a wrong number would reach the reader looking exactly like a right one.

The property under test throughout is that a window too short to compute honestly yields None
rather than a figure derived from whatever history happened to exist.
"""

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Final

import pytest

from orient.domain.models import Bar
from orient.domain.signals import (
    TRADING_DAYS_PER_YEAR,
    compute_breadth,
    compute_signals,
)

_START: Final = date(2026, 1, 5)


def _bars(closes: Sequence[float], volumes: Sequence[int] | None = None, start: date = _START) -> tuple[Bar, ...]:
    counts: Final = volumes if volumes is not None else [1] * len(closes)
    return tuple(
        Bar(
            session_date=start + timedelta(days=offset),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=count,
        )
        for offset, (close, count) in enumerate(zip(closes, counts, strict=True))
    )


def test_no_history_yields_no_signals() -> None:
    assert compute_signals("^GSPC", ()) is None


def test_one_day_return_uses_the_previous_close() -> None:
    signals: Final = compute_signals("^GSPC", _bars([100.0, 110.0]))
    assert signals is not None
    assert signals.returns.one_day == pytest.approx(0.1)
    assert signals.close == 110.0


def test_bars_are_ordered_before_anything_is_computed() -> None:
    """Providers do not promise ordering, and a reversed series would invert every return."""
    ordered: Final = _bars([100.0, 110.0])
    signals: Final = compute_signals("^GSPC", tuple(reversed(ordered)))
    assert signals is not None
    assert signals.session_date == ordered[-1].session_date
    assert signals.returns.one_day == pytest.approx(0.1)


@pytest.mark.parametrize(
    ("length", "attribute"),
    [(5, "one_week"), (21, "one_month"), (63, "three_month")],
)
def test_a_window_longer_than_the_history_is_none(length: int, attribute: str) -> None:
    signals: Final = compute_signals("^GSPC", _bars([100.0] * length))
    assert signals is not None
    assert getattr(signals.returns, attribute) is None


@pytest.mark.parametrize(
    ("length", "attribute"),
    [(6, "one_week"), (22, "one_month"), (64, "three_month")],
)
def test_a_window_exactly_covered_by_the_history_computes(length: int, attribute: str) -> None:
    closes: Final = [100.0] * (length - 1) + [110.0]
    signals: Final = compute_signals("^GSPC", _bars(closes))
    assert signals is not None
    assert getattr(signals.returns, attribute) == pytest.approx(0.1)


def test_a_zero_previous_close_yields_none_rather_than_dividing_by_zero() -> None:
    signals: Final = compute_signals("^GSPC", _bars([0.0, 5.0]))
    assert signals is not None
    assert signals.returns.one_day is None


def test_year_to_date_measures_from_the_previous_year_final_close() -> None:
    december: Final = _bars([100.0], start=date(2025, 12, 31))
    january: Final = _bars([110.0], start=date(2026, 1, 2))
    signals: Final = compute_signals("^GSPC", december + january)
    assert signals is not None
    assert signals.returns.year_to_date == pytest.approx(0.1)


def test_year_to_date_is_none_when_the_history_does_not_reach_last_year() -> None:
    signals: Final = compute_signals("^GSPC", _bars([100.0, 110.0], start=date(2026, 1, 2)))
    assert signals is not None
    assert signals.returns.year_to_date is None


def test_moving_average_distance_needs_the_full_window() -> None:
    short: Final = compute_signals("^GSPC", _bars([100.0] * 49))
    assert short is not None
    assert short.trend.from_50_day is None
    assert short.trend.from_200_day is None

    full: Final = compute_signals("^GSPC", _bars([100.0] * 49 + [110.0]))
    assert full is not None
    assert full.trend.from_50_day == round(110.0 / 100.2 - 1, 4)
    assert full.trend.from_200_day is None


def test_realised_volatility_needs_one_more_close_than_its_window() -> None:
    twenty: Final = compute_signals("^GSPC", _bars([100.0] * 20))
    assert twenty is not None
    assert twenty.realised_volatility_20d is None

    twenty_one: Final = compute_signals("^GSPC", _bars([100.0] * 21))
    assert twenty_one is not None
    assert twenty_one.realised_volatility_20d == pytest.approx(0.0)


def test_realised_volatility_is_none_when_no_change_can_be_measured() -> None:
    """A halted or unpriced instrument reports zero closes; a deviation of them means nothing."""
    signals: Final = compute_signals("^GSPC", _bars([0.0] * 21))
    assert signals is not None
    assert signals.realised_volatility_20d is None


def test_realised_volatility_is_annualised() -> None:
    """A series alternating by a fixed step has a known daily deviation, so the scaling is checkable."""
    closes: Final = [100.0 if index % 2 == 0 else 101.0 for index in range(21)]
    signals: Final = compute_signals("^GSPC", _bars(closes))
    assert signals is not None
    assert signals.realised_volatility_20d is not None
    assert signals.realised_volatility_20d > TRADING_DAYS_PER_YEAR**0.5 * 0.009


def test_volume_ratio_compares_the_latest_session_with_its_twenty_day_average() -> None:
    volumes: Final = [100] * 19 + [200]
    signals: Final = compute_signals("^GSPC", _bars([100.0] * 20, volumes))
    assert signals is not None
    assert signals.volume_vs_20_day == round(200 / 105, 4)


def test_volume_ratio_is_none_before_the_window_fills() -> None:
    signals: Final = compute_signals("^GSPC", _bars([100.0] * 19, [100] * 19))
    assert signals is not None
    assert signals.volume_vs_20_day is None


def test_drawdown_is_negative_below_the_high_and_zero_at_it() -> None:
    below: Final = compute_signals("^GSPC", _bars([100.0, 120.0, 90.0]))
    assert below is not None
    assert below.drawdown_from_52_week_high == pytest.approx(-0.25)

    at_high: Final = compute_signals("^GSPC", _bars([100.0, 90.0, 120.0]))
    assert at_high is not None
    assert at_high.drawdown_from_52_week_high == pytest.approx(0.0)


def test_breadth_counts_each_direction_and_ranks_both_ends() -> None:
    breadth: Final = compute_breadth({"AAA": 3.0, "BBB": -1.0, "CCC": 0.0, "DDD": 5.0}, count=2)
    assert (breadth.advancers, breadth.decliners, breadth.unchanged) == (2, 1, 1)
    assert tuple(entry.symbol for entry in breadth.top) == ("DDD", "AAA")
    assert tuple(entry.symbol for entry in breadth.bottom) == ("BBB", "CCC")


def test_breadth_of_nothing_is_empty_rather_than_an_error() -> None:
    breadth: Final = compute_breadth({})
    assert (breadth.advancers, breadth.decliners, breadth.unchanged) == (0, 0, 0)
    assert breadth.top == ()
    assert breadth.bottom == ()
