"""Citing a measurement instead of typing it.

Every formatting rule the writing skill used to carry existed because the model transcribed
numbers by hand. These check that the transcription is gone and that the formatting it used to
get wrong is now decided once.
"""

from datetime import date
from typing import Final

from orient.domain import figures
from orient.domain.figures import Figure
from orient.domain.models import CrossAsset, Relative, Returns, SessionShape, Signals, TrendDistance

SESSION: Final = date(2026, 8, 26)


def _signals(close: float = 938.4, **overrides: object) -> Signals:
    base: Final[dict[str, object]] = {
        "symbol": "MU",
        "session_date": SESSION,
        "close": close,
        "returns": Returns(one_day=0.0058, year_to_date=2.2708),
        "trend": TrendDistance(from_200_day=0.6144),
        "realised_volatility_20d": 0.8707,
        "volume_multiple_20d": 0.51,
        "high_52_week": 1254.81,
        "low_52_week": 114.07,
        "drawdown_from_52_week_high": -0.2522,
        "shape": SessionShape(gap=-0.0077, intraday=0.0137, close_location=0.6525),
        "relative": Relative(benchmark="SPY", excess_over_benchmark=0.0026),
        "cross_asset": CrossAsset(vix=15.21),
    }
    return Signals.model_validate({**base, **overrides})


def _said(prose: str, close: float = 938.4, **overrides: object) -> str:
    return figures.render(prose, figures.addressable(_signals(close, **overrides)))


def test_a_cited_figure_is_the_measurement_rather_than_whatever_was_typed() -> None:
    assert _said("closed at {{close}}") == "closed at 938.40"


def test_a_rate_is_written_as_a_signed_percentage_and_never_as_its_fraction() -> None:
    """A live summary read "0.1052, or 10.52%" throughout, hedging against the check by printing
    both. There is nothing to hedge against when the renderer decides."""
    assert _said("{{year_to_date}} this year") == "+227.08% this year"
    assert "0.0058" not in _said("{{one_day}}")


def test_a_multiple_is_not_a_percentage() -> None:
    """0.51 written as "51%" reads as a move of that size, which turns a quiet day into a rout."""
    assert _said("volume was {{volume_multiple_20d}}") == "volume was 0.51x"


def test_a_ratio_is_neither() -> None:
    assert _said("volume leaned {{up_down_volume_60d}}", shape=SessionShape(up_down_volume_60d=0.89)) == (
        "volume leaned 0.89"
    )


def test_a_position_in_the_days_range_reads_as_a_share_of_it() -> None:
    """The panel called it 63% and the prose called it 0.63, which is one measurement written two
    ways on the same page."""
    assert _said("finished {{close_location}} up its range") == "finished 65% up its range"


def test_a_yield_is_already_a_percentage_and_says_so() -> None:
    """4.67 means 4.67%, not 467%, and the backdrop panel had been the only place that said so."""
    assert _said("the ten-year at {{yield_10y}}", cross_asset=CrossAsset(yield_10y=4.67)) == "the ten-year at 4.67%"


def test_a_figure_the_sentence_already_gives_direction_to_is_written_unsigned() -> None:
    """ "-25.22% below its high" says the opposite of what it means."""
    assert _said("{{drawdown_from_52_week_high}} below its high") == "25.22% below its high"


def test_a_nested_measurement_answers_to_its_path_and_to_its_own_name() -> None:
    """The writer reads `shape.gap` out of a tool result and should not have to remember which."""
    assert _said("{{shape.gap}}") == _said("{{gap}}") == "-0.77%"


def test_a_price_is_written_at_the_precision_this_instrument_is_quoted_to() -> None:
    """Magnitude cannot decide this: a currency pair at 1.17324 and a fifty-dollar stock sit in the
    same band and want five decimals and two."""
    assert _said("{{high_52_week}}", close=46.83, high_52_week=52.33770751953125) == "52.34"
    assert _said("{{high_52_week}}", close=1.17324, high_52_week=1.19881) == "1.19881"
    assert _said("{{close}}", close=1.17324) == "1.17324"


def test_a_name_nothing_measured_is_reported_rather_than_rendered() -> None:
    known: Final = figures.addressable(_signals())

    assert figures.unknown("{{close}} and {{sector_retrun}}", known) == ("sector_retrun",)


def test_an_unresolved_name_is_left_alone_rather_than_blanked() -> None:
    """A summary stored against measurements that have since changed still has to read."""
    assert _said("{{nothing_measured_this}}") == "{{nothing_measured_this}}"


def test_every_measurement_in_the_session_is_addressable() -> None:
    """A figure the writer cannot name is a figure it will type by hand instead."""
    known: Final = figures.addressable(_signals())

    for name in ("close", "one_day", "year_to_date", "from_200_day", "volume_multiple_20d", "gap", "vix"):
        assert name in known, name


def test_a_measurement_that_is_null_is_not_addressable() -> None:
    """Null means unmeasurable. Rendering it as zero would be inventing a figure."""
    assert "one_week" not in figures.addressable(_signals())


def test_the_unit_comes_from_the_type_rather_than_from_a_list_of_names() -> None:
    """`Rate`, `Level` and `Share` tag themselves, so a measurement added tomorrow formats
    correctly without anyone remembering to register it."""
    known: Final = figures.addressable(_signals())

    assert known["close"].shown == "level"
    assert known["one_day"].shown == "change"
    assert known["excess_over_benchmark"].shown == "change"


def test_writing_a_figure_needs_no_session_around_it() -> None:
    assert figures.written(Figure(0.0065, "change")) == "+0.65%"
    assert figures.written(Figure(15.21, "level")) == "15.21"


def test_a_sign_can_be_dropped_where_the_sentence_already_gives_direction() -> None:
    """ "+21.51% above its low" has the direction twice. Signed stays the default, because losing
    one silently is worse than an extra character."""
    assert _said("{{above_52_week_low}}", above_52_week_low=0.2151) == "+21.51%"
    assert _said("{{above_52_week_low:plain}} above its low", above_52_week_low=0.2151) == "21.51% above its low"


def test_dropping_the_sign_does_nothing_to_a_figure_that_never_had_one() -> None:
    assert _said("{{close:plain}}") == _said("{{close}}") == "938.40"
    assert _said("{{volume_multiple_20d:plain}}") == "0.51x"
