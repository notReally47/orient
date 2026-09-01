"""What the market-data tools hand back.

Separate from `models` because these are fetched rather than persisted: nothing here is
written to a table, and keeping the two apart stops the persisted models from acquiring
fields that only exist because a vendor returns them.

Almost every field is optional. Yahoo omits rather than nulls, and it omits different things
for an ETF than for an equity, so a required field would turn a partial answer into no answer
at all. A tool returning what it has beats a tool raising because one figure was missing.
"""

from collections.abc import Mapping
from datetime import date, datetime

from orient.domain.models import (
    AssetClass,
    Breadth,
    CalendarDate,
    CrossAsset,
    EarningsReaction,
    Frozen,
    Holding,
    SectorMove,
)


class InstrumentMatch(Frozen):
    symbol: str
    name: str | None = None
    quote_type: str | None = None
    exchange: str | None = None
    sector: str | None = None
    industry: str | None = None
    price: float | None = None
    change_percent: float | None = None


class InstrumentProfile(Frozen):
    """What an instrument is. Deliberately not what it does.

    Yahoo ships a business description of a few hundred words, and for Apple it was four fifths of
    this whole answer. It says nothing about the session, changes perhaps once a year, and the
    model already knows what the company sells; carrying it meant paying for it again on every
    turn of the run that followed.
    """

    symbol: str
    name: str | None = None
    asset_class: AssetClass | None = None
    sector: str | None = None
    industry: str | None = None
    exchange: str | None = None
    currency: str | None = None
    market_cap: float | None = None
    beta: float | None = None
    trailing_pe: float | None = None
    forward_pe: float | None = None
    dividend_yield: float | None = None
    average_volume: float | None = None
    shares_outstanding: float | None = None
    next_earnings: CalendarDate | None = None
    holdings: tuple[Holding, ...] = ()
    sector_weights: Mapping[str, float] = {}


class MarketSession(Frozen):
    """A session's bounds are moments, so each adapter converts its vendor's form to one here.

    A string would specify a type without specifying a format, leaving two adapters free to
    disagree while both satisfying it. The zone name sits beside them for the prose to quote.
    """

    name: str | None = None
    status: str | None = None
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    timezone: str | None = None


class MacroReading(Frozen):
    """One macro series as of the session: what it read, what it read before, and when.

    The date is not decoration. Inflation and employment are published monthly and weeks in
    arrears, so a reader told "inflation is 2.9%" deserves to know whether that was measured last
    month or last quarter. `observed_on` is the period the figure describes, not the day it was
    released.
    """

    series: str
    label: str
    value: float
    previous: float | None = None
    observed_on: date | None = None
    unit: str | None = None


class Macro(Frozen):
    """The published backdrop, from the statistical agencies rather than from a calendar.

    This exists because the forward economic calendar available here does not work: it is capped
    at twelve rows drawn from one day of the window and has never once returned a US release.
    What can be had reliably and without a key is the other direction — what the last prints
    actually were. "Core inflation was 2.8% in July and 2.9% in June" is a fact a reader can act
    on; "Kenyan CPI is due on the 31st" is not.
    """

    readings: tuple[MacroReading, ...] = ()
    real_yield_10y: float | None = None


class MarketContext(Frozen):
    """The backdrop a move happened against, fetched as one unit.

    Breadth and contribution are counted across the sector basket the adapter serves, never
    across index constituents, because no membership list is available. The field names say
    sector so a writer cannot mistake it for a constituent count.
    """

    session: MarketSession | None = None
    cross_asset: CrossAsset = CrossAsset()
    macro: Macro | None = None
    sectors: tuple[SectorMove, ...] = ()
    sector_breadth: Breadth | None = None
    sector_market: str | None = None


class EarningsEvent(Frozen):
    event_date: CalendarDate
    eps_estimate: float | None = None
    reported_eps: float | None = None
    surprise_percent: float | None = None


class EpsRevisions(Frozen):
    period: str
    up_last_7_days: int | None = None
    up_last_30_days: int | None = None
    down_last_7_days: int | None = None
    down_last_30_days: int | None = None


class PriceTargets(Frozen):
    current: float | None = None
    low: float | None = None
    high: float | None = None
    mean: float | None = None
    median: float | None = None


class RatingAction(Frozen):
    graded_at: CalendarDate
    firm: str | None = None
    to_grade: str | None = None
    from_grade: str | None = None
    action: str | None = None


class ImpliedMove(Frozen):
    """One figure from the nearest expiry, which is all a summary should ever quote from options."""

    expiry: CalendarDate
    implied_volatility: float
    implied_move_percent: float


class EarningsDetail(Frozen):
    symbol: str
    events: tuple[EarningsEvent, ...] = ()
    revisions: tuple[EpsRevisions, ...] = ()
    price_targets: PriceTargets | None = None
    recent_actions: tuple[RatingAction, ...] = ()
    reactions: tuple[EarningsReaction, ...] = ()
    implied_move: ImpliedMove | None = None


class NewsArticle(Frozen):
    title: str
    url: str
    published: str | None = None
    snippet: str | None = None


class NewsSource(Frozen):
    """An article named rather than reproduced.

    The URL is deliberately absent. A model cannot follow a link, and on a real search the URLs
    were 72% of the tool result while the findings they pointed at were 22%. What a writer needs
    is who said it and when, and the findings carry the attribution already.
    """

    title: str
    published: str | None = None


class NewsFindings(Frozen):
    """What the questions turned up, read and condensed before it reaches the writer.

    `findings` is prose a model wrote about articles other people wrote, so nothing in it was
    measured and no figure inside it may be quoted. The tool says so, the skills say so, and the
    grounding check enforces it by never admitting this tool's numbers to the quotable set.
    """

    questions: tuple[str, ...]
    findings: str
    sources: tuple[NewsSource, ...] = ()
    unanswered: tuple[str, ...] = ()
