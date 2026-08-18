"""The parser is what lets an older skill version keep rendering, so it is tested on bad input.

Every case here is a document the writer could plausibly produce. None of them may raise, and
none of them may silently lose prose the reader was meant to see.
"""

from typing import Final

from orient.orchestrator.sections import Draft, as_markdown, parse, prose

SPINE: Final = """\
# The index gave back Monday's gain on a narrow tape

## The big picture

Two sectors carried the week and both fell today.

## What moved, and why

Energy led the decline.

## Reading the signals

Volatility rose while the index fell.

## What to watch this week

CPI lands on Thursday.
"""


def test_the_full_spine_parses_into_a_thesis_and_four_sections() -> None:
    draft: Final = parse(SPINE)
    assert draft.thesis == "The index gave back Monday's gain on a narrow tape"
    assert [section.heading for section in draft.sections] == [
        "The big picture",
        "What moved, and why",
        "Reading the signals",
        "What to watch this week",
    ]
    assert draft.sections[1].body == "Energy led the decline."


def test_a_missing_section_is_absent_rather_than_an_error() -> None:
    draft: Final = parse("# A claim\n\n## The big picture\n\nIt rose.\n")
    assert len(draft.sections) == 1


def test_an_unknown_heading_becomes_a_section() -> None:
    """A skill version that adds a section must not cost the reader its prose."""
    draft: Final = parse("# A claim\n\n## Something new\n\nIt happened.\n")
    assert draft.sections[0].heading == "Something new"


def test_a_reordered_document_keeps_the_order_it_was_written_in() -> None:
    draft: Final = parse("# A claim\n\n## Second\n\nb\n\n## First\n\na\n")
    assert [section.heading for section in draft.sections] == ["Second", "First"]


def test_a_missing_title_marker_still_yields_the_thesis() -> None:
    draft: Final = parse("The index gave back Monday's gain\n\n## The big picture\n\nIt fell.\n")
    assert draft.thesis == "The index gave back Monday's gain"
    assert draft.sections[0].heading == "The big picture"


def test_a_document_with_no_headings_at_all_is_all_thesis() -> None:
    draft: Final = parse("It fell, and nothing else happened.")
    assert draft.thesis == "It fell, and nothing else happened."
    assert draft.sections == ()


def test_an_empty_section_is_dropped_rather_than_rendered_hollow() -> None:
    draft: Final = parse("# A claim\n\n## Empty\n\n## Full\n\nSomething.\n")
    assert [section.heading for section in draft.sections] == ["Full"]


def test_deeper_headings_are_sections_too() -> None:
    draft: Final = parse("# A claim\n\n### Deep\n\nSomething.\n")
    assert draft.sections[0].heading == "Deep"


def test_a_closed_atx_heading_loses_its_trailing_hashes() -> None:
    draft: Final = parse("# A claim\n\n## The big picture ##\n\nIt rose.\n")
    assert draft.sections[0].heading == "The big picture"


def test_prose_covers_the_thesis_and_every_body() -> None:
    """The grounding check reads this, so a figure hiding in the thesis must not escape it."""
    covered: Final = prose(parse(SPINE))
    assert "narrow tape" in covered
    assert "CPI lands on Thursday." in covered
    assert "The big picture" not in covered


def test_a_parsed_draft_round_trips_back_to_markdown() -> None:
    """A revise is re-prompted with the draft, so it has to come back in the form it went out in."""
    assert parse(as_markdown(parse(SPINE))) == parse(SPINE)


def test_a_thesis_only_draft_renders_without_a_dangling_heading() -> None:
    assert as_markdown(Draft(thesis="It fell.")) == "# It fell.\n\n"
