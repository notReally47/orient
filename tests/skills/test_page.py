"""The briefings that tell the writer what the reader already sees.

They exist because the writer duplicated the page it could not see: a Micron summary explained
what a volume multiple is in the prose and filed the identical sentence as the hover definition
for the tile above it. `references/page.md` and `references/visuals.md` are filed rather than
generated, so nothing keeps them honest except these: a label renamed in the vocabulary and not in
the briefing has the writer working around a wording the reader never meets, and a briefing that
disagrees with the page is worse than none.
"""

from typing import Final

import pytest

from orient.domain import vocabulary
from orient.skills.loader import SkillError, Skills

WRITING: Final = "writing"
PAGE: Final = "references/page.md"
VISUALS: Final = "references/visuals.md"


def _page() -> str:
    return Skills().resource(WRITING, PAGE)


def _visuals() -> str:
    return Skills().resource(WRITING, VISUALS)


def test_both_briefings_are_listed_among_the_resources_the_writer_may_read() -> None:
    resources: Final = Skills().body(WRITING).resources

    assert PAGE in resources
    assert VISUALS in resources


def test_every_figure_the_page_can_show_is_named_by_the_name_the_writer_picks_it_by() -> None:
    """A figure missing here is one the writer never learns it may ask for."""
    page: Final = _page()

    for figure in vocabulary.HEADLINE_FIGURES:
        assert f"`{figure}`" in page, f"{figure} is on the page and not in the briefing"


def test_every_label_the_reader_sees_is_named_in_the_briefing() -> None:
    """A label renamed in the vocabulary and not here has the writer working around a wording the
    reader never meets."""
    page: Final = _page()

    for term in (*vocabulary.HEADLINE.values(), *vocabulary.BACKDROP.values()):
        assert term.label in page, f"the page shows {term.label!r} and the briefing never says so"


def test_every_panel_the_layout_accepts_is_described() -> None:
    """`visuals.md` is the single description of the panels. `page.md` used to carry a second one,
    which is how the two came to disagree about what `sectors` draws."""
    visuals: Final = _visuals()

    for panel in vocabulary.PANELS:
        assert f"`{panel}`" in visuals, f"{panel} can be laid out and the briefing never says what it draws"


def test_the_briefing_says_which_figures_lead_when_the_writer_names_none() -> None:
    """Naming none is a real choice and the writer should know what it buys."""
    page: Final = _page()

    assert all(figure in page for figure in vocabulary.DEFAULT_TILES)


def test_the_chart_lines_are_named_so_a_moving_average_is_not_explained_twice() -> None:
    page: Final = _page()

    assert all(line in page for line in vocabulary.SERIES)


def test_the_briefing_tells_the_writer_to_cite_rather_than_type() -> None:
    """The one instruction the whole figure-reference design rests on."""
    page: Final = _page()

    assert "{{close}}" in page
    assert "Never type a number" in page


def test_a_reference_carries_no_frontmatter_of_its_own() -> None:
    """Nothing parses it. `resource` returns the file whole, so a fence is prose the model reads
    and pays for, and one that drifts from the body contradicts it: `beginner.md` claimed two
    different word budgets that way."""
    for path in Skills().body(WRITING).resources:
        assert not Skills().resource(WRITING, path).startswith("---\n"), path


def test_asking_for_a_resource_nobody_filed_still_fails() -> None:
    with pytest.raises(SkillError):
        _ = Skills().resource(WRITING, "references/nothing.md")
