"""Signal math. Pure functions over price history: no network, no clock, no configuration.

Every window yields None rather than a partial figure when the history is too short. A summary
quoting a "200-day average" computed from forty days is worse than one that omits the line,
because the reader cannot tell the difference and the judge cannot catch it.
"""

from collections.abc import Sequence
from datetime import date
from itertools import pairwise
from math import sqrt
from statistics import fmean, stdev
from typing import Final

from orient.domain.market import EarningsReaction
from orient.domain.models import (
    Bar,
    Breadth,
    CrossAsset,
    Relative,
    Returns,
    SectorMove,
    SessionShape,
    Signals,
    TrendDistance,
)

ONE_WEEK: Final = 5
ONE_MONTH: Final = 21
THREE_MONTHS: Final = 63
ONE_YEAR: Final = 252
VOLATILITY_WINDOW: Final = 20
VOLUME_WINDOW: Final = 20
TRADING_DAYS_PER_YEAR: Final = 252
MINIMUM_FOR_DEVIATION: Final = 2
SLOPE_WINDOW: Final = 21
REPORTS_REMEMBERED: Final = 4
PRESSURE_WINDOW: Final = 60
FLAT_SESSION: Final = 0.0025


def _change(earlier: float, later: float) -> float | None:
    return None if earlier == 0 else later / earlier - 1


def _return_over(closes: Sequence[float], lookback: int) -> float | None:
    if len(closes) <= lookback:
        return None
    return _change(closes[-1 - lookback], closes[-1])


def _year_to_date(bars: Sequence[Bar]) -> float | None:
    """Measured from the final close of the previous year, the convention every data vendor uses."""
    current_year: Final = bars[-1].session_date.year
    prior: Final = tuple(bar for bar in bars if bar.session_date.year < current_year)
    if not prior:
        return None
    return _change(prior[-1].close, bars[-1].close)


def _distance_from_average(closes: Sequence[float], window: int) -> float | None:
    if len(closes) < window:
        return None
    return _change(fmean(closes[-window:]), closes[-1])


def _realised_volatility(closes: Sequence[float]) -> float | None:
    """Annualised standard deviation of daily returns, the figure quoted as "20-day vol"."""
    if len(closes) < VOLATILITY_WINDOW + 1:
        return None
    recent: Final = closes[-(VOLATILITY_WINDOW + 1) :]
    changes: Final = tuple(
        change for earlier, later in pairwise(recent) if (change := _change(earlier, later)) is not None
    )
    if len(changes) < MINIMUM_FOR_DEVIATION:
        return None
    return stdev(changes) * sqrt(TRADING_DAYS_PER_YEAR)


def _volume_ratio(volumes: Sequence[int]) -> float | None:
    if len(volumes) < VOLUME_WINDOW:
        return None
    average: Final = fmean(volumes[-VOLUME_WINDOW:])
    return None if average == 0 else round(volumes[-1] / average, 2)


def _extremes(bars: Sequence[Bar]) -> tuple[float, float]:
    """The highest and lowest the price actually reached in the year, not the highest and lowest
    it happened to close.

    Every quote page states the 52-week range this way, so measuring the distances off closes gave
    a reader two figures that could not both be true: a low of 114.25 quoted from the profile and
    a rise of 702.67% measured from a different number entirely. The percentages and the levels now
    come from one series, and the level travels beside the percentage so they cannot drift apart.
    """
    window: Final = bars[-ONE_YEAR:]
    return max(bar.high for bar in window), min(bar.low for bar in window)


def _average_slope(closes: Sequence[float], window: int, over: int = SLOPE_WINDOW) -> float | None:
    """How far the moving average itself has moved, which is the direction the distance lacks."""
    if len(closes) < window + over:
        return None
    now: Final = fmean(closes[-window:])
    before: Final = fmean(closes[-window - over : -over])
    return _change(before, now)


def _shape(bars: Sequence[Bar]) -> SessionShape | None:
    """Where the move happened inside the day, and which side the quarter's volume was on.

    An instrument that prices once a day has no inside to its day: open, high, low and close are
    the same number, so splitting the move into a gap and a session divides a session that never
    happened. Every mutual fund otherwise reports a gap share of exactly 1.0, which reads as a
    move that was over before the open and refuses any summary that does not say so.
    """
    if len(bars) < MINIMUM_FOR_DEVIATION:
        return None
    last: Final = bars[-1]
    span: Final = last.high - last.low
    traded: Final = span > 0
    gap: Final = _change(bars[-2].close, last.open) if traded else None
    net: Final = _change(bars[-2].close, last.close)
    return SessionShape(
        gap=gap,
        intraday=_change(last.open, last.close) if traded else None,
        gap_share_of_move=_gap_share(gap, net),
        close_location=round((last.close - last.low) / span, 4) if traded else None,
        range_percent=_change(last.low, last.high),
        up_down_volume_60d=_pressure(bars),
    )


def _gap_share(gap: float | None, net: float | None) -> float | None:
    """How much of the day's move had already happened before the open.

    Undefined on a session that finished where it started, and unstable just either side of that:
    a move of two basis points puts a whole gap over a divisor near zero and reports a share in the
    hundreds. Below the floor the two halves are worth reading on their own and the ratio is not.
    """
    if gap is None or net is None or abs(net) < FLAT_SESSION:
        return None
    return round(gap / net, 2)


def _pressure(bars: Sequence[Bar]) -> float | None:
    """Volume on rising days over volume on falling days: above one is buying, below is selling.

    A total tells you how much traded, never which way it leaned. Instruments the vendor reports
    no volume for — currency pairs, chiefly — come back None rather than one.
    """
    recent: Final = bars[-(PRESSURE_WINDOW + 1) :]
    if len(recent) < PRESSURE_WINDOW + 1:
        return None
    up: Final[list[int]] = []
    down: Final[list[int]] = []
    for earlier, later in pairwise(recent):
        if later.close > earlier.close:
            up.append(later.volume)
        elif later.close < earlier.close:
            down.append(later.volume)
    if not up or not down:
        return None
    falling: Final = fmean(down)
    return None if falling == 0 else round(fmean(up) / falling, 2)


def compare(
    session_return: float | None,
    benchmark: tuple[str, float | None] | None = None,
    peer: tuple[str, str | None, float | None] | None = None,
) -> Relative | None:
    """The session's move beside the same session's move in what it trades with.

    Each side degrades on its own: a benchmark that could not be measured costs the benchmark
    comparison and leaves the peer one standing.
    """
    if session_return is None or (benchmark is None and peer is None):
        return None
    symbol, market = benchmark if benchmark else (None, None)
    peer_symbol, peer_name, peer_move = peer if peer else (None, None, None)
    relative: Final = Relative(
        benchmark=symbol,
        benchmark_return=market,
        excess_over_benchmark=None if market is None else session_return - market,
        peer=peer_symbol,
        peer_name=peer_name,
        peer_return=peer_move,
        excess_over_peer=None if peer_move is None else session_return - peer_move,
    )
    return relative if relative.excess_over_benchmark is not None or relative.excess_over_peer is not None else None


def compute_signals(
    symbol: str,
    bars: Sequence[Bar],
    breadth: Breadth | None = None,
    sectors: Sequence[SectorMove] = (),
    sector_market: str | None = None,
    cross_asset: CrossAsset | None = None,
    relative: Relative | None = None,
) -> Signals | None:
    """None when there is no history at all; every individual figure degrades to None on its own."""
    if not bars:
        return None

    ordered: Final = tuple(sorted(bars, key=lambda bar: bar.session_date))
    closes: Final = tuple(bar.close for bar in ordered)
    volumes: Final = tuple(bar.volume for bar in ordered)
    high, low = _extremes(ordered)

    return Signals(
        symbol=symbol,
        session_date=ordered[-1].session_date,
        close=closes[-1],
        returns=Returns(
            one_day=_return_over(closes, 1),
            one_week=_return_over(closes, ONE_WEEK),
            one_month=_return_over(closes, ONE_MONTH),
            three_month=_return_over(closes, THREE_MONTHS),
            year_to_date=_year_to_date(ordered),
        ),
        trend=TrendDistance(
            from_50_day=_distance_from_average(closes, 50),
            from_200_day=_distance_from_average(closes, 200),
            two_hundred_day_slope=_average_slope(closes, 200),
        ),
        realised_volatility_20d=_realised_volatility(closes),
        volume_multiple_20d=_volume_ratio(volumes),
        high_52_week=high,
        low_52_week=low,
        drawdown_from_52_week_high=_change(high, closes[-1]),
        above_52_week_low=_change(low, closes[-1]),
        shape=_shape(ordered),
        relative=relative,
        breadth=breadth,
        sectors=tuple(sectors),
        sector_market=sector_market,
        cross_asset=cross_asset,
    )


def reactions(
    reported: Sequence[date], bars: Sequence[Bar], most_recent: int = REPORTS_REMEMBERED
) -> tuple[EarningsReaction, ...]:
    """How the shares moved the session after each of the last few reports.

    Measured from the close on or before the report to the next close after it, which is where a
    result lands whether it was published before the open or after the bell. A report with no
    session on one side of it is skipped rather than measured against a gap.
    """
    closes: Final[dict[date, float]] = {bar.session_date: bar.close for bar in bars}
    ordered: Final[list[date]] = sorted(closes)
    found: Final[list[EarningsReaction]] = []
    for when in sorted(reported, reverse=True):
        before = [day for day in ordered if day <= when]
        after = [day for day in ordered if day > when]
        if not before or not after:
            continue
        move = _change(closes[before[-1]], closes[after[0]])
        if move is not None:
            found.append(EarningsReaction(reported_on=when, next_session_move=move))
        if len(found) == most_recent:
            break
    return tuple(found)
