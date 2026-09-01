"""The text the orchestrator itself contributes, which is deliberately almost none of it.

How to research and how to write are defined in the skill tree, so a human can change them
without touching code and any harness reads the same words. This module holds only what the loop
itself must say: the framing that tells a model it is working alone, the one-line subject, and
the nudges for a turn that produced nothing usable. Anything longer than that belongs in a skill.

There is nothing here for a summary that was refused. The model reads `save_summary`'s own answer,
which names the reason, the detail and the offending figures, and restating that from out here
would hand it the same instruction twice in slightly different words.
"""

from dataclasses import dataclass
from datetime import date
from typing import Final

from orient.domain.levels import WORD_BUDGETS
from orient.domain.models import ReadingLevel

AGENT_FRAMING: Final = """\
You are producing one market summary, working on your own. Nothing has been fetched for you, and
no skill is loaded.

Start by activating the `analysis` skill. It says how to establish what happened, and which of
the tools this particular instrument's session actually needs.

Every figure the tools return was measured. A field absent from a result is one nothing measured:
it is not zero and must never be filled in. A number quoted in a news article was measured by
nothing at all.

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
    """The one-line request: which instrument, which session, which reader, and how long."""
    budget: Final = WORD_BUDGETS[subject.level]
    return (
        f"Summarise {subject.symbol} for the session of {subject.session_date:%d %B %Y}, "
        f"written for a {subject.level} reader at {budget.minimum} to {budget.maximum} words."
    )


def blocked(detail: str) -> str:
    """A guardrail turned the turn away. Which guardrail is in the detail, so it is passed on
    verbatim rather than described, and the model reads what the policy actually said."""
    return f"That turn was refused by a policy on this proxy:\n{detail}\n\nAdjust and continue."
