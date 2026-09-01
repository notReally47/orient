"""Which rows out of a vendor frame count as a traded session."""

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Final

import pytest
from pydantic import ValidationError

from orient.providers._untyped import Records
from orient.providers.yahoo.prices import YahooPrices

pytestmark = pytest.mark.anyio

SESSION: Final = date(2026, 8, 27)
WINDOW: Final = (date(2026, 8, 20), date(2026, 8, 28))


def _row(when: date = SESSION, **overrides: object) -> Mapping[str, object]:
    return {
        "session_date": when,
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 1.5,
        "volume": 10,
        **overrides,
    }


def _prices(*rows: Mapping[str, object]) -> YahooPrices:
    served: Final[Records] = rows

    def fetch_one(symbol: str, start: date, end: date) -> Records:
        del symbol, start, end
        return served

    def fetch_many(symbols: Sequence[str], start: date, end: date) -> Mapping[str, Records]:
        del start, end
        return dict.fromkeys(symbols, served)

    return YahooPrices(fetch_one, fetch_many)


async def test_a_session_that_has_not_traded_yet_is_not_a_bar() -> None:
    """The vendor emits a stub for a session whose books are open and whose prices have not
    printed: volume populated, every price empty. Validating it took the whole series with it,
    which broke every price call on the morning it first appeared."""
    stub: Final = _row(date(2026, 8, 28), open=None, high=None, low=None, close=None, volume=2_589_484_000)

    bars: Final = await _prices(_row(), stub).bars("^GSPC", *WINDOW)

    assert [bar.session_date for bar in bars] == [SESSION]


async def test_a_padded_row_from_a_batched_download_is_dropped() -> None:
    """A multi-symbol download pads every symbol to a shared calendar, so a symbol that did not
    trade that day arrives with empty prices rather than not at all."""
    bars: Final = await _prices(_row(date(2026, 8, 26), close=None), _row()).bars("^GSPC", *WINDOW)

    assert [bar.session_date for bar in bars] == [SESSION]


async def test_a_column_the_vendor_renamed_still_fails_rather_than_shortening_the_series() -> None:
    """A missing price is a row to skip. A missing column is a schema change, and quietly
    returning a shorter series would hide it until a summary was written off half a year."""
    moved: Final = {"session_date": SESSION, "open": 1.0, "high": 2.0, "low": 0.5, "volume": 10}

    with pytest.raises(ValidationError):
        _ = await _prices(moved).bars("^GSPC", *WINDOW)


async def test_bars_come_back_oldest_first() -> None:
    """Every window calculation above reads the last row as the latest one."""
    bars: Final = await _prices(_row(date(2026, 8, 27)), _row(date(2026, 8, 25)), _row(date(2026, 8, 26))).bars(
        "^GSPC", *WINDOW
    )

    assert [bar.session_date.day for bar in bars] == [25, 26, 27]
