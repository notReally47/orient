"""FRED series, validated into domain models at the boundary."""

from collections.abc import Callable
from datetime import date
from functools import partial
from math import isnan
from typing import Final

from anyio import to_thread
from pydantic import TypeAdapter

from orient.domain.models import Observation
from orient.providers._untyped import Records, fred_observations

_OBSERVATIONS: Final = TypeAdapter(tuple[Observation, ...])


def _is_missing(value: object) -> bool:
    """FRED returns a NaN row for holidays and unpublished days rather than omitting the date."""
    return value is None or (isinstance(value, float) and isnan(value))


class FredProvider:
    def __init__(self, fetch: Callable[[str, date, date], Records] = fred_observations) -> None:
        self._fetch: Final = fetch

    async def observations(self, series_id: str, start: date, end: date) -> tuple[Observation, ...]:
        """One series over a window, with the periods the agency has not published yet left out."""
        fetched: Final = await to_thread.run_sync(partial(self._fetch, series_id, start, end))
        published: Final = tuple(record for record in fetched if not _is_missing(record.get("value")))
        return _OBSERVATIONS.validate_python(published)
