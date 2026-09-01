"""What a finished summary leaves behind for the next one to find.

Claims are the narrative half of the knowledge bank: a cause the summary asserted, an expectation
it set, an anomaly it could not explain. They are embedded so a later session can ask when things
last looked like this, and dated so an expectation can be settled rather than left open forever.
"""

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Final

from orient.domain.models import Claim, Summary
from orient.llm import extraction
from orient.llm.chat import Answered, SystemMessage, UserMessage
from orient.llm.embeddings import EmbeddingError
from orient.mcp.deps import ToolDeps

WATCH_HORIZON: Final = timedelta(days=7)

FRAMING: Final = """\
Read the summary below and return JSON only.

Record only what could not be recomputed from the measurements. Do not restate a figure: "the
index rose 0.65%" is already in the numbers and is not a claim.

Record a cause the summary asserted, with `attribution` naming who said it. Record a
forward-looking statement only when it says what would have to happen for it to be judged, not
that a scheduled event is scheduled. Record an anomaly whenever the summary said something could
not be explained.

`mentioned_symbols` are tickers, never company names.
"""


async def read_back(deps: ToolDeps, markdown: str, session: str | None) -> extraction.Extraction:
    """What a finished summary claimed, pulled back out of its own prose.

    Reads the rendered text rather than the draft: a figure reference is not a claim about
    anything until it has resolved to the measurement behind it.
    """
    answer: Final = await deps.chat.complete(
        model=deps.fast_model,
        messages=[SystemMessage(content=FRAMING), UserMessage(content=markdown)],
        schema=extraction.SCHEMA,
        tags=("phase:extract",),
        session=session,
    )
    if not isinstance(answer, Answered):
        return extraction.Extraction()
    return extraction.parse(answer.message.content)


def _due(target: date | None, expected: bool, session_date: date) -> date | None:
    if target is not None or not expected:
        return target
    return session_date + WATCH_HORIZON


def _claims(deps: ToolDeps, summary: Summary, found: Sequence[extraction.ExtractedClaim]) -> tuple[Claim, ...]:
    return tuple(
        Claim(
            id=deps.new_id(),
            summary_id=summary.id,
            subject_symbol=summary.symbol,
            session_date=summary.session_date,
            kind=entry.kind,
            statement=entry.statement,
            mentioned_symbols=entry.mentioned_symbols,
            attribution=entry.attribution,
            target_date=_due(entry.target_date, entry.kind == "expectation", summary.session_date),
        )
        for entry in found
    )


async def remember(
    deps: ToolDeps,
    summary: Summary,
    extracted: extraction.Extraction,
    session: str | None,
) -> int:
    """An embedding the proxy would not serve costs the claims, never the summary."""
    claims: Final = _claims(deps, summary, extracted.claims)
    if not claims:
        return 0
    try:
        vectors = await deps.embeddings.embed([claim.statement for claim in claims], session)
    except EmbeddingError:
        return 0
    await deps.claims.add(claims, vectors)
    return len(claims)
