"""Envelopes for the tools whose answer is a list.

The SDK derives a tool's output schema from its return annotation, and a bare tuple gives the
model an unnamed array. Wrapping each list in a model means every tool answers with an object
whose field says what the list is, and leaves room to add a count or a caveat without changing
the tool's shape.
"""

from orient.domain.market import InstrumentMatch, NewsArticle
from orient.domain.models import Bar, Claim, Frozen


class InstrumentMatches(Frozen):
    query: str
    matches: tuple[InstrumentMatch, ...] = ()


class PriceHistory(Frozen):
    symbol: str
    period: str
    bars: tuple[Bar, ...] = ()


class NewsResults(Frozen):
    query: str
    articles: tuple[NewsArticle, ...] = ()


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
