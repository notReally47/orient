"""A session as a vector, and whether the distances between them mean anything.

The knowledge bank could already find summaries that read alike. This is meant to find sessions
that measured alike, which is a different question and the one a reader has.
"""

from datetime import date
from math import dist
from typing import Final

from orient.domain import resemblance
from orient.domain.models import Breadth, CrossAsset, Returns, SessionShape, Signals, TrendDistance

SESSION: Final = date(2026, 8, 26)


def _signals(symbol: str = "MU", close: float = 938.4, **overrides: object) -> Signals:
    base: Final[dict[str, object]] = {
        "symbol": symbol,
        "session_date": SESSION,
        "close": close,
        "returns": Returns(one_day=0.0058, one_week=-0.0083, one_month=0.0364),
        "trend": TrendDistance(from_50_day=-0.03, from_200_day=0.6144),
        "realised_volatility_20d": 0.8707,
        "volume_multiple_20d": 0.51,
        "shape": SessionShape(gap=-0.0077, intraday=0.0137, close_location=0.6525),
        "cross_asset": CrossAsset(vix=15.21),
    }
    return Signals.model_validate({**base, **overrides})


def test_a_session_is_the_same_length_whatever_was_measurable() -> None:
    """A vector column has a fixed width, so a sparse session cannot produce a short one."""
    sparse: Final = Signals(symbol="X", session_date=SESSION, close=1.0, returns=Returns(), trend=TrendDistance())

    assert len(resemblance.vector(sparse)) == resemblance.DIMENSIONS
    assert len(resemblance.vector(_signals())) == resemblance.DIMENSIONS


def test_a_measurement_nobody_took_reads_as_ordinary_rather_than_extreme() -> None:
    """Zero is the centre of every feature, so a missing one pulls a distance toward typical
    instead of inventing an outlier."""
    sparse: Final = Signals(symbol="X", session_date=SESSION, close=1.0, returns=Returns(), trend=TrendDistance())

    assert resemblance.vector(sparse) == (0.0,) * resemblance.DIMENSIONS


def test_two_instruments_of_wildly_different_price_can_still_match() -> None:
    """The whole point of a scale-free vector. A fifty-dollar stock and a twenty-thousand-point
    index that behaved identically must land in the same place."""
    cheap: Final = resemblance.vector(_signals("DVN", close=46.83))
    dear: Final = resemblance.vector(_signals("^NSEI", close=24207.75))

    assert cheap == dear


def test_a_violent_session_is_far_from_a_quiet_one() -> None:
    quiet: Final = resemblance.vector(_signals(returns=Returns(one_day=0.001), realised_volatility_20d=0.10))
    violent: Final = resemblance.vector(_signals(returns=Returns(one_day=-0.09), realised_volatility_20d=1.40))
    other_quiet: Final = resemblance.vector(_signals(returns=Returns(one_day=0.002), realised_volatility_20d=0.12))

    assert dist(quiet, other_quiet) < dist(quiet, violent)


def test_an_extreme_reading_cannot_swamp_every_other_feature() -> None:
    """A name 700% above its year low and one 40% above it are both simply far above it. Without a
    squash the first would dominate every distance it ever appeared in."""
    far: Final = resemblance.vector(_signals(above_52_week_low=7.2267))
    farther: Final = resemblance.vector(_signals(above_52_week_low=40.0))

    assert dist(far, farther) < 0.1
    assert all(abs(reading) <= 1.0 for reading in far)


def test_a_gap_that_reversed_reads_differently_from_one_that_held() -> None:
    """The measurement three live summaries walked past. It has to move the vector."""
    reversed_out: Final = resemblance.vector(_signals(shape=SessionShape(gap=-0.0077, intraday=0.0137)))
    held: Final = resemblance.vector(_signals(shape=SessionShape(gap=0.0204, intraday=0.0043)))

    assert dist(reversed_out, held) > 0.5


def test_a_match_can_say_which_features_it_matched_on() -> None:
    """A nearest neighbour with no explanation is a number a reader has to take on faith."""
    here: Final = resemblance.vector(_signals(breadth=Breadth(advancers=6, decliners=4, unchanged=1, total=11)))
    there: Final = resemblance.vector(_signals(breadth=Breadth(advancers=6, decliners=4, unchanged=1, total=11)))

    agreed: Final = resemblance.described(here, there)

    assert len(agreed) == 3
    assert set(agreed) <= set(resemblance.FEATURES)


def test_every_feature_actually_moves_the_vector() -> None:
    """A feature squashed by the wrong scale is either always zero or always saturated, and both
    make it invisible to the distance. This catches one added without a scale."""
    flat: Final = Signals(symbol="X", session_date=SESSION, close=1.0, returns=Returns(), trend=TrendDistance())
    baseline: Final = resemblance.vector(flat)

    moved: Final = resemblance.vector(
        flat.model_copy(
            update={
                "returns": Returns(one_day=0.05, one_week=0.08, one_month=0.15, three_month=0.25),
                "trend": TrendDistance(from_50_day=0.12, from_200_day=0.35, two_hundred_day_slope=0.12),
                "realised_volatility_20d": 0.5,
                "volume_multiple_20d": 2.0,
                "drawdown_from_52_week_high": -0.3,
                "above_52_week_low": 1.2,
                "shape": SessionShape(gap=0.03, intraday=0.04, close_location=0.95, up_down_volume_60d=1.4),
                "cross_asset": CrossAsset(vix=35.0, yield_10y=5.2, yield_2y=4.0, high_yield_spread=6.0),
                "breadth": Breadth(advancers=11, decliners=0, unchanged=0, total=11),
            }
        )
    )

    unmoved: Final = tuple(
        name for name, before, after in zip(resemblance.FEATURES, baseline, moved, strict=True) if before == after
    )
    assert unmoved == ("excess_over_benchmark", "excess_over_peer"), unmoved
