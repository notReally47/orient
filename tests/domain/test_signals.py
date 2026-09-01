"""Signal math is where a wrong number would reach the reader looking exactly like a right one.

The property under test throughout is that a window too short to compute honestly yields None
rather than a figure derived from whatever history happened to exist.
"""

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Final

import pytest

from orient.domain.models import Bar, Breadth
from orient.domain.signals import (
    REPORTS_REMEMBERED,
    TRADING_DAYS_PER_YEAR,
    compute_signals,
    reactions,
)

_START: Final = date(2026, 1, 5)


RATE_ROUNDING: Final = 5e-5


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
    assert signals.volume_multiple_20d == round(200 / 105, 2)


def test_volume_ratio_is_none_before_the_window_fills() -> None:
    signals: Final = compute_signals("^GSPC", _bars([100.0] * 19, [100] * 19))
    assert signals is not None
    assert signals.volume_multiple_20d is None


def test_drawdown_is_negative_below_the_high_and_zero_at_it() -> None:
    below: Final = compute_signals("^GSPC", _bars([100.0, 120.0, 90.0]))
    assert below is not None
    assert below.drawdown_from_52_week_high == pytest.approx(-0.25)

    at_high: Final = compute_signals("^GSPC", _bars([100.0, 90.0, 120.0]))
    assert at_high is not None
    assert at_high.drawdown_from_52_week_high == pytest.approx(0.0)


def test_the_years_range_is_where_the_price_reached_not_where_it_closed() -> None:
    """A live summary read "702.67% above its 52-week low of 114.25", two grounded figures that
    could not both be true: the percentage came off the lowest close and the level off the lowest
    trade. One series settles it, and the traded extremes are what a quote page states."""
    spiked: Final = (
        Bar(session_date=_START, open=100.0, high=140.0, low=80.0, close=100.0, volume=1),
        Bar(session_date=_START + timedelta(days=1), open=100.0, high=125.0, low=95.0, close=120.0, volume=1),
    )

    signals: Final = compute_signals("^GSPC", spiked)

    assert signals is not None
    assert (signals.high_52_week, signals.low_52_week) == (140.0, 80.0)
    assert signals.drawdown_from_52_week_high == pytest.approx(120.0 / 140.0 - 1, abs=RATE_ROUNDING)
    assert signals.above_52_week_low == pytest.approx(120.0 / 80.0 - 1)


def test_the_level_and_the_distance_measured_from_it_always_reconcile() -> None:
    """The pair travels together, so prose quoting both agrees with itself to the precision a rate
    is stored at. What it can no longer do is disagree by fourteen percentage points."""
    signals: Final = compute_signals("^GSPC", _bars([100.0, 150.0, 90.0, 132.0]))

    assert signals is not None
    assert signals.high_52_week is not None
    assert signals.low_52_week is not None
    assert signals.drawdown_from_52_week_high is not None
    assert signals.above_52_week_low is not None
    assert signals.high_52_week * (1 + signals.drawdown_from_52_week_high) == pytest.approx(
        signals.close, rel=RATE_ROUNDING
    )
    assert signals.low_52_week * (1 + signals.above_52_week_low) == pytest.approx(signals.close, rel=RATE_ROUNDING)


def test_a_move_that_was_over_at_the_open_is_measured_as_one() -> None:
    """Micron rose 2.48% having gapped 2.04%, and two summaries in a row called that a day of
    buying. The split was in front of the writer both times; the ratio says it in one figure."""
    gapped: Final = (
        Bar(session_date=_START, open=100.0, high=100.0, low=100.0, close=100.0, volume=1),
        Bar(session_date=_START + timedelta(days=1), open=102.04, high=103.0, low=102.0, close=102.48, volume=1),
    )

    signals: Final = compute_signals("MU", gapped)

    assert signals is not None
    assert signals.shape is not None
    assert signals.shape.gap_share_of_move == pytest.approx(0.82, abs=0.01)


def test_a_gap_the_session_gave_back_reads_above_one() -> None:
    """Opened 2% up, closed 0.5% up. The reader needs to know the day sold into the gap."""
    faded: Final = (
        Bar(session_date=_START, open=100.0, high=100.0, low=100.0, close=100.0, volume=1),
        Bar(session_date=_START + timedelta(days=1), open=102.0, high=102.5, low=100.0, close=100.5, volume=1),
    )

    signals: Final = compute_signals("MU", faded)

    assert signals is not None
    assert signals.shape is not None
    assert signals.shape.gap_share_of_move == pytest.approx(4.0)


def test_a_flat_session_has_no_share_to_report() -> None:
    """Dividing a whole gap by a net move of two basis points reports a share in the hundreds, and
    the two halves are worth reading on their own long before that."""
    flat: Final = (
        Bar(session_date=_START, open=100.0, high=100.0, low=100.0, close=100.0, volume=1),
        Bar(session_date=_START + timedelta(days=1), open=101.0, high=101.0, low=99.9, close=100.02, volume=1),
    )

    signals: Final = compute_signals("MU", flat)

    assert signals is not None
    assert signals.shape is not None
    assert signals.shape.gap is not None
    assert signals.shape.gap_share_of_move is None


def test_breadth_counts_each_direction_and_the_total_it_counted_from() -> None:
    """Counts and nothing else. Naming the strongest few restated the sector list beside it."""
    breadth: Final = Breadth.over({"AAA": 3.0, "BBB": -1.0, "CCC": 0.0, "DDD": 5.0})
    assert (breadth.advancers, breadth.decliners, breadth.unchanged) == (2, 1, 1)
    assert breadth.total == 4


def test_breadth_of_nothing_is_empty_rather_than_an_error() -> None:
    breadth: Final = Breadth.over({})
    assert (breadth.advancers, breadth.decliners, breadth.unchanged, breadth.total) == (0, 0, 0, 0)


def test_how_a_company_took_its_last_reports_is_measured_from_the_sessions_either_side() -> None:
    """The only earnings fact that is about the trade rather than about the business."""
    bars: Final = _bars([100.0, 100.0, 90.0, 90.0, 90.0, 99.0], start=date(2026, 3, 2))
    reported: Final = [date(2026, 3, 3), date(2026, 3, 6)]

    took: Final = reactions(reported, bars)

    assert [entry.reported_on for entry in took] == [date(2026, 3, 6), date(2026, 3, 3)]
    assert took[0].next_session_move == pytest.approx(0.1)
    assert took[1].next_session_move == pytest.approx(-0.1)


def test_a_report_with_no_session_after_it_is_skipped_rather_than_measured_against_a_gap() -> None:
    bars: Final = _bars([100.0, 101.0], start=date(2026, 3, 2))

    assert reactions([date(2026, 3, 30)], bars) == ()


def test_only_the_last_few_reports_are_remembered() -> None:
    """Enough to see a habit, not a history of the company."""
    bars: Final = _bars([100.0 + n for n in range(20)], start=date(2026, 3, 2))
    every = [date(2026, 3, 2) + timedelta(days=n) for n in range(1, 12)]

    assert len(reactions(every, bars)) == REPORTS_REMEMBERED


def _traded(closes: Sequence[float], span: float = 2.0) -> tuple[Bar, ...]:
    """Bars with a real high-low range, so the day has an inside to split."""
    return tuple(
        Bar(
            session_date=_START + timedelta(days=offset),
            open=close - span / 2,
            high=close + span,
            low=close - span,
            close=close,
            volume=1,
        )
        for offset, close in enumerate(closes)
    )


def test_a_session_with_a_range_splits_into_a_gap_and_the_move_during_it() -> None:
    measured: Final = compute_signals("X", _traded([100.0, 104.0]))
    assert measured is not None
    shape: Final = measured.shape

    assert shape is not None
    assert shape.gap is not None
    assert shape.intraday is not None
    assert shape.gap_share_of_move is not None
    assert shape.close_location is not None


def test_an_instrument_that_prices_once_a_day_has_no_split_to_report() -> None:
    """A mutual fund's bar is a net asset value: open, high, low and close are one number. Divided
    anyway it reports a gap share of exactly 1.0, which reads as a move that was over before an
    open the fund does not have, and refuses every summary that does not say so."""
    measured: Final = compute_signals("X", _bars([100.0, 104.0]))
    assert measured is not None
    shape: Final = measured.shape

    assert shape is not None
    assert shape.gap is None
    assert shape.intraday is None
    assert shape.gap_share_of_move is None
    assert shape.close_location is None
