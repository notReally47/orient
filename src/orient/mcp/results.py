"""Envelopes for the tools whose answer is a list.

The SDK derives a tool's output schema from its return annotation, and a bare tuple gives the
model an unnamed array. Wrapping each list in a model means every tool answers with an object
whose field says what the list is, and leaves room to add a count or a caveat without changing
the tool's shape.
"""

from datetime import date
from typing import Literal
from uuid import UUID

from orient.domain.market import InstrumentMatch
from orient.domain.models import Bar, Claim, Frozen, Signals


class InstrumentMatches(Frozen):
    query: str
    matches: tuple[InstrumentMatch, ...] = ()


class PriceHistory(Frozen):
    symbol: str
    start: date
    end: date
    bars: tuple[Bar, ...] = ()


class RecalledClaim(Frozen):
    """A claim stripped of its storage identifiers, which mean nothing to a model."""

    subject_symbol: str
    session_date: str
    kind: str
    statement: str
    attribution: str | None = None

    @classmethod
    def of(cls, claim: Claim) -> "RecalledClaim":
        return cls(
            subject_symbol=claim.subject_symbol,
            session_date=claim.session_date.isoformat(),
            kind=claim.kind,
            statement=claim.statement,
            attribution=claim.attribution,
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
    reason: Literal["grounding", "quality", "unfiled"] | None = None
    detail: str | None = None
    figures: tuple[str, ...] = ()


class PriorSession(Frozen):
    """One earlier session's measurements, without the symbol repeated on every row."""

    session_date: str
    close: float | None = None
    one_day: float | None = None
    realised_volatility_20d: float | None = None
    volume_vs_20_day: float | None = None
    drawdown_from_52_week_high: float | None = None

    @classmethod
    def of(cls, signals: Signals) -> "PriorSession":
        return cls(
            session_date=signals.session_date.isoformat(),
            close=signals.close,
            one_day=signals.returns.one_day,
            realised_volatility_20d=signals.realised_volatility_20d,
            volume_vs_20_day=signals.volume_vs_20_day,
            drawdown_from_52_week_high=signals.drawdown_from_52_week_high,
        )


class Recollection(Frozen):
    symbol: str
    sessions: tuple[PriorSession, ...] = ()
    open_items: tuple[RecalledClaim, ...] = ()
