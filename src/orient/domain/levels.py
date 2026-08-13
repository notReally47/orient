"""Word budgets per reading level.

Advanced is deliberately the shortest. Its reader wants a regime call, a scannable evidence
table and the falsifier; prose beyond that is padding, and the judge scores it as such.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from orient.domain.models import ReadingLevel


@dataclass(frozen=True, slots=True)
class WordBudget:
    minimum: int
    maximum: int

    def holds(self, words: int) -> bool:
        return self.minimum <= words <= self.maximum


WORD_BUDGETS: Final[Mapping[ReadingLevel, WordBudget]] = MappingProxyType(
    {
        "beginner": WordBudget(500, 700),
        "intermediate": WordBudget(400, 600),
        "advanced": WordBudget(350, 500),
    }
)
