"""FRED publishes a row for every calendar date in range, marking non-publication days NaN.

Passing those through would put NaN into a signal and then into prose, so dropping them is the
provider's real work and is what these tests pin.
"""

from collections.abc import Callable
from datetime import date
from typing import Final

import pytest
from pydantic import ValidationError

from orient.providers._untyped import Records
from orient.providers.fred import FredProvider

_START: Final = date(2026, 8, 1)
_END: Final = date(2026, 8, 31)


def _fetch(records: Records) -> Callable[[str, date, date], Records]:
    def fetch(series_id: str, start: date, end: date) -> Records:
        del series_id, start, end
        return records

    return fetch


def _record(day: int, value: object) -> dict[str, object]:
    return {"observation_date": date(2026, 8, day), "value": value}


def test_not_a_number_rows_are_dropped() -> None:
    provider: Final = FredProvider(_fetch((_record(3, 4.2), _record(4, float("nan")), _record(5, 4.3))))
    observations: Final = provider.observations("DGS10", _START, _END)
    assert tuple(entry.observation_date.day for entry in observations) == (3, 5)


def test_null_rows_are_dropped() -> None:
    provider: Final = FredProvider(_fetch((_record(3, 4.2), _record(4, None))))
    assert len(provider.observations("DGS10", _START, _END)) == 1


def test_a_series_of_only_missing_values_is_empty_rather_than_an_error() -> None:
    provider: Final = FredProvider(_fetch((_record(3, float("nan")), _record(4, None))))
    assert provider.observations("DGS10", _START, _END) == ()


def test_published_values_survive_with_their_dates() -> None:
    provider: Final = FredProvider(_fetch((_record(3, 4.2),)))
    observation: Final = provider.observations("DGS10", _START, _END)[0]
    assert (observation.observation_date, observation.value) == (date(2026, 8, 3), 4.2)


def test_a_non_numeric_value_fails_rather_than_being_coerced_to_zero() -> None:
    provider: Final = FredProvider(_fetch((_record(3, "unavailable"),)))
    with pytest.raises(ValidationError):
        _ = provider.observations("DGS10", _START, _END)
