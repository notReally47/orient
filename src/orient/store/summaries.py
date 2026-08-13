"""Stored summaries, which double as the summary cache.

The cache key is the whole `SummaryKey`, so a summary is only ever served back for the exact
inputs it was written for. A field that reaches the prompt and not the key is a bug.
"""

from typing import Final
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.sql import SQL, Identifier
from psycopg.types.json import Json
from pydantic import TypeAdapter

from orient.domain.models import Summary, SummaryKey
from orient.store.pool import Pool

COLUMNS: Final = (
    "id",
    "symbol",
    "session_date",
    "level",
    "status",
    "sections",
    "annotations",
    "signals_snapshot",
    "signals_version",
    "skill_version",
    "pinned",
    "run_id",
    "created_at",
)

_ADAPTER: Final = TypeAdapter(Summary)
_PROJECTION: Final = SQL(", ").join(Identifier(name) for name in COLUMNS)

_FIND: Final = SQL("""
    SELECT {columns} FROM summaries
    WHERE symbol = %(symbol)s
      AND session_date = %(session_date)s
      AND level = %(level)s
      AND signals_version = %(signals_version)s
      AND skill_version = %(skill_version)s
""").format(columns=_PROJECTION)

_RECENT: Final = SQL("""
    SELECT {columns} FROM summaries
    WHERE symbol = %(symbol)s
    ORDER BY session_date DESC, created_at DESC
    LIMIT %(limit)s
""").format(columns=_PROJECTION)

_INSERT: Final = SQL("""
    INSERT INTO summaries (
        id, symbol, session_date, level, status, sections, annotations,
        signals_snapshot, signals_version, skill_version, pinned, run_id
    )
    VALUES (
        %(id)s, %(symbol)s, %(session_date)s, %(level)s, %(status)s, %(sections)s, %(annotations)s,
        %(signals_snapshot)s, %(signals_version)s, %(skill_version)s, %(pinned)s, %(run_id)s
    )
    ON CONFLICT (symbol, session_date, level, signals_version, skill_version) DO NOTHING
""")

_SET_PINNED: Final = SQL("UPDATE summaries SET pinned = %(pinned)s WHERE id = %(id)s")

DEFAULT_HISTORY: Final = 20


class SummaryRepository:
    def __init__(self, pool: Pool) -> None:
        self._pool: Final = pool

    async def find(self, key: SummaryKey) -> Summary | None:
        parameters: Final = {
            "symbol": key.symbol,
            "session_date": key.session_date,
            "level": key.level,
            "signals_version": key.signals_version,
            "skill_version": key.skill_version,
        }
        async with self._pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
            _ = await cursor.execute(_FIND, parameters)
            row = await cursor.fetchone()
        return None if row is None else _ADAPTER.validate_python(row)

    async def recent(self, symbol: str, limit: int = DEFAULT_HISTORY) -> tuple[Summary, ...]:
        async with self._pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
            _ = await cursor.execute(_RECENT, {"symbol": symbol, "limit": limit})
            rows = await cursor.fetchall()
        return tuple(_ADAPTER.validate_python(row) for row in rows)

    async def add(self, summary: Summary) -> None:
        payload: Final = summary.model_dump(mode="json")
        parameters: Final = {
            "id": summary.id,
            "symbol": summary.symbol,
            "session_date": summary.session_date,
            "level": summary.level,
            "status": summary.status,
            "sections": Json(payload["sections"]),
            "annotations": Json(payload["annotations"]),
            "signals_snapshot": Json(payload["signals_snapshot"]),
            "signals_version": summary.signals_version,
            "skill_version": summary.skill_version,
            "pinned": summary.pinned,
            "run_id": summary.run_id,
        }
        async with self._pool.connection() as connection:
            _ = await connection.execute(_INSERT, parameters)

    async def set_pinned(self, summary_id: UUID, *, pinned: bool) -> None:
        async with self._pool.connection() as connection:
            _ = await connection.execute(_SET_PINNED, {"id": summary_id, "pinned": pinned})
