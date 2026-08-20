"""The four Yahoo calendars, flattened into one shape.

An analyst asks "what is happening this week", not "which of four endpoints holds it", so the
four frames collapse into one sorted list tagged by kind.

Each row is validated on its own. Validating the batch would let one row Yahoo typed unexpectedly
cost the other forty-seven, and partial success is a first-class result everywhere else here.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from functools import partial
from typing import Final

from anyio import to_thread
from pydantic import TypeAdapter, ValidationError

from orient.domain.models import Calendar, CalendarEntry, CalendarKind
from orient.providers._untyped import (
    Records,
    yahoo_earnings_calendar,
    yahoo_economic_calendar,
    yahoo_ipo_calendar,
    yahoo_splits_calendar,
)

ALL_KINDS: Final[tuple[CalendarKind, ...]] = ("earnings", "economic", "ipo", "split")

_ENTRY: Final = TypeAdapter(CalendarEntry)

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


def _side(value: object) -> str | None:
    """Yahoo carries each side of a split as a number, and "2.0-for-1.0" is not what a reader reads."""
    return f"{value:g}" if isinstance(value, int | float) and not isinstance(value, bool) else None


def _split_entry(row: Mapping[str, object]) -> Mapping[str, object]:
    new, old = _side(row.get("share_worth")), _side(row.get("old_share_worth"))
    return {
        "kind": "split",
        "label": row.get("company") or row.get("symbol") or "unknown",
        "symbol": row.get("symbol"),
        "occurs_at": row.get("payable_on"),
        "detail": None if new is None or old is None else f"{new}-for-{old}",
    }


def _read(row: Mapping[str, object]) -> CalendarEntry | None:
    try:
        return _ENTRY.validate_python(row)
    except ValidationError:
        return None


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

    async def entries(
        self,
        start: date,
        end: date,
        kinds: Sequence[CalendarKind] | None = None,
    ) -> Calendar:
        return await to_thread.run_sync(partial(self._entries, start, end, kinds))

    def _entries(
        self,
        start: date,
        end: date,
        kinds: Sequence[CalendarKind] | None = None,
    ) -> Calendar:
        """Sorted by date, undated last, so the soonest thing is always first."""
        wanted: Final = ALL_KINDS if kinds is None else kinds
        rows: Final = tuple(
            shape(row) for kind in wanted for fetch, shape in (self._sources[kind],) for row in fetch(start, end)
        )
        read: Final = tuple(entry for entry in map(_read, rows) if entry is not None)
        return Calendar(
            entries=tuple(sorted(read, key=lambda entry: (entry.occurs_at is None, entry.occurs_at or date.max))),
            unreadable=len(rows) - len(read),
        )
