"""Signal math. Pure functions over price history: no network, no clock, no configuration.

Every window yields None rather than a partial figure when the history is too short. A summary
quoting a "200-day average" computed from forty days is worse than one that omits the line,
because the reader cannot tell the difference and the judge cannot catch it.
"""

from collections.abc import Mapping, Sequence
from itertools import pairwise
from math import sqrt
from statistics import fmean, stdev
from typing import Final

from orient.domain.models import (
    Bar,
    Breadth,
    Contributor,
    CrossAsset,
    Returns,
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
CONTRIBUTOR_COUNT: Final = 5
MINIMUM_FOR_DEVIATION: Final = 2


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
    return None if average == 0 else volumes[-1] / average


def _drawdown_from_high(closes: Sequence[float]) -> float | None:
    high: Final = max(closes[-ONE_YEAR:])
    return _change(high, closes[-1])


def compute_signals(
    symbol: str,
    bars: Sequence[Bar],
    breadth: Breadth | None = None,
    cross_asset: CrossAsset | None = None,
) -> Signals | None:
    """None when there is no history at all; every individual figure degrades to None on its own."""
    if not bars:
        return None

    ordered: Final = tuple(sorted(bars, key=lambda bar: bar.session_date))
    closes: Final = tuple(bar.close for bar in ordered)
    volumes: Final = tuple(bar.volume for bar in ordered)

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
        ),
        realised_volatility_20d=_realised_volatility(closes),
        volume_vs_20_day=_volume_ratio(volumes),
        drawdown_from_52_week_high=_drawdown_from_high(closes),
        breadth=breadth,
        cross_asset=cross_asset,
    )


def compute_breadth(contributions: Mapping[str, float], count: int = CONTRIBUTOR_COUNT) -> Breadth:
    """`contributions` maps a constituent to its share of the index move, already weighted."""
    ranked: Final = tuple(sorted(contributions.items(), key=lambda item: item[1], reverse=True))
    return Breadth(
        advancers=sum(1 for _, value in ranked if value > 0),
        decliners=sum(1 for _, value in ranked if value < 0),
        unchanged=sum(1 for _, value in ranked if value == 0),
        top=tuple(Contributor(symbol=symbol, contribution=value) for symbol, value in ranked[:count]),
        bottom=tuple(Contributor(symbol=symbol, contribution=value) for symbol, value in reversed(ranked[-count:])),
    )
