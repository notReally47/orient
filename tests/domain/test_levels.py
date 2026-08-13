"""Word budgets. Advanced being the shortest is a deliberate rule, not an oversight."""

from typing import Final, get_args

from orient.domain.levels import WORD_BUDGETS
from orient.domain.models import ReadingLevel


def test_every_reading_level_has_a_budget() -> None:
    assert set(WORD_BUDGETS) == set(get_args(ReadingLevel))


def test_advanced_is_never_longer_than_beginner() -> None:
    assert WORD_BUDGETS["advanced"].maximum <= WORD_BUDGETS["beginner"].minimum


def test_a_budget_includes_both_of_its_bounds() -> None:
    budget: Final = WORD_BUDGETS["beginner"]
    assert budget.holds(budget.minimum)
    assert budget.holds(budget.maximum)
    assert not budget.holds(budget.minimum - 1)
    assert not budget.holds(budget.maximum + 1)
