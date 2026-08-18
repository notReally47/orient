"""Everything the tools reach for, passed in rather than imported.

Storage and market data are named by port, so no tool knows which vendor answers it. Tests still
inject the real adapters built over fake fetchers, because structural typing means those objects
satisfy the ports unchanged, and driving the real adapter is what keeps the validation layer under
test.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from orient.llm.embeddings import EmbeddingClient
from orient.llm.search import SearchClient
from orient.providers.protocols import Calendars, Discovery, Earnings, MarketData, Prices, Reference
from orient.store.bars import BarRepository
from orient.store.claims import ClaimRepository


def today() -> date:
    return datetime.now(tz=UTC).date()


@dataclass(frozen=True, slots=True)
class ToolDeps:
    prices: Prices
    discovery: Discovery
    reference: Reference
    earnings: Earnings
    market: MarketData
    calendars: Calendars
    search: SearchClient
    bars: BarRepository
    claims: ClaimRepository
    embeddings: EmbeddingClient
    clock: Callable[[], date] = today
