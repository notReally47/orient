"""The ports the rest of the system depends on.

Structural, so an implementation never imports this module to satisfy one, and a test passes a
hand-written object without inheriting anything. Parameters are positional-only, because a port
says what a capability is called and takes, not what an implementation names its arguments.

Every method returns a domain type that its implementation validated at the vendor boundary. No
port returns a frame, a record or a vendor payload, and that is what makes an adapter swappable:
everything above sees the same values whichever vendor produced them.

Every method is async. Not because vendor SDKs are, they block, but because an implementation is
free not to be: `providers/cache.py` satisfies `Prices` by reading Postgres. A blocking adapter
hands its call to a worker thread itself, which puts that decision next to the code that knows it
blocks rather than repeated in every tool that calls it.

Price windows are inclusive date ranges rather than period strings. A period is always measured
from now, so a port taking one cannot answer a question about a past session, and every figure
above it would silently describe today while claiming to describe the day that was asked for.
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
from orient.domain.models import AssetClass, Bar, Calendar, CalendarKind, Observation, Relative


class Prices(Protocol):
    async def bars(self, symbol: str, start: date, end: date, /) -> tuple[Bar, ...]: ...

    async def multi_bars(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
        /,
    ) -> Mapping[str, tuple[Bar, ...]]: ...


class Series(Protocol):
    async def observations(self, series_id: str, start: date, end: date, /) -> tuple[Observation, ...]: ...


class Discovery(Protocol):
    async def by_screen(self, key: str, count: int, /) -> tuple[InstrumentMatch, ...]: ...

    async def anything(
        self, query: str, count: int, asset_class: AssetClass | None = ..., /
    ) -> tuple[InstrumentMatch, ...]: ...


class Reference(Protocol):
    async def profile(self, symbol: str, /) -> InstrumentProfile: ...

    async def implied_move(self, symbol: str, spot: float, today: date, /) -> ImpliedMove | None: ...


class Earnings(Protocol):
    async def detail(self, symbol: str, /) -> EarningsDetail: ...


class MarketData(Protocol):
    async def backdrop(self, as_of: date, exchange: str | None = ..., /) -> MarketContext: ...

    async def relative(
        self,
        symbol: str,
        session_return: float | None,
        as_of: date,
        asset_class: str | None = ...,
        sector: str | None = ...,
        exchange: str | None = ...,
        /,
    ) -> Relative | None: ...


class Calendars(Protocol):
    async def entries(self, start: date, end: date, kinds: Sequence[CalendarKind] | None = None, /) -> Calendar: ...
