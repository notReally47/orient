"""The only module permitted to touch untyped third-party libraries.

yfinance and pandas-datareader ship no type information, so every call into them returns
Unknown under strict checking. Confining them here keeps the suppressions in one reviewable
place and leaves the rest of the package strict. Callers get plain records keyed to the domain
model's field names and validate them into that model themselves.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Final, Protocol, cast

import pandas_datareader.data as web
import yfinance as yf

Records = Sequence[Mapping[str, object]]


class _Frame(Protocol):
    """The only two frame methods this module uses, so each untyped result is narrowed once."""

    def reset_index(self) -> "_Frame": ...
    def to_dict(self, orient: str) -> Records: ...


def _records(frame: _Frame) -> Records:
    return frame.reset_index().to_dict(orient="records")


def yahoo_daily_bars(symbol: str, period: str) -> Records:
    ticker: Final = yf.Ticker(symbol)
    frame: Final = cast(
        "_Frame",
        ticker.history(period=period),  # pyright: ignore[reportUnknownMemberType]  # no stubs
    )
    return tuple(
        {
            "session_date": row.get("Date", row.get("Datetime")),
            "open": row.get("Open"),
            "high": row.get("High"),
            "low": row.get("Low"),
            "close": row.get("Close"),
            "volume": row.get("Volume"),
        }
        for row in _records(frame)
    )


def fred_observations(series_id: str, start: date, end: date) -> Records:
    frame: Final = cast(
        "_Frame",
        web.DataReader(series_id, "fred", start, end),  # pyright: ignore[reportUnknownMemberType]  # no stubs
    )
    return tuple(
        {"observation_date": row.get("DATE", row.get("index")), "value": row.get(series_id)} for row in _records(frame)
    )
