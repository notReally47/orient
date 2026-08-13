"""The only module permitted to touch untyped third-party libraries.

yfinance and pandas-datareader ship no type information, so every call into them
returns `Unknown` under strict checking. Confining them here means the suppressions
live in one reviewable place and the rest of the package stays strict. Callers get
`object` back and narrow it themselves.
"""

from datetime import date
from typing import Final, cast

import pandas_datareader.data as web
import yfinance as yf


def yahoo_history(symbol: str, period: str) -> object:
    ticker: Final = yf.Ticker(symbol)
    return ticker.history(period=period)  # pyright: ignore[reportUnknownMemberType]  # yfinance is untyped


def fred_series(series_id: str, start: date, end: date) -> object:
    return cast("object", web.DataReader(series_id, "fred", start, end))  # pyright: ignore[reportUnknownMemberType]
