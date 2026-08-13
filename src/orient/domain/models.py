"""The values every layer passes around: tool results, signal output, persisted snapshots.

Models are frozen because a signals snapshot is stored alongside the summary it produced and
re-rendered from months later. Anything able to mutate one in flight would silently rewrite
history that a published summary still cites.
"""

from datetime import date, datetime
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, computed_field, field_validator

AssetClass = Literal["equity", "etf", "index", "future", "currency", "crypto", "fund"]
ReadingLevel = Literal["beginner", "intermediate", "advanced"]
ClaimKind = Literal["observation", "expectation", "anomaly"]

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
