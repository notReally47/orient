"""The grounding check is what makes "numbers never pass through a model" mean anything.

The cases that matter are the two failure directions: a real figure that gets flagged makes the
revise loop fight the writer over nothing, and an invented figure that passes is the exact bug the
whole design exists to prevent.
"""

from collections.abc import Mapping
from datetime import date
from typing import Final

import pytest

from orient.domain.grounding import Grounded, Ungrounded, check, measured

SESSION: Final = date(2026, 8, 13)

SIGNALS: Final[Mapping[str, object]] = {
    "symbol": "^GSPC",
    "session_date": "2026-08-13",
    "close": 6412.37,
    "returns": {"one_day": -0.008, "one_week": 0.0123, "one_month": None},
    "trend": {"from_50_day": 0.0341, "from_200_day": 0.1102},
    "realised_volatility_20d": 0.1184,
    "volume_multiple_20d": 2.23,
    "cross_asset": {"vix": 18.34, "yield_10y": 4.21, "yield_2y": 3.77},
}

PROFILE: Final[Mapping[str, object]] = {
    "symbol": "^GSPC",
    "name": "S&P 500",
    "market_cap": 3_450_000_000_000,
}


def _verdict(prose: str, evidence: tuple[Mapping[str, object], ...] = (SIGNALS, PROFILE)) -> object:
    return check(prose, measured(evidence), SESSION)


@pytest.mark.parametrize(
    ("quoted", "why"),
    [
        ("The index closed at 6,412.37.", "a close, thousands separated"),
        ("It fell 0.8% on the day.", "a fraction quoted as a percent"),
        ("It fell 0.80% on the day.", "the same figure at another precision"),
        ("The VIX rose to 18.", "a level rounded down to the unit"),
        ("The VIX sat at 18.3.", "the same level at one decimal"),
        ("Volume ran at 2.2x its average.", "a ratio"),
        ("It sits 3.4% above its 50 day average.", "a trend distance, and a window length"),
        ("The 10 year yields 4.21% against 3.77% at 2 years.", "two yields and two window lengths"),
        ("Realised volatility is 11.8%.", "an annualised figure"),
        ("The S&P 500 rose.", "a numeral inside an instrument name"),
        ("A market cap near 3.45 trillion.", "a large figure quoted in trillions"),
        ("It has not been here since 2025.", "a year adjacent to the session"),
        ("It is 11% above its 200 day average.", "a trend distance and the other window"),
    ],
)
def test_a_measured_figure_is_grounded(quoted: str, why: str) -> None:
    del why
    assert isinstance(_verdict(quoted), Grounded)


@pytest.mark.parametrize(
    "invented",
    [
        "It fell 1.93% on the day.",
        "The index closed at 6,388.14.",
        "The VIX rose to 27.6.",
        "Breadth was 180 advancers to 320 decliners.",
    ],
)
def test_an_invented_figure_is_caught_and_named(invented: str) -> None:
    verdict: Final = _verdict(invented)
    assert isinstance(verdict, Ungrounded)
    assert verdict.figures


def test_the_verdict_names_every_unmatched_figure_so_a_revise_can_act() -> None:
    verdict: Final = _verdict("It fell 1.93% while the VIX reached 27.6.")
    assert isinstance(verdict, Ungrounded)
    assert set(verdict.figures) == {"1.93", "27.6"}


def test_a_figure_repeated_is_reported_once() -> None:
    verdict: Final = _verdict("It fell 1.93%, and that 1.93% was the worst of the week.")
    assert isinstance(verdict, Ungrounded)
    assert verdict.figures == ("1.93",)


def test_prose_with_no_figures_is_grounded() -> None:
    assert isinstance(_verdict("The index fell, and its sector peers fell with it."), Grounded)


def test_a_news_figure_is_not_grounded_because_news_is_not_evidence() -> None:
    """An article's numbers reached the prompt but nobody measured them, so quoting one must fail."""
    article: Final[Mapping[str, object]] = {
        "articles": [{"title": "Chipmakers slide 4.7% as orders slow", "url": "https://example.test/a"}]
    }
    assert isinstance(check("Chipmakers slid 4.7%.", measured((SIGNALS, article)), SESSION), Grounded)
    assert isinstance(_verdict("Chipmakers slid 4.7%."), Ungrounded)


def test_a_null_signal_grounds_nothing() -> None:
    """A window too short to compute comes back null, and null is not zero."""
    verdict: Final = _verdict("It is up 4.4% over the month.")
    assert isinstance(verdict, Ungrounded)


def test_evidence_with_nothing_in_it_still_admits_structure() -> None:
    verdict: Final = check("It sits above its 200 day average, the first time since 2025.", frozenset(), SESSION)
    assert isinstance(verdict, Grounded)


def test_a_comma_ending_a_clause_is_not_part_of_the_figure() -> None:
    """A live refusal reported the unmatched figure as "16," because the digit class swallowed
    the comma after "August 16". A thousands separator sits between digits, never after them."""
    verdict: Final = check("On Sunday, August 16, South Korea reports.", frozenset(), date(2026, 8, 13))

    assert isinstance(verdict, Ungrounded)
    assert verdict.figures == ("16",)


def test_a_thousands_separator_inside_a_figure_still_reads_as_one_number() -> None:
    allowed: Final = measured([{"close": 7798.99, "volume": 1234}])

    assert isinstance(check("It closed at 7,798.99 on volume of 1,234.", allowed, date(2026, 8, 13)), Grounded)


def test_a_window_named_in_a_field_may_be_written_out() -> None:
    """`up_down_volume_60d` cannot be described without saying sixty, and a check that refuses it
    sends the writer back to fix a sentence whose only fault is naming its own window."""
    verdict: Final = check(
        "Volume leaned to the buyers over the last 60 sessions.",
        measured(({"up_down_volume_60d": 1.03},)),
        SESSION,
    )

    assert isinstance(verdict, Grounded)
