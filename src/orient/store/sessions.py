"""The numeric layer of the knowledge bank: one signals row per instrument per session.

Only the `signals` column is read back. Symbol, date and version are all inside the snapshot,
so returning the row would hand the caller two copies of the same facts that could disagree.
"""

from typing import Final

from psycopg.rows import dict_row
from psycopg.sql import SQL
from psycopg.types.json import Json
from pydantic import TypeAdapter

from orient.domain.models import Signals
from orient.store.pool import Pool

_ADAPTER: Final = TypeAdapter(Signals)
_UPSERT: Final = SQL("""
    INSERT INTO sessions (symbol, session_date, signals_version, signals)
    VALUES (%(symbol)s, %(session_date)s, %(signals_version)s, %(signals)s)
    ON CONFLICT (symbol, session_date, signals_version) DO UPDATE SET signals = EXCLUDED.signals
""")
_RECENT: Final = SQL("""
    SELECT signals FROM sessions
    WHERE symbol = %(symbol)s AND signals_version = %(signals_version)s
    ORDER BY session_date DESC
    LIMIT %(limit)s
""")

DEFAULT_RECALL: Final = 30


class SessionRepository:
    def __init__(self, pool: Pool) -> None:
        self._pool: Final = pool

    async def upsert(self, signals: Signals) -> None:
        parameters: Final = {
            "symbol": signals.symbol,
            "session_date": signals.session_date,
            "signals_version": signals.version,
            "signals": Json(signals.model_dump(mode="json")),
        }
        async with self._pool.connection() as connection:
            _ = await connection.execute(_UPSERT, parameters)

    async def recent(self, symbol: str, version: str, limit: int = DEFAULT_RECALL) -> tuple[Signals, ...]:
        """Newest first. Streaks and ranges are aggregated from these at read time, never stored."""
        parameters: Final = {"symbol": symbol, "signals_version": version, "limit": limit}
        async with self._pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
            _ = await cursor.execute(_RECENT, parameters)
            rows = await cursor.fetchall()
        return tuple(_ADAPTER.validate_python(row["signals"]) for row in rows)
