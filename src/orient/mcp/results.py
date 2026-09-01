"""Envelopes for the tools whose answer is a list.

The SDK derives a tool's output schema from its return annotation, and a bare tuple gives the
model an unnamed array. Wrapping each list in a model means every tool answers with an object
whose field says what the list is, and leaves room to add a count or a caveat without changing
the tool's shape.
"""

from datetime import date
from typing import Annotated, Final, Literal
from uuid import UUID

from pydantic import Field

from orient.domain.faults import Kind as FaultKind
from orient.domain.market import InstrumentMatch
from orient.domain.models import Bar, Claim, Frozen, Signals
from orient.domain.vocabulary import PanelName

MAX_MEANING: Final = 240
MAX_TERM: Final = 60


class InstrumentMatches(Frozen):
    query: str
    matches: tuple[InstrumentMatch, ...] = ()


class PriceHistory(Frozen):
    symbol: str
    start: date
    end: date
    bars: tuple[Bar, ...] = ()


class RecalledClaim(Frozen):
    """Something an earlier summary asserted, and the handle for saying whether it held.

    The id used to be stripped as storage detail. It is not: an expectation nobody can settle is
    an expectation that stays open forever, and every later summary is handed it again.
    """

    id: UUID
    subject_symbol: str
    session_date: str
    kind: str
    statement: str
    attribution: str | None = None
    due: str | None = None

    @classmethod
    def of(cls, claim: Claim) -> "RecalledClaim":
        return cls(
            id=claim.id,
            subject_symbol=claim.subject_symbol,
            session_date=claim.session_date.isoformat(),
            kind=claim.kind,
            statement=claim.statement,
            attribution=claim.attribution,
            due=None if claim.target_date is None else claim.target_date.isoformat(),
        )


class KnowledgeResults(Frozen):
    query: str
    claims: tuple[RecalledClaim, ...] = ()


class SaveOutcome(Frozen):
    """Accepted or refused, as one model rather than a union.

    The SDK derives a tool's output schema from its return annotation, and a union has no single
    schema, so a union comes back as text with no structured content at all. One model with a tag
    keeps the schema and keeps the caller matching on a discriminator rather than on a shape.
    """

    outcome: Literal["saved", "refused"]
    summary_id: UUID | None = None
    session_date: date | None = None
    sections: int = 0
    claims: int = 0
    reason: Literal["faults", "quality", "unfiled"] | None = None
    detail: str | None = None
    figures: tuple[str, ...] = ()
    drawn: tuple[str, ...] = ()
    dropped: tuple[str, ...] = ()
    faults: tuple["Fault", ...] = ()
    settled: int = 0


class PriorSession(Frozen):
    """One earlier session's measurements, without the symbol repeated on every row."""

    session_date: str
    close: float | None = None
    one_day: float | None = None
    realised_volatility_20d: float | None = None
    volume_multiple_20d: float | None = None
    drawdown_from_52_week_high: float | None = None

    @classmethod
    def of(cls, signals: Signals) -> "PriorSession":
        return cls(
            session_date=signals.session_date.isoformat(),
            close=signals.close,
            one_day=signals.returns.one_day,
            realised_volatility_20d=signals.realised_volatility_20d,
            volume_multiple_20d=signals.volume_multiple_20d,
            drawdown_from_52_week_high=signals.drawdown_from_52_week_high,
        )


class Recollection(Frozen):
    symbol: str
    sessions: tuple[PriorSession, ...] = ()
    open_items: tuple[RecalledClaim, ...] = ()


class LaidOut(Frozen):
    """One figure the writer wants drawn, and where.

    A name and a heading, never data. The name picks a renderer that reads the stored snapshot,
    which is what stops a chart becoming a place to put a number nothing measured.
    """

    name: PanelName
    section: Literal[
        "The big picture",
        "What moved, and why",
        "Reading the signals",
        "What to watch this week",
    ]


class Explained(Frozen):
    """One term the summary used, and what it means for this instrument.

    Any word the reader might not know: a label on a tile, a piece of trade shorthand, a term the
    prose leaned on and did not stop to define. The page shows it wherever the word appears.
    """

    term: Annotated[str, Field(max_length=MAX_TERM, description="The word or phrase as the summary wrote it")]
    meaning: Annotated[
        str,
        Field(
            max_length=MAX_MEANING,
            description=(
                "What it means here, in a sentence or two and with no figure in it. The prose is "
                "checked against what was measured, and so is this: a definition may name the window "
                "a measurement is taken over, and may not quote a figure from this session."
            ),
        ),
    ]


class Fault(Frozen):
    """One thing wrong with a draft, and what to do about it."""

    kind: FaultKind
    items: tuple[str, ...] = ()
    detail: str = ""


class Checked(Frozen):
    """What is wrong with a draft, all of it, before anything is written down.

    Every fault the mechanical checks can find, in one answer. Finding them one at a time meant a
    rewrite could only ever fix one, and a rewrite is a whole summary regenerated.
    """

    ok: bool
    faults: tuple[Fault, ...] = ()


class Settled(Frozen):
    """A verdict on something an earlier summary expected."""

    claim_id: UUID
    resolution: Literal["supported", "contradicted", "unresolved"]


class Resembled(Frozen):
    """A past session that measured like this one, and what happened next."""

    symbol: str
    session_date: str
    agreed_on: tuple[str, ...] = ()
    next_day: float | None = None


class Resemblances(Frozen):
    """Sessions that looked like this one, nearest first.

    `next_day` is what the session after each of them did. Several neighbours agreeing is a
    pattern worth a sentence; several disagreeing is worth saying so.
    """

    symbol: str
    session_date: str
    across_all_instruments: bool
    sessions: tuple[Resembled, ...] = ()


class Page(Frozen):
    """What the summary looks like: which figures are drawn, which lead, and what the words mean.

    One argument rather than three, because they are one decision. A layout without the glossary
    that explains its labels is half a page.
    """

    layout: Annotated[
        tuple[LaidOut, ...],
        Field(
            description=(
                "The figures drawn beside the prose, each with the section heading it sits under. "
                "Chosen for this session rather than by habit. A panel this instrument has no data "
                "for is dropped rather than refused, and the answer says which."
            )
        ),
    ] = ()
    tiles: Annotated[
        tuple[str, ...],
        Field(
            description=(
                "Which measurements lead the summary, named as compute_instrument_signals names "
                "them. Naming none falls back to a standing five, which is rarely the right five."
            )
        ),
    ] = ()
    glossary: Annotated[
        tuple[Explained, ...],
        Field(
            description=(
                "Every term the summary used that a reader at this level may not know. Each is "
                "shown wherever the word appears and listed beneath the summary, so the prose can "
                "use a term and move on instead of stopping to explain it."
            )
        ),
    ] = ()
