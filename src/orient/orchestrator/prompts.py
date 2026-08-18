"""The text that reaches the model, assembled in one place.

Nothing here decides anything. The rules live in the skill files so a human can change how the
system reasons and writes without touching Python; this only arranges the fetched material around
them. Keeping the arrangement in one module is what makes everything reaching a prompt visible at
once, which is the opposite of the prior attempt where a config key could be documented and never
read.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final

from orient.domain.levels import WORD_BUDGETS
from orient.domain.models import Claim, ReadingLevel, Signals
from orient.orchestrator.events import Rejection

RECALLED_SESSIONS: Final = 10

RESEARCH_FRAMING: Final = """\
You are researching one instrument so that a summary of its session can be written.

Work through the tools until you have what the skills below say you need. Every figure they
return was measured; a null means unknown and must never be filled in. News is somebody's claim
about the market, not a measurement, so treat a figure inside an article as unquotable.

When you have enough, stop calling tools and reply with a short note: what you established, what
you could not explain, and nothing else. Do not write the summary yet.
"""

WRITING_FRAMING: Final = """\
Write the summary now, in markdown, following the skills below.

Use only figures that appear in the measured material above. Do not compute a new one, do not
round a figure into a different one, and do not carry a number over from a news article. If a
figure you want is not there, write the sentence without it.
"""

EXTRACTION_FRAMING: Final = """\
Read the summary below and return JSON only.

`annotations` are terms the summary used that a reader at this level may not know, each defined
for the way this summary used it rather than generically.

`claims` are what the summary asserted. `observation` is something it stated about the session.
`expectation` is a forward-looking item from "what to watch", and carries the date it should be
judged on. `anomaly` is something the summary said it could not explain, which is what makes a
later explanation possible. `attribution` is the cause the summary gave, if it gave one.
`mentioned_symbols` are other instruments the claim refers to.
"""


@dataclass(frozen=True, slots=True)
class Subject:
    symbol: str
    session_date: date
    level: ReadingLevel


def _block(name: str, body: str) -> str:
    return f"<{name}>\n{body}\n</{name}>"


def brief(subject: Subject) -> str:
    budget: Final = WORD_BUDGETS[subject.level]
    return (
        f"Subject: {subject.symbol} on {subject.session_date:%d %B %Y}, "
        f"written for a {subject.level} reader at {budget.minimum} to {budget.maximum} words."
    )


def evidence(measured: Mapping[str, Mapping[str, object]]) -> str:
    """One named block per tool result, so the model can say which figure came from where."""
    body: Final = "\n".join(f"{name}: {json.dumps(payload, default=str)}" for name, payload in measured.items())
    return _block("measured", body)


def recall(sessions: Sequence[Signals], claims: Sequence[Claim]) -> str:
    """Fetched by SQL before the model plans anything, so it cannot forget to ask for its own past."""
    history: Final = "\n".join(
        f"{signals.session_date}: {signals.model_dump_json(exclude={'symbol', 'version'})}"
        for signals in sessions[:RECALLED_SESSIONS]
    )
    open_claims: Final = "\n".join(
        f"{claim.session_date} {claim.kind}: {claim.statement}"
        + (f" (attributed to {claim.attribution})" if claim.attribution else "")
        + (f" (due {claim.target_date})" if claim.target_date else "")
        for claim in claims
    )
    return _block(
        "previously",
        f"Recent sessions, newest first:\n{history or 'none recorded'}\n\n"
        f"Open items from earlier summaries:\n{open_claims or 'none'}",
    )


def revise(reason: Rejection, detail: str) -> str:
    match reason:
        case "grounding":
            return (
                f"These figures appear in the summary but not in the measured material: {detail}. "
                "Rewrite it so every figure it quotes is one of the measured ones, dropping any "
                "sentence that cannot be written without an unmeasured figure."
            )
        case "judge":
            return f"The summary was rejected on review. Rewrite it addressing this in full:\n{detail}"
