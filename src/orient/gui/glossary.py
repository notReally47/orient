"""Terms defined where the reader meets them, and again where they can look them up.

The writer supplies one definition per term. The page shows it twice over: on the first mention in
the prose, so a reader who pauses gets it without leaving the sentence, and in a list beneath the
summary, so a reader on a phone, on paper, or simply not hovering anything still has it. Same text
both times, written once.

A definition is model-written text going into markup, so it is escaped before it goes anywhere.
"""

import re
from collections.abc import Mapping, Sequence
from html import escape
from typing import Final

from orient.domain.models import Term

MAX_DEFINITION: Final = 240


def _pattern(terms: Sequence[str]) -> re.Pattern[str] | None:
    """One expression for every term, longest first so a phrase wins over a word inside it."""
    ordered: Final = sorted({term.strip() for term in terms if term.strip()}, key=len, reverse=True)
    if not ordered:
        return None
    return re.compile(r"\b(" + "|".join(re.escape(term) for term in ordered) + r")\b", re.IGNORECASE)


def annotate(prose: str, terms: Sequence[Term]) -> str:
    """The prose with each term made hoverable, the first time it appears.

    Only the first mention is marked. A page that dots the same word five times reads as though
    the reader is being nagged, and the definition is the same each time.
    """
    pattern: Final = _pattern([note.term for note in terms])
    if pattern is None:
        return prose
    meanings: Final[Mapping[str, str]] = {note.term.strip().lower(): note.meaning for note in terms}
    seen: Final[set[str]] = set()

    def mark(found: re.Match[str]) -> str:
        word = found.group(1)
        key = word.lower()
        meaning = meanings.get(key)
        if meaning is None or key in seen:
            return word
        seen.add(key)
        said = escape(meaning[:MAX_DEFINITION])
        return (
            f'<span class="orient-term" tabindex="0">{escape(word)}'
            f'<span class="orient-meaning" role="tooltip">{said}</span></span>'
        )

    return pattern.sub(mark, prose)


def listed(terms: Sequence[Term]) -> tuple[Term, ...]:
    """The same definitions as a list, alphabetical, for the section under the summary."""
    unique: Final[dict[str, Term]] = {note.term.strip().lower(): note for note in terms if note.term.strip()}
    return tuple(sorted(unique.values(), key=lambda note: note.term.lower()))
