"""Yahoo Finance prices, validated into domain models at the boundary."""

from collections.abc import Callable
from typing import Final

from pydantic import TypeAdapter

from orient.domain.models import Bar
from orient.providers._untyped import Records, yahoo_daily_bars

DEFAULT_PERIOD: Final = "1y"

_BARS: Final = TypeAdapter(tuple[Bar, ...])


class YahooProvider:
    """Validation is the whole job: a shape change upstream fails here rather than downstream."""

    def __init__(self, fetch: Callable[[str, str], Records] = yahoo_daily_bars) -> None:
        self._fetch: Final = fetch

    def daily_bars(self, symbol: str, period: str = DEFAULT_PERIOD) -> tuple[Bar, ...]:
        return _BARS.validate_python(self._fetch(symbol, period))
