"""Markdown into the four-section spine, forgivingly.

The spine is fixed, so this is code rather than a second model call, and the judge and the
grounding check both score the prose the reader will actually see.

It never fails. An unknown heading becomes a section, a missing section is simply absent, a
reordered document keeps its order, and everything before the first section heading is the
thesis. That is what lets a summary written against an older skill version keep rendering.
"""

import re
from typing import Final

from orient.domain.models import Frozen, Section

_HEADING: Final = re.compile(r"^\s{0,3}(#{2,6})\s+(?P<heading>.+?)\s*#*\s*$", re.MULTILINE)
_TITLE: Final = re.compile(r"^\s{0,3}#\s+")


class Draft(Frozen):
    thesis: str
    sections: tuple[Section, ...] = ()


def _thesis(head: str) -> str:
    """A leading '# ' marks it, but a writer that omitted the marker still meant this line."""
    return " ".join(_TITLE.sub("", head, count=1).split())


def parse(markdown: str) -> Draft:
    matches: Final = tuple(_HEADING.finditer(markdown))
    bounds: Final = (*(match.start() for match in matches), len(markdown))
    sections: Final = tuple(
        Section(heading=match.group("heading"), body=markdown[match.end() : bounds[index + 1]].strip())
        for index, match in enumerate(matches)
    )
    return Draft(
        thesis=_thesis(markdown[: bounds[0]].strip()),
        sections=tuple(section for section in sections if section.body),
    )


def as_markdown(draft: Draft) -> str:
    """The inverse, for re-prompting: a revise sees the draft in the form it produced it."""
    body: Final = "\n\n".join(f"## {section.heading}\n\n{section.body}" for section in draft.sections)
    return f"# {draft.thesis}\n\n{body}" if draft.thesis else body


def prose(draft: Draft) -> str:
    """Everything a reader will read, which is exactly what the grounding check must cover."""
    return " ".join((draft.thesis, *(section.body for section in draft.sections)))
