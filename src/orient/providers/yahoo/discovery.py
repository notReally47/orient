"""Finding an instrument from a phrase, a ticker fragment or a predefined screen."""

from collections.abc import Callable
from typing import Final

from pydantic import TypeAdapter

from orient.domain.market import InstrumentMatch
from orient.providers._untyped import Records, yahoo_lookup, yahoo_screen, yahoo_search

DEFAULT_COUNT: Final = 10
LOOKUP_KIND: Final = "all"
"""Yahoo splits ticker lookup by instrument type. A search that only covered equities would miss
the index, the currency pair and the crypto pair the tool says it finds."""

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

    def by_screen(self, key: str, count: int = DEFAULT_COUNT) -> tuple[InstrumentMatch, ...]:
        return _MATCHES.validate_python(_named(self._screen(key, count)))

    def anything(self, query: str, count: int = DEFAULT_COUNT) -> tuple[InstrumentMatch, ...]:
        """Ticker lookup first, then name search, de-duplicated on symbol with order kept.

        A user who types a ticker wants that instrument at the top; a user who types a company
        wants the name match. Running both and merging means the tool never has to ask which.
        That Yahoo answers the two from different endpoints is this adapter's business alone.
        """
        found: Final = (*self._by_ticker(query, count), *self._by_name(query, count))
        earliest: Final = {match.symbol: match for match in reversed(found)}
        return tuple(earliest[symbol] for symbol in dict.fromkeys(match.symbol for match in found))

    def _by_ticker(self, query: str, count: int) -> tuple[InstrumentMatch, ...]:
        return _MATCHES.validate_python(_named(self._lookup(query, LOOKUP_KIND, count)))

    def _by_name(self, query: str, count: int) -> tuple[InstrumentMatch, ...]:
        return _MATCHES.validate_python(_named(self._search(query, count)))
