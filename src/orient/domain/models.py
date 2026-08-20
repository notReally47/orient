"""The values every layer passes around: tool results, signal output, persisted snapshots.

Models are frozen because a signals snapshot is stored alongside the summary it produced and
re-rendered from months later. Anything able to mutate one in flight would silently rewrite
history that a published summary still cites.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Final, Literal, Self, cast
from uuid import UUID

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, model_validator

AssetClass = Literal["equity", "etf", "index", "future", "currency", "crypto", "fund"]
ReadingLevel = Literal["beginner", "intermediate", "advanced"]
ClaimKind = Literal["attribution", "expectation", "anomaly"]
ClaimResolution = Literal["supported", "contradicted", "unresolved"]
SummaryStatus = Literal["ok", "caveated"]
RunStatus = Literal["running", "ok", "caveated", "failed", "cancelled"]
CalendarKind = Literal["earnings", "economic", "ipo", "split"]

SIGNALS_VERSION: Final = "1"
SKILL_VERSION: Final = "1"
CONTRIBUTOR_COUNT: Final = 3
RATE_PLACES: Final = 4
LEVEL_PLACES: Final = 2


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _drop_time(value: object) -> object:
    """Yahoo dates a daily row with a timestamp, sometimes tz-aware. A daily row is a date."""
    return value.date() if isinstance(value, datetime) else value


CalendarDate = Annotated[date, BeforeValidator(_drop_time)]


def _to_rate(value: float) -> float:
    return round(value, RATE_PLACES)


def _to_level(value: float) -> float:
    return round(value, LEVEL_PLACES)


Rate = Annotated[float, AfterValidator(_to_rate)]
"""A fraction: 0.0065 is 0.65 percent.

Rounded here rather than by whoever renders it, because a derived figure carries the precision of
the calculation and not of the measurement. A float that arrives as 0.0065161301380911585 is
sixteen digits of arithmetic noise attached to four digits of fact, and the layers below cannot
tell the difference: the writer copies it verbatim into prose, the grounding check accepts it
because it matches, and the stored snapshot keeps it forever. Four places is two decimals of a
percentage, which is the finest thing any of these summaries has cause to say.
"""

Level = Annotated[float, AfterValidator(_to_level)]
"""A price, an index level or a yield, at the two places every venue quotes them to."""


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
    """Close relative to its moving averages, as a fraction: 0.03 is three percent above."""

    from_50_day: Rate | None = None
    from_200_day: Rate | None = None


class Contributor(Frozen):
    symbol: str
    contribution: Rate


def _counted(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


class Breadth(Frozen):
    """A count over a set of named changes, carrying the denominator it was counted from.

    Advancers without the number of things counted means nothing, so the total is derived on the
    way in rather than left to whoever reads it.
    """

    advancers: int
    decliners: int
    unchanged: int
    total: int = 0
    top: tuple[Contributor, ...] = ()
    bottom: tuple[Contributor, ...] = ()

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
    def over(cls, changes: Mapping[str, float | None], count: int = CONTRIBUTOR_COUNT) -> "Breadth":
        """Anything with no change counts as neither, because it has not been measured."""
        measured: Final = {symbol: change for symbol, change in changes.items() if change is not None}
        ranked: Final = sorted(measured.items(), key=lambda entry: -entry[1])
        return cls(
            advancers=sum(1 for change in measured.values() if change > 0),
            decliners=sum(1 for change in measured.values() if change < 0),
            unchanged=sum(1 for change in measured.values() if change == 0),
            top=tuple(Contributor(symbol=symbol, contribution=change) for symbol, change in ranked[:count]),
            bottom=tuple(
                Contributor(symbol=symbol, contribution=change) for symbol, change in reversed(ranked[-count:])
            ),
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
    session_date: date
    close: Level
    returns: Returns
    trend: TrendDistance
    realised_volatility_20d: Rate | None = None
    volume_vs_20_day: Rate | None = None
    drawdown_from_52_week_high: Rate | None = None
    breadth: Breadth | None = None
    cross_asset: CrossAsset | None = None
    version: str = SIGNALS_VERSION


class Section(Frozen):
    heading: str
    body: str


class Annotation(Frozen):
    """A term the writer flagged, defined for the way it used the term rather than generically."""

    term: str
    definition: str


class CalendarEntry(Frozen):
    """One shape for all four calendars, so the model never has to pick which kind it wants."""

    kind: CalendarKind
    label: str
    symbol: str | None = None
    occurs_at: CalendarDate | None = None
    detail: str | None = None


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


class Summary(Frozen):
    id: UUID
    symbol: str
    session_date: date
    level: ReadingLevel
    status: SummaryStatus
    thesis: str
    sections: tuple[Section, ...]
    signals_snapshot: Signals
    annotations: tuple[Annotation, ...] = ()
    calendar: tuple[CalendarEntry, ...] = ()
    signals_version: str = SIGNALS_VERSION
    skill_version: str = SKILL_VERSION
    pinned: bool = False
    trace_id: str | None = None
    created_at: datetime | None = None

    @property
    def key(self) -> SummaryKey:
        return SummaryKey(
            symbol=self.symbol,
            session_date=self.session_date,
            level=self.level,
            signals_version=self.signals_version,
            skill_version=self.skill_version,
        )


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
