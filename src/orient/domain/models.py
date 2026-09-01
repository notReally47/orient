"""The values every layer passes around: tool results, signal output, persisted snapshots.

Models are frozen because a signals snapshot is stored alongside the summary it produced and
re-rendered from months later. Anything able to mutate one in flight would silently rewrite
history that a published summary still cites.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from math import floor, log10
from types import MappingProxyType
from typing import Annotated, Final, Literal, Self, cast
from uuid import UUID

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, model_serializer, model_validator
from pydantic_core.core_schema import SerializerFunctionWrapHandler

AssetClass = Literal["equity", "etf", "index", "future", "currency", "crypto", "fund"]
ReadingLevel = Literal["beginner", "intermediate", "advanced"]
ClaimKind = Literal["attribution", "expectation", "anomaly"]
ClaimResolution = Literal["supported", "contradicted", "unresolved"]
SummaryStatus = Literal["ok", "caveated"]
RunStatus = Literal["running", "ok", "caveated", "failed", "cancelled"]
CalendarKind = Literal["earnings", "economic", "ipo", "split"]

# Bump whenever a measurement changes meaning: it is part of the cache key, so an older
# snapshot stops being served for a request that expects the new one.
SIGNALS_VERSION: Final = "4"

# What earlier versions called a field since renamed, so a stored snapshot still reads back.
RENAMED_SINCE: Final[Mapping[str, Mapping[str, str]]] = MappingProxyType(
    {"1": MappingProxyType({"volume_vs_20_day": "volume_multiple_20d"})}
)
SKILL_VERSION: Final = "1"
RATE_PLACES: Final = 4

LEVEL_CENTS_ABOVE: Final = 100.0
LEVEL_PLACES: Final = 2
# Significant figures, not decimal places: four loses a token priced at 0.000034219 entirely.
LEVEL_FIGURES: Final = 6


class Frozen(BaseModel):
    """Frozen because a stored snapshot is re-rendered months later, and serialised without its
    nulls because a null field tells a reader nothing and invites a model to wonder what failed.

    Every nullable field defaults to None, so a dump round-trips back into the same model. Empty
    collections stay: `sectors: []` says the board was looked for and was not there, which is not
    the same as never having asked.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_serializer(mode="wrap")
    def _without_nulls(self, dump: SerializerFunctionWrapHandler) -> dict[str, object]:
        written: Final = cast("dict[str, object]", dump(self))
        return {key: value for key, value in written.items() if value is not None}


def _drop_time(value: object) -> object:
    """Yahoo dates a daily row with a timestamp, sometimes tz-aware. A daily row is a date."""
    return value.date() if isinstance(value, datetime) else value


CalendarDate = Annotated[date, BeforeValidator(_drop_time)]


def _to_rate(value: float) -> float:
    return round(value, RATE_PLACES)


def _to_level(value: float) -> float:
    magnitude: Final = abs(value)
    if magnitude >= LEVEL_CENTS_ABOVE:
        return round(value, LEVEL_PLACES)
    if magnitude == 0.0:
        return 0.0
    return round(value, LEVEL_FIGURES - 1 - floor(log10(magnitude)))


RATE: Final = "rate"
LEVEL: Final = "level"
SHARE: Final = "share"

Rate = Annotated[float, AfterValidator(_to_rate), RATE]
"""A fraction: 0.0065 is 0.65 percent.

Rounded here rather than by whoever renders it, because a derived figure carries the precision of
the calculation and not of the measurement. A float that arrives as 0.0065161301380911585 is
sixteen digits of arithmetic noise attached to four digits of fact, and the layers below cannot
tell the difference: the writer copies it verbatim into prose, the grounding check accepts it
because it matches, and the stored snapshot keeps it forever. Four places is two decimals of a
percentage, which is the finest thing any of these summaries has cause to say.
"""

Level = Annotated[float, AfterValidator(_to_level), LEVEL]

# Six rather than a rate's four. A contribution is a fraction of a percentage point, and four
# rounds the smallest sector on the board to nothing.
SHARE_PLACES: Final = 6


def _to_share(value: float) -> float:
    return round(value, SHARE_PLACES)


Share = Annotated[float, AfterValidator(_to_share), SHARE]
"""A price, an index level or a yield, at the precision its own size is quoted to.

Rounded here for the same reason a rate is: the arithmetic that produced it carries more digits
than the measurement does. A fixed number of places cannot serve every market, though. Two is
right for an index at 7798.99 and wrong for a currency pair at 1.1732, where it would store 1.17
and leave the writer unable to quote the rate it was given and the grounding check unable to
recognise the true one. The scale therefore follows the magnitude.
"""


class Bar(Frozen):
    session_date: CalendarDate
    open: float
    high: float
    low: float
    close: float
    volume: int


class Observation(Frozen):
    observation_date: CalendarDate
    value: float


class Holding(Frozen):
    """One position inside a fund. Persisted, because a basket's session is explained by what it
    held on the day and today's list is not that list."""

    symbol: str | None = None
    name: str | None = None
    weight: Rate | None = None


class Instrument(Frozen):
    symbol: str
    asset_class: AssetClass
    name: str
    sector: str | None = None
    exchange: str | None = None
    currency: str | None = None


class Returns(Frozen):
    one_day: Rate | None = None
    one_week: Rate | None = None
    one_month: Rate | None = None
    three_month: Rate | None = None
    year_to_date: Rate | None = None


class TrendDistance(Frozen):
    """Close relative to its moving averages, as a fraction: 0.03 is three percent above.

    Distance alone does not say what the trend is doing. A close 8% above a two-hundred day
    average that has been falling for a month is a bounce inside a downtrend; the same 8% above a
    rising one is an uptrend extending. `two_hundred_day_slope` is the change in that average over
    the last month of sessions, which is what separates the two.
    """

    from_50_day: Rate | None = None
    from_200_day: Rate | None = None
    two_hundred_day_slope: Rate | None = None


class SessionShape(Frozen):
    """How the session was actually traded, which a single close-to-close return cannot say.

    Three closes that all read "down 2%" can be three different days: one that gapped down at the
    open and then went nowhere, one that opened flat and sold off all afternoon, and one that fell
    and then bought back most of it into the bell. The split says which, and it is the difference
    between a move that has already happened and one that is still happening.

    `close_location` places the close inside the day's range: 1.0 is a close on the high, 0.0 on
    the low, 0.5 in the middle. `up_down_volume` compares the volume that traded on rising days
    against falling days over the quarter, which is the one thing a volume total cannot tell you
    — which side it was on.
    """

    gap: Rate | None = None
    intraday: Rate | None = None
    gap_share_of_move: float | None = None
    close_location: float | None = None
    range_percent: Rate | None = None
    up_down_volume_60d: float | None = None


class Relative(Frozen):
    """The session's move set against what it moved with.

    A return on its own cannot say whether an instrument did anything. A stock down 3% on a day
    its sector fell 2.8% has not; the same stock down 3% on a day its sector rose 1% has, and
    that is the difference between a summary that explains the day and one that narrates it.

    These are plain differences of same-day returns, not regression residuals. A beta fitted over
    sixty sessions routinely explains a few per cent of the variance of a single name, and a
    "beta-adjusted return" built on it looks precise while resting on nothing. Subtraction rests
    on two measured closes.
    """

    benchmark: str | None = None
    benchmark_return: Rate | None = None
    excess_over_benchmark: Rate | None = None
    peer: str | None = None
    peer_name: str | None = None
    peer_return: Rate | None = None
    excess_over_peer: Rate | None = None


class SectorMove(Frozen):
    """One sector's session, carrying the name a reader knows it by as well as its ticker.

    The whole panel is stored rather than the strongest and weakest few. Five sectors missing
    from the middle makes a session look more polarised than it was, and leaves a chart unable
    to corroborate prose that counts how many rose."""

    symbol: str
    name: str
    change_percent: Rate | None = None
    weight: Rate | None = None
    # `Share`, not `Rate`: rounding this to four places would zero the smallest sector.
    contribution: Share | None = None


def _counted(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


class Breadth(Frozen):
    """A count over a set of named changes, carrying the denominator it was counted from.

    Advancers without the number of things counted means nothing, so the total is derived on the
    way in rather than left to whoever reads it.

    Only the counts. It used to carry the strongest and weakest few as well, which restated rows
    already present and already sorted in the list of sector moves beside it — a fifth of the
    backdrop's length spent saying a second time what the reader could see the first time.
    """

    advancers: int
    decliners: int
    unchanged: int
    total: int = 0

    @model_validator(mode="before")
    @classmethod
    def _derive_the_total(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        entries: Final[Mapping[str, object]] = cast("Mapping[str, object]", value)
        return {
            **entries,
            "total": sum(_counted(entries.get(name)) for name in ("advancers", "decliners", "unchanged")),
        }

    @classmethod
    def over(cls, changes: Mapping[str, float | None]) -> "Breadth":
        """Anything with no change counts as neither, because it has not been measured."""
        measured: Final = {symbol: change for symbol, change in changes.items() if change is not None}
        return cls(
            advancers=sum(1 for change in measured.values() if change > 0),
            decliners=sum(1 for change in measured.values() if change < 0),
            unchanged=sum(1 for change in measured.values() if change == 0),
        )


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


class CrossAsset(Frozen):
    vix: Level | None = None
    vix_change: Rate | None = None
    yield_10y: Level | None = None
    yield_2y: Level | None = None
    high_yield_spread: Level | None = None
    dollar_index: Level | None = None
    crude_oil: Level | None = None
    gold: Level | None = None
    spread_10s2s: Level | None = None

    @model_validator(mode="before")
    @classmethod
    def _derive_the_spread(cls, value: object) -> object:
        """Derived on the way in, so it cannot disagree with the two yields sitting beside it.

        A read-time property would be simpler, but the spread has to reach a prompt and a stored
        snapshot, and a figure the writer cannot see is a figure it is not allowed to quote.
        """
        if not isinstance(value, Mapping):
            return value
        entries: Final[Mapping[str, object]] = cast("Mapping[str, object]", value)
        ten: Final = _number(entries.get("yield_10y"))
        two: Final = _number(entries.get("yield_2y"))
        return {**entries, "spread_10s2s": None if ten is None or two is None else ten - two}


class Signals(Frozen):
    symbol: str
    asset_class: AssetClass | None = None
    currency: str | None = None
    sector: str | None = None
    session_date: date
    close: Level
    returns: Returns
    trend: TrendDistance
    realised_volatility_20d: Rate | None = None
    # A multiple, where 1.0 is an ordinary day. Every other rate here is a change, and reading
    # this as one turns a quiet session into a violent one with nothing downstream to catch it.
    volume_multiple_20d: float | None = None
    high_52_week: Level | None = None
    low_52_week: Level | None = None
    drawdown_from_52_week_high: Rate | None = None
    above_52_week_low: Rate | None = None
    shape: SessionShape | None = None
    relative: Relative | None = None
    breadth: Breadth | None = None
    sectors: tuple[SectorMove, ...] = ()
    sector_market: str | None = None
    cross_asset: CrossAsset | None = None
    version: str = SIGNALS_VERSION

    @model_validator(mode="before")
    @classmethod
    def _read_an_older_snapshot(cls, value: object) -> object:
        """Accept a snapshot written under an earlier version of these measurements.

        `extra="forbid"` is what stops a vendor's renamed column reaching a field silently, and it
        stays. This only relaxes it for rows this code wrote itself under a version it recognises:
        a field renamed since then is moved to its current name, and one that no longer exists is
        dropped rather than refused. Anything carrying the current version is still validated
        strictly, so live data gets no leniency at all.
        """
        if not isinstance(value, Mapping):
            return value
        entries: Final[Mapping[str, object]] = cast("Mapping[str, object]", value)
        stored: Final = entries.get("version")
        if not isinstance(stored, str) or stored == SIGNALS_VERSION:
            return entries
        renamed: Final[Mapping[str, str]] = RENAMED_SINCE.get(stored) or {}
        known: Final = set(cls.model_fields)
        migrated: Final[dict[str, object]] = {}
        for name, held in entries.items():
            field = renamed.get(name, name)
            if field in known:
                migrated[field] = held
        return migrated


class Section(Frozen):
    heading: str
    body: str


class Term(Frozen):
    """A word the summary used and what it means here.

    Defined once and shown wherever the word appears, on the first mention in the prose and in the
    list beneath it. No figures: the prose is checked figure by figure and a definition is not.
    """

    term: str
    meaning: str


CONDITIONAL: Final = ("dollar_index", "gold", "crude_oil")

COMMODITY_SECTORS: Final = frozenset({"Energy", "Basic Materials"})

COMMODITY_CLASSES: Final = frozenset({"future", "currency", "crypto"})


def commodities_bear_on(asset_class: str | None, sector: str | None) -> bool:
    """Whether the dollar and commodity readings belong beside this instrument.

    An unknown class keeps them. Dropping a measurement because the caller did not say what it was
    looking at would strip readings out of summaries written before the class was stored, and the
    safe direction to fail in is one figure too many rather than one too few.
    """
    if asset_class is None:
        return True
    if asset_class in COMMODITY_CLASSES:
        return True
    return asset_class == "equity" and sector in COMMODITY_SECTORS


class CalendarEntry(Frozen):
    """One shape for all four calendars, so the model never has to pick which kind it wants."""

    kind: CalendarKind
    label: str
    symbol: str | None = None
    occurs_at: CalendarDate | None = None
    detail: str | None = None
    eps_estimate: float | None = None
    market_cap: float | None = None


class Calendar(Frozen):
    """What was readable, and how much was not.

    A list short by a third looks exactly like a quiet week unless it says so, and a writer told
    the calendar is incomplete can hedge what to watch where one handed a silent truncation cannot.
    """

    entries: tuple[CalendarEntry, ...] = ()
    unreadable: int = 0


@dataclass(frozen=True, slots=True)
class SummaryKey:
    """Every field that reaches the prompt. A summary served for one key was written for it."""

    symbol: str
    session_date: date
    level: ReadingLevel
    signals_version: str = SIGNALS_VERSION
    skill_version: str = SKILL_VERSION


class EarningsReaction(Frozen):
    """What the market did with a result, the session after it landed.

    Not a line item. Whether revenue grew is a fact about the business; whether the shares fell
    nine per cent the morning after is a fact about how this company's reports are received, and
    only the second is a fact about the trade.
    """

    reported_on: CalendarDate
    next_session_move: Rate


class Panel(Frozen):
    """One figure, and the section it belongs under.

    Carries no data. The name selects a renderer that reads from the snapshot, so a chart can only
    ever show a measured figure — the same rule the prose is held to, applied to the pictures.
    """

    name: str
    section: str


class Summary(Frozen):
    id: UUID
    symbol: str
    session_date: date
    level: ReadingLevel
    status: SummaryStatus
    thesis: str
    sections: tuple[Section, ...]
    signals_snapshot: Signals
    glossary: tuple[Term, ...] = ()
    calendar: tuple[CalendarEntry, ...] = ()
    holdings: tuple[Holding, ...] = ()
    reactions: tuple[EarningsReaction, ...] = ()
    layout: tuple[Panel, ...] = ()
    tiles: tuple[str, ...] = ()
    signals_version: str = SIGNALS_VERSION
    skill_version: str = SKILL_VERSION
    trace_id: str | None = None
    created_at: datetime | None = None

    @property
    def drawable(self) -> frozenset[str]:
        """Every panel this summary holds the measurements to render.

        Asking for a panel with nothing behind it costs nothing and draws nothing.
        `save_summary` reports which of them were dropped, so the writer learns.
        """
        snapshot: Final = self.signals_snapshot
        holds: Final = {
            "price": True,
            "candles": True,
            "against": snapshot.relative is not None,
            "sectors": any(move.change_percent is not None for move in snapshot.sectors),
            "holdings": bool(self.holdings),
            "reactions": bool(self.reactions),
            "shape": snapshot.shape is not None,
            "backdrop": snapshot.cross_asset is not None,
            "calendar": bool(self.calendar),
        }
        return frozenset(name for name, ready in holds.items() if ready)

    @property
    def key(self) -> SummaryKey:
        return SummaryKey(
            symbol=self.symbol,
            session_date=self.session_date,
            level=self.level,
            signals_version=self.signals_version,
            skill_version=self.skill_version,
        )


class Listing(Frozen):
    """A stored summary as a list draws it: enough to recognise, without the prose behind it.

    Reading whole rows to draw a list of headings carries the sections, the glossary and the
    entire signals snapshot for every entry on screen. At a hundred summaries that is megabytes
    fetched to render a page of one-line labels, so the browse path selects these columns and
    stops there.
    """

    id: UUID
    symbol: str
    session_date: date
    level: ReadingLevel
    thesis: str


class Written(Frozen):
    """One instrument that has been summarised before, and how much of it there is.

    What a reader filters a hundred summaries by is which instrument they are for, and the only
    instruments worth offering are the ones something was actually written about.
    """

    symbol: str
    count: int
    latest: date


class Shelf(Frozen):
    """One screen of listings, carrying the size of the whole so a reader can see what is behind.

    `total` counts everything the filters match rather than everything stored, which is what
    makes "showing twelve of a hundred and thirty-seven" a true sentence at any filter.
    """

    total: int = 0
    entries: tuple[Listing, ...] = ()


class Claim(Frozen):
    id: UUID
    summary_id: UUID
    subject_symbol: str
    session_date: date
    kind: ClaimKind
    statement: str
    mentioned_symbols: tuple[str, ...] = ()
    attribution: str | None = None
    target_date: date | None = None
    resolved_by: UUID | None = None
    resolution: ClaimResolution | None = None

    @model_validator(mode="after")
    def _expectation_needs_a_target(self) -> Self:
        """Mirrors the table's CHECK, so a malformed claim fails before it reaches Postgres."""
        if self.kind == "expectation" and self.target_date is None:
            message = "an expectation claim must carry a target_date"
            raise ValueError(message)
        return self
