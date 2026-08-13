"""The ports the rest of the system depends on.

Structural, so an implementation never imports this module to satisfy it, and a test passes a
hand-written fake without inheriting anything.
"""

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from orient.domain.models import Bar, Observation


class PriceProvider(Protocol):
    def daily_bars(self, symbol: str, period: str) -> tuple[Bar, ...]: ...


class SeriesProvider(Protocol):
    def observations(self, series_id: str, start: date, end: date) -> tuple[Observation, ...]: ...


__all__: Sequence[str] = ("PriceProvider", "SeriesProvider")
