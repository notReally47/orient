"""The ports the rest of the system depends on.

Structural, so an implementation never imports this module to satisfy one, and a test passes a
hand-written object without inheriting anything. Parameters are positional-only, because a port
says what a capability is called and takes, not what an implementation names its arguments.

Every method returns a domain type that its implementation validated at the vendor boundary. No
port returns a frame, a record or a vendor payload, and that is what makes an adapter swappable:
everything above sees the same values whichever vendor produced them.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Protocol

from orient.domain.market import (
    EarningsDetail,
    ImpliedMove,
    InstrumentMatch,
    InstrumentProfile,
    MarketContext,
)
from orient.domain.models import Bar, Calendar, CalendarKind, Observation


class Prices(Protocol):
    def daily_bars(self, symbol: str, period: str, /) -> tuple[Bar, ...]: ...

    def multi_bars(self, symbols: Sequence[str], period: str, /) -> Mapping[str, tuple[Bar, ...]]: ...


class Series(Protocol):
    def observations(self, series_id: str, start: date, end: date, /) -> tuple[Observation, ...]: ...


class Discovery(Protocol):
    def by_screen(self, key: str, count: int, /) -> tuple[InstrumentMatch, ...]: ...

    def anything(self, query: str, count: int, /) -> tuple[InstrumentMatch, ...]: ...


class Reference(Protocol):
    def profile(self, symbol: str, /) -> InstrumentProfile: ...

    def implied_move(self, symbol: str, spot: float, today: date, /) -> ImpliedMove | None: ...


class Earnings(Protocol):
    def detail(self, symbol: str, /) -> EarningsDetail: ...


class MarketData(Protocol):
    def backdrop(self) -> MarketContext: ...


class Calendars(Protocol):
    def entries(self, start: date, end: date, kinds: Sequence[CalendarKind] | None = None, /) -> Calendar: ...
