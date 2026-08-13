"""The formatter behind `make shapes`.

Its output is what the typed providers get written against, so a description that hides a
column or silently truncates without saying so would send the models off in the wrong
direction. The probes themselves need Yahoo and are exercised by running the command.
"""

from collections.abc import Sequence
from typing import Final

import pytest

from orient.providers.shapes import MAX_KEYS, describe, probes, truncate


class _Frame:
    """Stands in for a DataFrame: the formatter only asks for `.columns` and `.index`."""

    def __init__(self, columns: Sequence[str], rows: int, index: Sequence[object] | None = None) -> None:
        self.columns: Final = list(columns)
        self.index: Final = tuple(range(rows)) if index is None else index


def test_a_frame_reports_its_row_count_and_every_column() -> None:
    described: Final = describe(_Frame(["Open", "High", "Low", "Close", "Volume"], rows=7))
    assert "rows=7" in described
    for column in ("Open", "High", "Low", "Close", "Volume"):
        assert column in described


class _NamedIndex(tuple[str, ...]):
    """A pandas Index carries a name; a bare tuple does not, and both reach this code."""

    name: str


def test_a_frame_reports_the_name_its_index_will_take_as_a_column() -> None:
    """That name becomes the record key after reset_index, so it decides what the model reads."""
    index: Final = _NamedIndex(("AAPL", "MSFT"))
    index.name = "symbol"

    described: Final = describe(_Frame(["shortName"], rows=2, index=index))
    assert "index name='symbol'" in described
    assert "AAPL" in described


def test_an_unnamed_index_reports_none_rather_than_inventing_a_name() -> None:
    assert "index name=None" in describe(_Frame(["shortName"], rows=1))


def test_a_mapping_reports_its_keys_sorted() -> None:
    described: Final = describe({"zeta": 1, "alpha": 2})
    assert described.index("alpha") < described.index("zeta")


def test_a_list_of_dicts_reports_the_first_entry_keys() -> None:
    described: Final = describe([{"symbol": "AAPL", "exchange": "NMS"}])
    assert "of dict" in described
    assert "symbol" in described
    assert "exchange" in described


def test_a_plain_sequence_samples_rather_than_dumping_everything() -> None:
    described: Final = describe(list(range(500)))
    assert "[500]" in described
    assert "499" not in described


def test_truncation_says_how_much_it_hid() -> None:
    """Silent truncation would read as a short column list and produce a model missing fields."""
    described: Final = truncate([f"col{index}" for index in range(MAX_KEYS + 5)])
    assert "+5 more" in described


def test_a_short_list_is_not_marked_as_truncated() -> None:
    assert "more)" not in truncate(["a", "b"])


@pytest.mark.parametrize("value", [None, 42, 3.5])
def test_an_unrecognised_value_still_reports_its_type(value: object) -> None:
    assert type(value).__name__ in describe(value)


def test_every_probe_is_uniquely_labelled() -> None:
    """Duplicate labels in the dump would silently overwrite each other when read back."""
    labels: Final = [label for label, _ in probes()]
    assert len(labels) == len(set(labels))


def test_the_dump_covers_every_surface_the_tools_need() -> None:
    joined: Final = " ".join(label for label, _ in probes())
    for surface in (
        "Lookup",
        "Search",
        "screen",
        "download",
        "info",
        "funds_data",
        "Market",
        "Sector",
        "earnings_dates",
        "eps_trend",
        "analyst_price_targets",
        "option_chain",
        "earnings_calendar",
        "economic_events_calendar",
    ):
        assert surface in joined
