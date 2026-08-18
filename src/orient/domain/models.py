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

from pydantic import BaseModel, BeforeValidator, ConfigDict, model_validator

AssetClass = Literal["equity", "etf", "index", "future", "currency", "crypto", "fund"]
ReadingLevel = Literal["beginner", "intermediate", "advanced"]
ClaimKind = Literal["observation", "expectation", "anomaly"]
ClaimResolution = Literal["supported", "contradicted", "unresolved"]
SummaryStatus = Literal["ok", "caveated"]
RunStatus = Literal["running", "ok", "caveated", "failed", "cancelled"]
CalendarKind = Literal["earnings", "economic", "ipo", "split"]
Phase = Literal["cache", "recall", "prefetch", "gather", "write", "check", "extract", "persist"]

SIGNALS_VERSION: Final = "1"
SKILL_VERSION: Final = "1"
CONTRIBUTOR_COUNT: Final = 3


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _drop_time(value: object) -> object:
    """Yahoo dates a daily row with a timestamp, sometimes tz-aware. A daily row is a date."""
    return value.date() if isinstance(value, datetime) else value


CalendarDate = Annotated[date, BeforeValidator(_drop_time)]


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
    one_day: float | None = None
    one_week: float | None = None
    one_month: float | None = None
    three_month: float | None = None
    year_to_date: float | None = None


class TrendDistance(Frozen):
    """Close relative to its moving averages, as a fraction: 0.03 is three percent above."""

    from_50_day: float | None = None
    from_200_day: float | None = None


class Contributor(Frozen):
    symbol: str
    contribution: float


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
    vix: float | None = None
    vix_change: float | None = None
    yield_10y: float | None = None
    yield_2y: float | None = None
    high_yield_spread: float | None = None
    dollar_index: float | None = None
    crude_oil: float | None = None
    gold: float | None = None
    spread_10s2s: float | None = None

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
    close: float
    returns: Returns
    trend: TrendDistance
    realised_volatility_20d: float | None = None
    volume_vs_20_day: float | None = None
    drawdown_from_52_week_high: float | None = None
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


class ModelUsage(Frozen):
    """What one phase spent on one model, so a run says where its tokens went, not only how many."""

    phase: Phase
    model: str
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def plus(self, other: "ModelUsage") -> "ModelUsage":
        return ModelUsage(
            phase=self.phase,
            model=self.model,
            calls=self.calls + other.calls,
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
        )


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
    run_id: UUID | None = None
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


class Run(Frozen):
    id: UUID
    symbol: str
    session_date: date
    level: ReadingLevel
    status: RunStatus
    trace_id: str | None = None
    phase_timings: Mapping[str, float] = {}
    model_usage: tuple[ModelUsage, ...] = ()
    started_at: datetime | None = None
    finished_at: datetime | None = None
