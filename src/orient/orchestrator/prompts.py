"""The text the orchestrator itself contributes, which is deliberately almost none of it.

How to research and how to write are defined in the skill tree, so a human can change them
without touching code and any harness reads the same words. This module holds only what the loop
itself must say: the framing that tells a model it is working alone, the one-line subject, and
the nudges for a turn that produced nothing usable. Anything longer than that belongs in a skill.
"""

from dataclasses import dataclass
from datetime import date
from typing import Final

from orient.domain.levels import WORD_BUDGETS
from orient.domain.models import ReadingLevel
from orient.orchestrator.events import Rejection

AGENT_FRAMING: Final = """\
You are producing one market summary, working on your own.

Nothing has been fetched for you. The skills below are available but not loaded: you have their
names and descriptions only. Load one with `activate_skill`, and read a file bundled with a skill
using `read_skill_resource` when that skill's instructions point at it.

Start by activating the `analysis` skill. It says how to establish what happened, and which of
the tools this particular instrument's session actually needs.

Every figure the tools return was measured. A null means unknown and must never be filled in, and
a number quoted in a news article was not measured by anything.

You are finished when `save_summary` accepts the summary, not when you have written one.
"""

UNFINISHED: Final = """\
You stopped without saving anything. If the summary is written, call `save_summary` with it. If it
is not, keep working: activate the skills you still need, and call the tools the analysis skill
said this instrument requires.
"""


@dataclass(frozen=True, slots=True)
class Subject:
    symbol: str
    session_date: date
    level: ReadingLevel


def brief(subject: Subject) -> str:
    budget: Final = WORD_BUDGETS[subject.level]
    return (
        f"Summarise {subject.symbol} for the session of {subject.session_date:%d %B %Y}, "
        f"written for a {subject.level} reader at {budget.minimum} to {budget.maximum} words."
    )


def blocked(detail: str) -> str:
    """A guardrail turned the turn away. Which guardrail is in the detail, so it is passed on
    verbatim rather than described, and the model reads what the policy actually said."""
    return f"That turn was refused by a policy on this proxy:\n{detail}\n\nAdjust and continue."


def revise(reason: Rejection, detail: str) -> str:
    match reason:
        case "grounding":
            return (
                f"These figures appear in the summary but were not measured: {detail}. "
                "Rewrite so every figure it quotes is one the tools returned, dropping any "
                "sentence that cannot be written without an unmeasured figure."
            )
        case "judge":
            return f"The summary was rejected on review. Rewrite it addressing this in full:\n{detail}"
