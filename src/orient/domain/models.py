"""The values every layer passes around: tool results, signal output, persisted snapshots.

Models are frozen because a signals snapshot is stored alongside the summary it produced and
re-rendered from months later. Anything able to mutate one in flight would silently rewrite
history that a published summary still cites.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, computed_field, field_validator, model_validator

AssetClass = Literal["equity", "etf", "index", "future", "currency", "crypto", "fund"]
ReadingLevel = Literal["beginner", "intermediate", "advanced"]
ClaimKind = Literal["observation", "expectation", "anomaly"]
ClaimResolution = Literal["supported", "contradicted", "unresolved"]
SummaryStatus = Literal["ok", "caveated"]
RunStatus = Literal["running", "ok", "caveated", "failed", "cancelled"]

SIGNALS_VERSION: Final = "1"
SKILL_VERSION: Final = "1"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Bar(_Frozen):
    session_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int

    @field_validator("session_date", mode="before")
    @classmethod
    def _drop_time(cls, value: object) -> object:
        """Price feeds hand back midnight timestamps; a daily bar is a date."""
        return value.date() if isinstance(value, datetime) else value


class Observation(_Frozen):
    observation_date: date
    value: float

    @field_validator("observation_date", mode="before")
    @classmethod
    def _drop_time(cls, value: object) -> object:
        return value.date() if isinstance(value, datetime) else value


class Instrument(_Frozen):
    symbol: str
    asset_class: AssetClass
    name: str
    sector: str | None = None
    exchange: str | None = None
    currency: str | None = None


class Returns(_Frozen):
    one_day: float | None = None
    one_week: float | None = None
    one_month: float | None = None
    three_month: float | None = None
    year_to_date: float | None = None


class TrendDistance(_Frozen):
    """Close relative to its moving averages, as a fraction: 0.03 is three percent above."""

    from_50_day: float | None = None
    from_200_day: float | None = None


class Contributor(_Frozen):
    symbol: str
    contribution: float


class Breadth(_Frozen):
    advancers: int
    decliners: int
    unchanged: int
    top: tuple[Contributor, ...] = ()
    bottom: tuple[Contributor, ...] = ()


class CrossAsset(_Frozen):
    vix: float | None = None
    vix_change: float | None = None
    yield_10y: float | None = None
    yield_2y: float | None = None
    high_yield_spread: float | None = None
    dollar_index: float | None = None
    crude_oil: float | None = None
    gold: float | None = None

    @computed_field
    @property
    def spread_10s2s(self) -> float | None:
        """Derived rather than stored, so it can never disagree with the two yields beside it."""
        if self.yield_10y is None or self.yield_2y is None:
            return None
        return self.yield_10y - self.yield_2y


class Signals(_Frozen):
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


class Section(_Frozen):
    heading: str
    body: str


class Annotation(_Frozen):
    """A term the writer flagged, defined for the way it used the term rather than generically."""

    term: str
    definition: str


class ModelUsage(_Frozen):
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True, slots=True)
class SummaryKey:
    """Every field that reaches the prompt. A summary served for one key was written for it."""

    symbol: str
    session_date: date
    level: ReadingLevel
    signals_version: str = SIGNALS_VERSION
    skill_version: str = SKILL_VERSION


class Summary(_Frozen):
    id: UUID
    symbol: str
    session_date: date
    level: ReadingLevel
    status: SummaryStatus
    sections: tuple[Section, ...]
    signals_snapshot: Signals
    annotations: tuple[Annotation, ...] = ()
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


class Claim(_Frozen):
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


class Run(_Frozen):
    id: UUID
    symbol: str
    session_date: date
    level: ReadingLevel
    status: RunStatus
    trace_id: str | None = None
    phase_timings: Mapping[str, float] = {}
    model_usage: Mapping[str, ModelUsage] = {}
    started_at: datetime | None = None
    finished_at: datetime | None = None
