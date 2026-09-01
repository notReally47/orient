"""Finding an instrument from a phrase, a ticker fragment or a predefined screen."""

from collections.abc import Callable, Mapping
from functools import partial
from types import MappingProxyType
from typing import Final

from anyio import to_thread
from pydantic import TypeAdapter

from orient.domain.market import InstrumentMatch
from orient.domain.models import AssetClass
from orient.providers._untyped import Records, yahoo_lookup, yahoo_screen, yahoo_search

DEFAULT_COUNT: Final = 10
LOOKUP_KIND: Final = "all"
"""Yahoo splits ticker lookup by instrument type. A search that only covered equities would miss
the index, the currency pair and the crypto pair the tool says it finds."""

LOOKUP_KINDS: Final[Mapping[AssetClass, str]] = MappingProxyType(
    {
        "equity": "stock",
        "etf": "etf",
        "index": "index",
        "future": "future",
        "currency": "currency",
        "crypto": "cryptocurrency",
        "fund": "mutualfund",
    }
)
"""Which endpoint the ticker lookup answers an asset class from. Yahoo calls an equity a stock."""

REPORTED_KINDS: Final[Mapping[AssetClass, str]] = MappingProxyType(
    {
        "equity": "equity",
        "etf": "etf",
        "index": "index",
        "future": "future",
        "currency": "currency",
        "crypto": "cryptocurrency",
        "fund": "mutualfund",
    }
)
"""What a row reports as its own type, which is a different vocabulary from the endpoint names:
the lookup answers an equity from `stock` but labels the row `equity`, and the name search
shouts every one of them in capitals."""

_MATCHES: Final = TypeAdapter(tuple[InstrumentMatch, ...])


def _named(records: Records) -> Records:
    """A row without a symbol cannot be acted on, and Yahoo occasionally returns one."""
    return tuple(row for row in records if row.get("symbol"))


class YahooDiscovery:
    def __init__(
        self,
        lookup: Callable[[str, str, int], Records] = yahoo_lookup,
        search: Callable[[str, int], Records] = yahoo_search,
        screen: Callable[[str, int], Records] = yahoo_screen,
    ) -> None:
        self._lookup: Final = lookup
        self._search: Final = search
        self._screen: Final = screen

    async def by_screen(self, key: str, count: int = DEFAULT_COUNT) -> tuple[InstrumentMatch, ...]:
        """One of the vendor's own named screens, such as the day's most active names."""
        screened: Final = await to_thread.run_sync(partial(self._screen, key, count))
        return _MATCHES.validate_python(_named(screened))

    async def anything(
        self, query: str, count: int = DEFAULT_COUNT, asset_class: AssetClass | None = None
    ) -> tuple[InstrumentMatch, ...]:
        """Ticker lookup first, then name search, de-duplicated on symbol with order kept.

        A user who types a ticker wants that instrument at the top; a user who types a company
        wants the name match. Running both and merging means the tool never has to ask which.
        That Yahoo answers the two from different endpoints is this adapter's business alone.

        Naming an asset class narrows both halves. The lookup takes it as the endpoint to call,
        which is a real filter rather than one applied afterwards; the name search has no such
        parameter, so its rows are kept only where the class the vendor reports agrees.
        """
        found: Final = (
            *await self._by_ticker(query, count, asset_class),
            *await self._by_name(query, count, asset_class),
        )
        earliest: Final = {match.symbol: match for match in reversed(found)}
        return tuple(earliest[symbol] for symbol in dict.fromkeys(match.symbol for match in found))

    async def _by_ticker(self, query: str, count: int, asset_class: AssetClass | None) -> tuple[InstrumentMatch, ...]:
        kind: Final = LOOKUP_KIND if asset_class is None else LOOKUP_KINDS[asset_class]
        found: Final = await to_thread.run_sync(partial(self._lookup, query, kind, count))
        return _MATCHES.validate_python(_named(found))

    async def _by_name(self, query: str, count: int, asset_class: AssetClass | None) -> tuple[InstrumentMatch, ...]:
        found: Final = await to_thread.run_sync(partial(self._search, query, count))
        matches: Final = _MATCHES.validate_python(_named(found))
        if asset_class is None:
            return matches
        wanted: Final = REPORTED_KINDS[asset_class]
        return tuple(match for match in matches if (match.quote_type or "").lower() == wanted)
