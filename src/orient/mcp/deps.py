"""Everything the tools reach for, passed in rather than imported.

Held as concrete provider classes rather than Protocols on purpose: each provider already takes
its own fetchers as arguments, so a test builds a real provider over fake fetchers and the tool
call runs through the same validation the wire does. A Protocol fake would skip exactly the
layer most likely to be wrong.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from orient.llm.embeddings import EmbeddingClient
from orient.llm.search import SearchClient
from orient.providers.protocols import SeriesProvider
from orient.providers.yahoo import (
    YahooCalendars,
    YahooContext,
    YahooDiscovery,
    YahooEarnings,
    YahooPrices,
    YahooReference,
)
from orient.store.claims import ClaimRepository


def today() -> date:
    return datetime.now(tz=UTC).date()


@dataclass(frozen=True, slots=True)
class ToolDeps:
    prices: YahooPrices
    discovery: YahooDiscovery
    reference: YahooReference
    earnings: YahooEarnings
    context: YahooContext
    calendars: YahooCalendars
    series: SeriesProvider
    search: SearchClient
    claims: ClaimRepository
    embeddings: EmbeddingClient
    clock: Callable[[], date] = today
