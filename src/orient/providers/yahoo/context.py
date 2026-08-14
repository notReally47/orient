"""Session state and sector composition.

Sector *performance* is not here. `Sector(...).overview` returns company counts, market cap and
market weight but no returns at all, so performance is derived from sector ETF prices instead
and lives in `domain.context`.
"""

from collections.abc import Callable, Mapping
from typing import Final

from pydantic import TypeAdapter

from orient.domain.market import InstrumentMatch, MarketSession
from orient.providers._untyped import (
    Records,
    yahoo_market_status,
    yahoo_sector_companies,
    yahoo_sector_overview,
)

DEFAULT_REGION: Final = "US"
DEFAULT_COMPANIES: Final = 10

_SESSION: Final = TypeAdapter(MarketSession)
_COMPANIES: Final = TypeAdapter(tuple[InstrumentMatch, ...])


def _session_fields(status: Mapping[str, object]) -> Mapping[str, object]:
    return {
        "name": status.get("name"),
        "status": status.get("status"),
        "opens_at": status.get("open"),
        "closes_at": status.get("close"),
        "timezone": status.get("timezone") or status.get("tz"),
    }


class YahooContext:
    def __init__(
        self,
        status: Callable[[str], Mapping[str, object]] = yahoo_market_status,
        companies: Callable[[str], Records] = yahoo_sector_companies,
        overview: Callable[[str], Mapping[str, object]] = yahoo_sector_overview,
    ) -> None:
        self._status: Final = status
        self._companies: Final = companies
        self._overview: Final = overview

    def session(self, region: str = DEFAULT_REGION) -> MarketSession:
        return _SESSION.validate_python(_session_fields(self._status(region)))

    def sector_companies(self, key: str, count: int = DEFAULT_COMPANIES) -> tuple[InstrumentMatch, ...]:
        """The largest names in a sector, which is what "who moved this sector" needs."""
        rows: Final = tuple(row for row in self._companies(key) if row.get("symbol"))[:count]
        return _COMPANIES.validate_python(
            tuple({"symbol": row["symbol"], "name": row.get("name"), "sector": key} for row in rows)
        )

    def sector_weight(self, key: str) -> float | None:
        """A sector's share of the whole market, for saying whether a big mover mattered."""
        weight: Final = self._overview(key).get("market_weight")
        return float(weight) if isinstance(weight, (int, float)) else None
