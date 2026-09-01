"""Terms defined where the reader meets them.

The definitions are model-written text going into markup, so what matters as much as the marking
is that nothing in them can break out of the attribute it lands in.
"""

from html.parser import HTMLParser
from typing import Final

from orient.domain.models import Term
from orient.gui import glossary

BREADTH: Final = Term(term="breadth", meaning="how many rose against how many fell")


class _Tags(HTMLParser):
    """Reads the marked prose as a browser would, which is the only honest way to ask whether
    a definition stayed inside the attribute it was put in."""

    def __init__(self) -> None:
        super().__init__()
        self.opened: list[str] = []
        self.attributes: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.opened.append(tag)
        self.attributes.append((tag, {name: value or "" for name, value in attrs}))


def test_a_flagged_term_becomes_hoverable_where_it_appears() -> None:
    marked: Final = glossary.annotate("The breadth was broad.", (BREADTH,))

    assert 'class="orient-term"' in marked
    assert ">breadth<" in marked
    assert "how many rose against how many fell" in marked


def test_a_marked_term_can_be_reached_from_the_keyboard() -> None:
    """A definition only a mouse can read is one a keyboard reader never sees."""
    marked: Final = glossary.annotate("breadth", (BREADTH,))

    assert 'tabindex="0"' in marked
    assert 'role="tooltip"' in marked


def test_only_the_first_mention_is_marked() -> None:
    """Dotting the same word five times reads as nagging, and the meaning does not change."""
    marked: Final = glossary.annotate("breadth, then breadth again", (BREADTH,))

    assert marked.count("orient-term") == 1
    assert marked.endswith("breadth again")


def test_a_term_inside_a_longer_word_is_left_alone() -> None:
    marked: Final = glossary.annotate("breadthwise", (BREADTH,))

    assert "orient-term" not in marked


def test_the_longest_matching_term_wins() -> None:
    """Otherwise "Price Index" would be marked inside "Producer Price Index" and read as a
    definition of the wrong thing."""
    notes: Final = (
        Term(term="Price Index", meaning="a measure of prices"),
        Term(term="Producer Price Index", meaning="a measure of wholesale prices"),
    )

    marked: Final = glossary.annotate("The Producer Price Index was flat.", notes)

    assert "a measure of wholesale prices" in marked
    assert 'a measure of prices"' not in marked


def test_a_definition_cannot_introduce_markup_of_its_own() -> None:
    """The definition is written by a model, so it is text rather than markup wherever it goes."""
    hostile: Final = Term(term="breadth", meaning='<img src=x onerror="alert(1)">')

    marked: Final = glossary.annotate("breadth", (hostile,))
    parsed: Final = _Tags()
    parsed.feed(marked)

    assert parsed.opened == ["span", "span"]
    assert not any("onerror" in attrs for _, attrs in parsed.attributes)


def test_prose_with_nothing_flagged_is_returned_unchanged() -> None:
    assert glossary.annotate("Nothing here.", ()) == "Nothing here."


def test_a_very_long_definition_is_cut_to_something_a_hover_can_hold() -> None:
    wordy: Final = Term(term="breadth", meaning="x" * 900)

    marked: Final = glossary.annotate("breadth", (wordy,))

    assert "x" * glossary.MAX_DEFINITION in marked
    assert "x" * (glossary.MAX_DEFINITION + 1) not in marked
