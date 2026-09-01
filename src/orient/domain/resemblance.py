"""A session as a vector, so "when did this last look like this" is a question about the data.

The claims index matches on phrasing, which is a different question: two sessions that measured
alike need not have been written about alike. Every feature here is scale-free, so a fifty-dollar
stock and a twenty-thousand-point index occupy the same space and a match across them means
something. No model call, at write time or at query time.

Squashed rather than clipped, because a name 700% above its year low and one 40% above it are
both simply far above it and the first would otherwise dominate every distance it appears in.
"""

from collections.abc import Mapping, Sequence
from math import tanh
from typing import Final

from orient.domain.models import Signals

FEATURES: Final = (
    "one_day",
    "one_week",
    "one_month",
    "three_month",
    "from_50_day",
    "from_200_day",
    "two_hundred_day_slope",
    "realised_volatility",
    "volume_multiple",
    "drawdown",
    "above_low",
    "gap",
    "intraday",
    "close_location",
    "up_down_volume",
    "excess_over_benchmark",
    "excess_over_peer",
    "vix",
    "curve",
    "credit",
    "breadth",
)
DIMENSIONS: Final = len(FEATURES)

_SCALE: Final[Mapping[str, float]] = {
    "one_day": 0.03,
    "one_week": 0.06,
    "one_month": 0.12,
    "three_month": 0.20,
    "from_50_day": 0.10,
    "from_200_day": 0.30,
    "two_hundred_day_slope": 0.10,
    "realised_volatility": 0.40,
    "volume_multiple": 0.60,
    "drawdown": 0.25,
    "above_low": 1.00,
    "gap": 0.02,
    "intraday": 0.03,
    "close_location": 0.50,
    "up_down_volume": 0.30,
    "excess_over_benchmark": 0.02,
    "excess_over_peer": 0.02,
    "vix": 10.0,
    "curve": 1.00,
    "credit": 2.00,
    "breadth": 0.50,
}


def _squash(reading: float | None, scale: float) -> float:
    """None reads as ordinary rather than as extreme, which is the safe direction for a distance."""
    return 0.0 if reading is None else tanh(reading / scale)


def _raw(signals: Signals) -> Mapping[str, float | None]:
    """Each feature centred on what an unremarkable session looks like, so zero means typical."""
    shape: Final = signals.shape
    relative: Final = signals.relative
    cross: Final = signals.cross_asset
    breadth: Final = signals.breadth
    return {
        "one_day": signals.returns.one_day,
        "one_week": signals.returns.one_week,
        "one_month": signals.returns.one_month,
        "three_month": signals.returns.three_month,
        "from_50_day": signals.trend.from_50_day,
        "from_200_day": signals.trend.from_200_day,
        "two_hundred_day_slope": signals.trend.two_hundred_day_slope,
        "realised_volatility": signals.realised_volatility_20d,
        "volume_multiple": None if signals.volume_multiple_20d is None else signals.volume_multiple_20d - 1.0,
        "drawdown": signals.drawdown_from_52_week_high,
        "above_low": signals.above_52_week_low,
        "gap": None if shape is None else shape.gap,
        "intraday": None if shape is None else shape.intraday,
        "close_location": None if shape is None or shape.close_location is None else shape.close_location - 0.5,
        "up_down_volume": None if shape is None or shape.up_down_volume_60d is None else shape.up_down_volume_60d - 1.0,
        "excess_over_benchmark": None if relative is None else relative.excess_over_benchmark,
        "excess_over_peer": None if relative is None else relative.excess_over_peer,
        "vix": None if cross is None or cross.vix is None else cross.vix - 20.0,
        "curve": None if cross is None else cross.spread_10s2s,
        "credit": None if cross is None or cross.high_yield_spread is None else cross.high_yield_spread - 3.5,
        "breadth": None if breadth is None or not breadth.total else breadth.advancers / breadth.total - 0.5,
    }


def vector(signals: Signals) -> tuple[float, ...]:
    readings: Final = _raw(signals)
    return tuple(round(_squash(readings[name], _SCALE[name]), 6) for name in FEATURES)


def described(one: Sequence[float], other: Sequence[float], most: int = 3) -> tuple[str, ...]:
    """Which features two sessions agree on most closely, so a match can say why it matched."""
    apart: Final = sorted(
        ((abs(a - b), name) for a, b, name in zip(one, other, FEATURES, strict=True)),
        key=lambda pair: pair[0],
    )
    return tuple(name for _, name in apart[:most])
