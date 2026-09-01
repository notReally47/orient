"""Everything wrong with a draft, found in one pass.

A rewrite costs a full generation, so a draft hears every fault at once rather than the first.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Final, Literal, NamedTuple

from orient.domain import figures, grounding
from orient.domain.figures import Figure
from orient.domain.models import Signals

Kind = Literal["unknown_figure", "ungrounded", "unmeasured_definition", "omission"]

MOSTLY_OVERNIGHT: Final = 0.6
AGAINST_THE_GAP: Final = 0.0

_SPLIT: Final = ("shape.gap", "gap", "shape.intraday", "intraday")


class Fault(NamedTuple):
    kind: Kind
    items: tuple[str, ...]
    detail: str


def _unknown(prose: str, known: Mapping[str, Figure]) -> Fault | None:
    missing: Final = figures.unknown(prose, known)
    if not missing:
        return None
    return Fault(
        kind="unknown_figure",
        items=missing,
        detail=(
            f"These are not measurements: {', '.join(missing)}. Name one the tools returned, or "
            "drop the sentence. compute_instrument_signals lists every name available."
        ),
    )


def _ungrounded(prose: str, evidence: frozenset[float], session_date: date) -> Fault | None:
    verdict: Final = grounding.check(figures.REFERENCE.sub("", prose), evidence, session_date)
    if not isinstance(verdict, grounding.Ungrounded):
        return None
    return Fault(
        kind="ungrounded",
        items=verdict.figures,
        detail=(
            f"These figures were typed into the prose but nobody measured them: "
            f"{', '.join(verdict.figures)}. Write {{{{name}}}} to cite a measurement instead of "
            "copying its digits, and drop any sentence that needs a figure the tools never returned."
        ),
    )


def _defined(glossary: Sequence[str], evidence: frozenset[float], session_date: date) -> Fault | None:
    """A definition quoting a figure nobody measured, held to the same rule as the prose.

    A definition is unchecked text sitting beside checked text, so a figure in one that could not
    appear in the other is a number the reader has no way to tell apart from a measured one. The
    rule is grounding's, not a separate one: a window length or a scale a measurement is defined
    on passes, because `up_down_volume_60d` cannot be explained without writing sixty.
    """
    verdicts: Final = (grounding.check(meaning, evidence, session_date) for meaning in glossary)
    unmatched: Final = tuple(
        dict.fromkeys(
            figure for verdict in verdicts if isinstance(verdict, grounding.Ungrounded) for figure in verdict.figures
        )
    )
    if not unmatched:
        return None
    return Fault(
        kind="unmeasured_definition",
        items=unmatched,
        detail=(
            f"These figures appear in a glossary definition and nobody measured them: "
            f"{', '.join(unmatched)}. A definition says what a term means, so it may name the "
            "window a measurement is taken over or the scale it runs on, but it may not quote a "
            "figure from this session. Put the figure in the prose, where it is checked."
        ),
    )


def _told(prose: str, known: Mapping[str, Figure]) -> bool:
    """Whether the prose put the split in front of the reader, by citation or in figures."""
    if set(figures.named(prose)) & set(_SPLIT):
        return True
    written: Final = {figures.written(known[name]).lstrip("+-") for name in _SPLIT if name in known}
    return any(shown in prose for shown in written)


def _omission(prose: str, known: Mapping[str, Figure], signals: Signals) -> Fault | None:
    """A move that was over at the open, described as though it happened during the day.

    Answered by whether the prose cited the split, not by hunting English for a word like
    "gapped": the second question is not one string matching can settle.
    """
    shape: Final = signals.shape
    share: Final = None if shape is None else shape.gap_share_of_move
    if share is None or AGAINST_THE_GAP <= share < MOSTLY_OVERNIGHT:
        return None
    if _told(prose, known):
        return None
    happened: Final = (
        "was already over when the market opened"
        if share >= MOSTLY_OVERNIGHT
        else "went one way overnight and was made back during the session"
    )
    return Fault(
        kind="omission",
        items=("shape.gap_share_of_move",),
        detail=(
            f"gap_share_of_move is {share}, so the move {happened}. Say where it happened in the "
            "section that reports the move, citing {{shape.gap}} and {{shape.intraday}}. A reader "
            "given only the close-to-close figure will picture a day of steady trading, and this "
            "was not one."
        ),
    )


def found(
    prose: str,
    known: Mapping[str, Figure],
    evidence: frozenset[float],
    signals: Signals,
    session_date: date,
    glossary: Sequence[str] = (),
) -> tuple[Fault, ...]:
    return tuple(
        fault
        for fault in (
            _unknown(prose, known),
            _ungrounded(prose, evidence, session_date),
            _defined(glossary, evidence, session_date),
            _omission(prose, known, signals),
        )
        if fault is not None
    )
