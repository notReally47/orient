"""The numeric layer of the knowledge bank: one signals row per instrument per session.

Only the `signals` column is read back. Symbol, date and version are all inside the snapshot,
so returning the row would hand the caller two copies of the same facts that could disagree.
"""

from typing import Final, NamedTuple

from pgvector import Vector
from psycopg.rows import dict_row
from psycopg.sql import SQL
from psycopg.types.json import Json
from pydantic import TypeAdapter

from orient.domain import resemblance
from orient.domain.models import Signals
from orient.store.pool import Pool

_ADAPTER: Final = TypeAdapter(Signals)
_RETURN: Final[TypeAdapter[float | None]] = TypeAdapter(float | None)
_UPSERT: Final = SQL("""
    INSERT INTO sessions (symbol, session_date, signals_version, signals, shape)
    VALUES (%(symbol)s, %(session_date)s, %(signals_version)s, %(signals)s, %(shape)s)
    ON CONFLICT (symbol, session_date, signals_version)
        DO UPDATE SET signals = EXCLUDED.signals, shape = EXCLUDED.shape
""")

_RESEMBLING: Final = SQL("""
    SELECT past.signals,
           (SELECT next.signals -> 'returns' ->> 'one_day'
              FROM sessions next
             WHERE next.symbol = past.symbol
               AND next.signals_version = past.signals_version
               AND next.session_date > past.session_date
             ORDER BY next.session_date
             LIMIT 1) AS next_day
      FROM sessions past
     WHERE past.shape IS NOT NULL
       AND past.signals_version = %(signals_version)s
       AND NOT (past.symbol = %(symbol)s AND past.session_date = %(session_date)s)
       AND (%(only)s::text IS NULL OR past.symbol = %(only)s)
     ORDER BY past.shape <-> %(shape)s
     LIMIT %(limit)s
""")
_RECENT: Final = SQL("""
    SELECT signals FROM sessions
    WHERE symbol = %(symbol)s AND signals_version = %(signals_version)s
    ORDER BY session_date DESC
    LIMIT %(limit)s
""")

DEFAULT_RECALL: Final = 30
DEFAULT_RESEMBLING: Final = 8


class Resembling(NamedTuple):
    """A past session that looked like this one, and what the session after it did."""

    signals: Signals
    next_day: float | None


class SessionRepository:
    def __init__(self, pool: Pool) -> None:
        self._pool: Final = pool

    async def upsert(self, signals: Signals) -> None:
        """Store a session, replacing any snapshot already held for the same measurements version.

        The shape vector is derived here rather than passed in, so every stored session is
        searchable by resemblance whatever route wrote it.
        """
        parameters: Final = {
            "symbol": signals.symbol,
            "session_date": signals.session_date,
            "signals_version": signals.version,
            "signals": Json(signals.model_dump(mode="json")),
            "shape": Vector(list(resemblance.vector(signals))),
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

    async def resembling(
        self,
        signals: Signals,
        only: str | None = None,
        limit: int = DEFAULT_RESEMBLING,
    ) -> tuple[Resembling, ...]:
        """The stored sessions closest to this one, nearest first, with what followed each.

        `only` restricts to one instrument; left unset the search runs across every instrument
        ever summarised, which is the point of a scale-free vector. The session being asked about
        is excluded, since a session always resembles itself perfectly and says nothing by it.
        """
        parameters: Final = {
            "symbol": signals.symbol,
            "session_date": signals.session_date,
            "signals_version": signals.version,
            "shape": Vector(list(resemblance.vector(signals))),
            "only": only,
            "limit": limit,
        }
        async with self._pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
            _ = await cursor.execute(_RESEMBLING, parameters)
            rows = await cursor.fetchall()
        return tuple(
            Resembling(
                signals=_ADAPTER.validate_python(row["signals"]),
                next_day=_RETURN.validate_python(row["next_day"]),
            )
            for row in rows
        )
