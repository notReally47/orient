"""Daily bars, the one thing here that is a fact rather than a derivation.

A bar for a past session never changes, so one row per instrument per trading day serves every
summary at every reading level. That is what lets the price cache read from here instead of
spending a request, and what lets a chart be drawn without asking a vendor anything.
"""

from collections.abc import Sequence
from datetime import date
from typing import Final

from psycopg.rows import dict_row
from psycopg.sql import SQL, Identifier
from pydantic import TypeAdapter

from orient.domain.models import Bar
from orient.store.pool import Pool

COLUMNS: Final = ("session_date", "open", "high", "low", "close", "volume")

_ADAPTER: Final = TypeAdapter(tuple[Bar, ...])
_PROJECTION: Final = SQL(", ").join(Identifier(name) for name in COLUMNS)

_BETWEEN: Final = SQL("""
    SELECT {columns} FROM bars
    WHERE symbol = %(symbol)s AND session_date BETWEEN %(start)s AND %(end)s
    ORDER BY session_date
""").format(columns=_PROJECTION)

_UPSERT: Final = SQL("""
    INSERT INTO bars (symbol, session_date, open, high, low, close, volume)
    VALUES (%(symbol)s, %(session_date)s, %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s)
    ON CONFLICT (symbol, session_date) DO NOTHING
""")


class BarRepository:
    def __init__(self, pool: Pool) -> None:
        self._pool: Final = pool

    async def between(self, symbol: str, start: date, end: date) -> tuple[Bar, ...]:
        """Oldest first, which is the order every window calculation reads them in."""
        parameters: Final = {"symbol": symbol, "start": start, "end": end}
        async with self._pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
            _ = await cursor.execute(_BETWEEN, parameters)
            rows = await cursor.fetchall()
        return _ADAPTER.validate_python(rows)

    async def add(self, symbol: str, bars: Sequence[Bar]) -> None:
        """Existing rows are left alone, because a past session's bar cannot have changed."""
        if not bars:
            return
        parameters: Final = [
            {
                "symbol": symbol,
                "session_date": bar.session_date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }
            for bar in bars
        ]
        async with self._pool.connection() as connection, connection.cursor() as cursor:
            await cursor.executemany(_UPSERT, parameters)
