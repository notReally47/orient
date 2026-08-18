"""The calendar adapter, driven with the rows Yahoo really returns across its four surfaces.

Value types are what these assert. Every row here carries the type `make shapes` prints, because
the failure this adapter exists to absorb is a column whose name is right and whose values are
not: the two sides of a split arrive as numbers, and a model expecting a ready-made ratio string
rejects that surface's every row while the other three pass.
"""

from collections.abc import Mapping
from datetime import date
from typing import Final

from orient.domain.models import Calendar, CalendarEntry
from orient.providers._untyped import Records
from orient.providers.yahoo.calendars import Fetch, YahooCalendars

START: Final = date(2026, 8, 10)
END: Final = date(2026, 8, 17)


def _serving(records: Records) -> Fetch:
    def fetch(start: date, end: date) -> Records:
        del start, end
        return records

    return fetch


def _calendars(
    earnings: Records = (),
    economic: Records = (),
    ipo: Records = (),
    splits: Records = (),
) -> YahooCalendars:
    return YahooCalendars(_serving(earnings), _serving(economic), _serving(ipo), _serving(splits))


def _split(**overrides: object) -> Mapping[str, object]:
    """Yahoo carries each side as a number, and the payable date as a date."""
    return {
        "symbol": "OLDCO",
        "company": "Old Co",
        "payable_on": date(2026, 8, 14),
        "old_share_worth": 1,
        "share_worth": 2,
        **overrides,
    }


def _only(calendar: Calendar) -> CalendarEntry:
    assert len(calendar.entries) == 1
    return calendar.entries[0]


def test_a_split_ratio_is_rendered_from_the_two_numbers_it_arrives_as() -> None:
    """A reader reads neither 2.0-for-1.0 nor a row the adapter threw away for being numeric."""
    entry: Final = _only(_calendars(splits=(_split(),)).entries(START, END))

    assert entry.kind == "split"
    assert entry.detail == "2-for-1"
    assert entry.occurs_at == date(2026, 8, 14)


def test_a_fractional_ratio_keeps_the_fraction() -> None:
    entry: Final = _only(_calendars(splits=(_split(share_worth=3.0, old_share_worth=2.5),)).entries(START, END))

    assert entry.detail == "3-for-2.5"


def test_a_split_missing_a_side_is_kept_without_a_ratio() -> None:
    """The event still belongs on the calendar; only the ratio is unknown."""
    entry: Final = _only(_calendars(splits=(_split(share_worth=None),)).entries(START, END))

    assert entry.detail is None
    assert entry.label == "Old Co"


def test_the_four_surfaces_flatten_into_one_list_tagged_by_kind() -> None:
    calendar: Final = _calendars(
        earnings=({"symbol": "MSFT", "company": "Microsoft", "starts_at": date(2026, 8, 13), "timing": "After close"},),
        economic=({"event": "CPI", "region": "US", "event_time": date(2026, 8, 12)},),
        ipo=({"symbol": "NEWCO", "company": "New Co", "exchange": "NMS", "event_date": date(2026, 8, 15)},),
        splits=(_split(),),
    ).entries(START, END)

    assert tuple(entry.kind for entry in calendar.entries) == ("economic", "earnings", "split", "ipo")
    assert calendar.unreadable == 0


def test_entries_sort_by_date_with_the_undated_ones_last() -> None:
    """An IPO with no priced date still matters; sorting it first would bury what happens tomorrow."""
    calendar: Final = _calendars(
        ipo=(
            {"symbol": "NODATE", "company": "Not Priced Yet", "exchange": "NMS", "event_date": None},
            {"symbol": "NEWCO", "company": "New Co", "exchange": "NMS", "event_date": date(2026, 8, 15)},
        ),
    ).entries(START, END)

    assert tuple(entry.symbol for entry in calendar.entries) == ("NEWCO", "NODATE")


def test_only_the_kinds_asked_for_are_fetched() -> None:
    """Four surfaces at fifteen requests a minute is three wasted when one kind was wanted."""
    asked: Final[list[str]] = []

    def watching(name: str) -> Fetch:
        def fetch(start: date, end: date) -> Records:
            del start, end
            asked.append(name)
            return ()

        return fetch

    calendars: Final = YahooCalendars(*(watching(name) for name in ("earnings", "economic", "ipo", "split")))
    _ = calendars.entries(START, END, ("earnings",))

    assert asked == ["earnings"]


def test_a_row_yahoo_typed_unexpectedly_costs_itself_and_not_the_batch() -> None:
    """Validating the batch would let one bad row take the other forty-seven with it."""
    calendar: Final = _calendars(
        economic=(
            {"event": "CPI", "region": "US", "event_time": date(2026, 8, 12)},
            {"event": None, "region": 7, "event_time": "not a date"},
            {"event": "PPI", "region": "US", "event_time": date(2026, 8, 13)},
        ),
    ).entries(START, END)

    assert tuple(entry.label for entry in calendar.entries) == ("CPI", "PPI")
    assert calendar.unreadable == 1


def test_a_row_without_a_name_is_labelled_by_its_symbol() -> None:
    entry: Final = _only(
        _calendars(earnings=({"symbol": "MSFT", "starts_at": date(2026, 8, 13), "timing": "TAS"},)).entries(START, END)
    )

    assert entry.label == "MSFT"
    assert entry.detail == "TAS"


def test_the_window_asked_for_reaches_every_surface() -> None:
    windows: Final[list[tuple[date, date]]] = []

    def recording(start: date, end: date) -> Records:
        windows.append((start, end))
        return ()

    _ = YahooCalendars(recording, recording, recording, recording).entries(START, END)

    assert windows == [(START, END)] * 4


def test_an_empty_week_is_an_empty_calendar_rather_than_an_error() -> None:
    calendar: Final = _calendars().entries(START, END)

    assert calendar.entries == ()
    assert calendar.unreadable == 0
