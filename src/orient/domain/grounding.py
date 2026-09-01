"""The numeric grounding check: deterministic Python, and the reason "numbers never pass through
a model" means something.

Every numeral in the prose must reconcile against a figure the run actually measured. The
permitted set is built by walking the evidence models and collecting every numeric leaf, plus the
numerals inside the strings they carry, which is what lets "S&P 500" and "13 August" through
without a special case. Each is compared at the precision the writer chose to quote it at, on
absolute value, since prose writes "fell 0.8%" for a signal of -0.008.

News is deliberately not evidence. An article's figures reached the prompt but nobody here
measured them, and the tool that returned them says as much, so quoting one fails this check.

The verdict is a value the caller acts on. A check that finds a violation and returns the prose
unchanged would be worse than no check, because it reads like a guarantee and is not one.
"""

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final, cast

MAX_REPORTED: Final = 10

SCALES: Final = (1.0, 100.0, 1e-3, 1e-6, 1e-9, 1e-12)

WINDOWS: Final = frozenset({1.0, 2.0, 5.0, 8.0, 10.0, 12.0, 20.0, 30.0, 50.0, 52.0, 60.0, 100.0, 200.0, 252.0})

_NUMERAL: Final = re.compile(r"\d(?:,(?=\d)|\d)*(?:\.\d+)?")
_SAFETY: Final = 1e-9


@dataclass(frozen=True, slots=True)
class Grounded:
    pass


@dataclass(frozen=True, slots=True)
class Ungrounded:
    figures: tuple[str, ...]


Verdict = Grounded | Ungrounded


def _numerals(text: str) -> Iterator[float]:
    yield from (abs(float(found.group().replace(",", ""))) for found in _NUMERAL.finditer(text))


def _leaves(value: object) -> Iterator[float]:
    """Walks JSON-shaped evidence, so dates arrive as strings and every leaf is a primitive."""
    match value:
        case bool() | None:
            return
        case int() | float():
            yield from (abs(float(value)) * scale for scale in SCALES)
        case str():
            yield from _numerals(value)
        case Mapping():
            for item in cast("Mapping[str, object]", value).values():
                yield from _leaves(item)
        case Sequence():
            for item in cast("Sequence[object]", value):
                yield from _leaves(item)
        case _:
            return


def measured(evidence: Sequence[Mapping[str, object]]) -> frozenset[float]:
    """Everything the tools returned, in every magnitude a writer might quote it at."""
    return frozenset(number for payload in evidence for number in _leaves(payload))


def _quotable(quoted: str, allowed: frozenset[float]) -> bool:
    """Matched at the precision the writer chose, so "18" reconciles against a VIX of 18.34."""
    number: Final = float(quoted.replace(",", ""))
    places: Final = len(quoted.partition(".")[2])
    tolerance: Final = 0.5 * 10.0**-places + _SAFETY
    return any(abs(candidate - number) <= tolerance for candidate in allowed)


def check(prose: str, evidence: frozenset[float], session_date: date) -> Verdict:
    years: Final = {float(session_date.year + offset) for offset in (-1, 0, 1)}
    allowed: Final = evidence | WINDOWS | years
    quoted: Final = (found.group() for found in _NUMERAL.finditer(prose))
    unmatched: Final = tuple(dict.fromkeys(figure for figure in quoted if not _quotable(figure, allowed)))
    return Grounded() if not unmatched else Ungrounded(figures=unmatched[:MAX_REPORTED])
