"""The four Yahoo calendars, flattened into one shape.

An analyst asks "what is happening this week", not "which of four endpoints holds it", so the
four frames collapse into one sorted list tagged by kind.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Final

from pydantic import TypeAdapter

from orient.domain.market import CalendarEntry, CalendarKind
from orient.providers._untyped import (
    Records,
    yahoo_earnings_calendar,
    yahoo_economic_calendar,
    yahoo_ipo_calendar,
    yahoo_splits_calendar,
)

ALL_KINDS: Final[tuple[CalendarKind, ...]] = ("earnings", "economic", "ipo", "split")

_ENTRIES: Final = TypeAdapter(tuple[CalendarEntry, ...])

Fetch = Callable[[date, date], Records]
Shape = Callable[[Mapping[str, object]], Mapping[str, object]]
Source = tuple[Fetch, Shape]


def _earnings_entry(row: Mapping[str, object]) -> Mapping[str, object]:
    return {
        "kind": "earnings",
        "label": row.get("company") or row.get("symbol") or "unknown",
        "symbol": row.get("symbol"),
        "occurs_at": row.get("starts_at"),
        "detail": row.get("timing"),
    }


def _economic_entry(row: Mapping[str, object]) -> Mapping[str, object]:
    return {
        "kind": "economic",
        "label": row.get("event") or "unknown",
        "symbol": None,
        "occurs_at": row.get("event_time"),
        "detail": row.get("region"),
    }


def _ipo_entry(row: Mapping[str, object]) -> Mapping[str, object]:
    return {
        "kind": "ipo",
        "label": row.get("company") or row.get("symbol") or "unknown",
        "symbol": row.get("symbol"),
        "occurs_at": row.get("event_date"),
        "detail": row.get("exchange"),
    }


def _split_entry(row: Mapping[str, object]) -> Mapping[str, object]:
    return {
        "kind": "split",
        "label": row.get("company") or row.get("symbol") or "unknown",
        "symbol": row.get("symbol"),
        "occurs_at": row.get("payable_on"),
        "detail": row.get("share_worth"),
    }


class YahooCalendars:
    def __init__(
        self,
        earnings: Fetch = yahoo_earnings_calendar,
        economic: Fetch = yahoo_economic_calendar,
        ipo: Fetch = yahoo_ipo_calendar,
        splits: Fetch = yahoo_splits_calendar,
    ) -> None:
        self._sources: Final[Mapping[CalendarKind, Source]] = {
            "earnings": (earnings, _earnings_entry),
            "economic": (economic, _economic_entry),
            "ipo": (ipo, _ipo_entry),
            "split": (splits, _split_entry),
        }

    def entries(
        self,
        start: date,
        end: date,
        kinds: Sequence[CalendarKind] = ALL_KINDS,
    ) -> tuple[CalendarEntry, ...]:
        """Sorted by date, undated last, so the soonest thing is always first."""
        rows: Final = tuple(
            shape(row) for kind in kinds for fetch, shape in (self._sources[kind],) for row in fetch(start, end)
        )
        entries: Final = _ENTRIES.validate_python(rows)
        return tuple(sorted(entries, key=lambda entry: (entry.occurs_at is None, entry.occurs_at or date.max)))
