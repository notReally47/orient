"""The provider's only job is validation, so these tests are about what it refuses to pass on.

Records here are shaped exactly as `_untyped.yahoo_daily_bars` returns them, including the
midnight timestamps yfinance puts on a daily bar.
"""

from collections.abc import Callable
from datetime import date, datetime
from typing import Final

import pytest
from pydantic import ValidationError

from orient.providers._untyped import Records
from orient.providers.yahoo import YahooPrices


def _fetch(records: Records) -> Callable[[str, str], Records]:
    def fetch(symbol: str, period: str) -> Records:
        del symbol, period
        return records

    return fetch


def _record(session_date: object, close: float = 100.0) -> dict[str, object]:
    return {
        "session_date": session_date,
        "open": 99.0,
        "high": 101.0,
        "low": 98.0,
        "close": close,
        "volume": 1_000,
    }


def test_a_midnight_timestamp_becomes_a_plain_date() -> None:
    """yfinance dates a daily bar with a timestamp; storing that would break date equality."""
    provider: Final = YahooPrices(_fetch((_record(datetime(2026, 8, 12, 0, 0)),)))  # noqa: DTZ001  # the feed is naive
    assert provider.daily_bars("^GSPC", "5d")[0].session_date == date(2026, 8, 12)


def test_a_date_passes_through_unchanged() -> None:
    provider: Final = YahooPrices(_fetch((_record(date(2026, 8, 12)),)))
    assert provider.daily_bars("^GSPC", "5d")[0].session_date == date(2026, 8, 12)


def test_bars_come_back_oldest_first_whatever_order_they_arrived_in() -> None:
    """Every window calculation above reads the last row as the latest, so the order is a guarantee."""
    records: Final = (_record(date(2026, 8, 12), 101.0), _record(date(2026, 8, 11), 100.0))
    provider: Final = YahooPrices(_fetch(records))
    assert tuple(bar.close for bar in provider.daily_bars("^GSPC", "5d")) == (100.0, 101.0)


def test_a_missing_column_fails_here_rather_than_downstream() -> None:
    """An upstream rename would otherwise surface as a null inside a summary weeks later."""
    incomplete: Final = ({"session_date": date(2026, 8, 12), "open": 99.0},)
    provider: Final = YahooPrices(_fetch(incomplete))
    with pytest.raises(ValidationError):
        _ = provider.daily_bars("^GSPC", "5d")


def test_an_absent_date_fails_rather_than_defaulting() -> None:
    provider: Final = YahooPrices(_fetch((_record(None),)))
    with pytest.raises(ValidationError):
        _ = provider.daily_bars("^GSPC", "5d")


def test_an_empty_response_is_an_empty_result_not_an_error() -> None:
    provider: Final = YahooPrices(_fetch(()))
    assert provider.daily_bars("^GSPC", "5d") == ()
