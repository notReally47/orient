"""The vendor edge, where a third-party library's own state can outlive its usefulness.

Everything else under `providers/` is driven through injected fetchers, so nothing exercises the
functions that really call yfinance. What is covered here is the one piece of behaviour in that
module that is a decision rather than a rename: what happens when Yahoo stops accepting the
credential yfinance is holding.
"""

from datetime import date
from typing import Final

import pytest
import yfinance as yf

from orient.providers import _untyped

START: Final = date(2026, 8, 10)
END: Final = date(2026, 8, 17)
REJECTED: Final = "{'code': 'Unauthorized', 'description': 'Invalid Crumb'}"
UNRELATED: Final = "the upstream host is unreachable"


class _Frame:
    """The two frame methods the module narrows every untyped result down to."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows: Final = rows

    def reset_index(self) -> "_Frame":
        return self

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        del orient
        return self._rows


class _Yahoo:
    """Yahoo's calendars and yfinance's credential singleton, standing in for both at once.

    The private `_crumb` is named as yfinance names it, because that attribute is what the code
    under test reaches for. `attempts` counts calls, which is how a test tells one retry from a
    loop.
    """

    def __init__(self, failures: int = 1, error: str = REJECTED) -> None:
        self.attempts: int = 0
        self._crumb: str | None = "stale"
        self._failures: Final = failures
        self._error: Final = error

    def __call__(self, start: date, end: date) -> "_Yahoo":
        del start, end
        return self

    @property
    def crumb(self) -> str | None:
        return self._crumb

    @property
    def earnings_calendar(self) -> _Frame:
        self.attempts += 1
        if self.attempts <= self._failures:
            raise RuntimeError(self._error)
        return _Frame([{"Symbol": "MSFT", "Company": "Microsoft"}])


def _standing_in(patch: pytest.MonkeyPatch, fake: _Yahoo) -> _Yahoo:
    patch.setattr(yf, "Calendars", fake)
    patch.setattr(yf.data, "YfData", lambda: fake)
    return fake


def test_a_rejected_crumb_is_thrown_away_and_the_call_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """Yahoo mints the crumb once per process and yfinance never replaces one it stops accepting.
    Without this, a single rejection ends every calendar call until the server is restarted."""
    yahoo: Final = _standing_in(monkeypatch, _Yahoo())

    rows: Final = _untyped.yahoo_earnings_calendar(START, END)

    assert yahoo.attempts == 2
    assert yahoo.crumb is None
    assert rows[0]["symbol"] == "MSFT"


def test_a_failure_that_is_not_the_crumb_keeps_the_one_it_has(monkeypatch: pytest.MonkeyPatch) -> None:
    """Discarding the credential on every error would re-fetch it through each unrelated outage."""
    yahoo: Final = _standing_in(monkeypatch, _Yahoo(error=UNRELATED))

    with pytest.raises(RuntimeError, match="unreachable"):
        _ = _untyped.yahoo_earnings_calendar(START, END)

    assert yahoo.attempts == 1
    assert yahoo.crumb == "stale"


def test_a_crumb_rejected_twice_is_reported_rather_than_retried_forever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One retry, not a loop. A Yahoo that refuses a freshly minted crumb is down, and a caller
    told so immediately learns it sooner than one waiting on an unbounded retry."""
    yahoo: Final = _standing_in(monkeypatch, _Yahoo(failures=99))

    with pytest.raises(RuntimeError, match="Invalid Crumb"):
        _ = _untyped.yahoo_earnings_calendar(START, END)

    assert yahoo.attempts == 2


class _LookupFrame:
    """A frame with the values pandas writes into cells that hold nothing."""

    def reset_index(self) -> "_LookupFrame":
        return self

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        del orient
        return [
            {
                "symbol": "AAPL",
                "shortName": "Apple Inc.",
                "quoteType": "EQUITY",
                "industryName": float("nan"),
                "regularMarketPrice": 200.0,
                "regularMarketPercentChange": float("nan"),
            }
        ]


class _Lookup:
    def __init__(self, query: str) -> None:
        del query

    def get_all(self, count: int) -> _LookupFrame:
        del count
        return _LookupFrame()


def test_a_cell_the_vendor_left_empty_arrives_as_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """pandas writes NaN into an empty cell, and a field typed as text rejects it, so one blank
    column would otherwise cost the whole search rather than its own value."""
    monkeypatch.setattr(yf, "Lookup", _Lookup)

    rows: Final = _untyped.yahoo_lookup("aapl", "all", 5)

    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["industry"] is None
    assert rows[0]["change_percent"] is None
    assert rows[0]["price"] == 200.0
