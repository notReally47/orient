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

from orient.domain.models import Listing, Shelf, Summary, SummaryKey, Written
from orient.store.pool import Pool

COLUMNS: Final = (
    "id",
    "symbol",
    "session_date",
    "level",
    "status",
    "thesis",
    "sections",
    "glossary",
    "calendar",
    "holdings",
    "reactions",
    "layout",
    "tiles",
    "signals_snapshot",
    "signals_version",
    "skill_version",
    "trace_id",
    "created_at",
)

LISTING_COLUMNS: Final = ("id", "symbol", "session_date", "level", "thesis")

_ADAPTER: Final = TypeAdapter(Summary)
_ID: Final = TypeAdapter(UUID)
_LISTINGS: Final = TypeAdapter(tuple[Listing, ...])
_COUNT: Final = TypeAdapter(int)
_WRITTEN_ROWS: Final = TypeAdapter(tuple[Written, ...])
_PROJECTION: Final = SQL(", ").join(Identifier(name) for name in COLUMNS)
_LISTING: Final = SQL(", ").join(Identifier(name) for name in LISTING_COLUMNS)

_FIND: Final = SQL("""
    SELECT {columns} FROM summaries
    WHERE symbol = %(symbol)s
      AND session_date = %(session_date)s
      AND level = %(level)s
      AND signals_version = %(signals_version)s
      AND skill_version = %(skill_version)s
""").format(columns=_PROJECTION)

_BY_ID: Final = SQL("SELECT {columns} FROM summaries WHERE id = %(id)s").format(columns=_PROJECTION)

_BROWSE: Final = SQL("""
    SELECT {columns}, count(*) OVER () AS total FROM summaries
    WHERE (%(symbol)s::text IS NULL OR symbol = %(symbol)s)
      AND (%(level)s::text IS NULL OR level = %(level)s)
    ORDER BY session_date DESC, created_at DESC
    LIMIT %(limit)s OFFSET %(offset)s
""").format(columns=_LISTING)

_WRITTEN: Final = SQL("""
    SELECT symbol, count(*) AS count, max(session_date) AS latest
    FROM summaries
    GROUP BY symbol
    ORDER BY count DESC, latest DESC
""")

_INSERT: Final = SQL("""
    INSERT INTO summaries (
        id, symbol, session_date, level, status, thesis, sections, glossary, calendar, holdings,
        reactions, layout, tiles, signals_snapshot, signals_version, skill_version, trace_id
    )
    VALUES (
        %(id)s, %(symbol)s, %(session_date)s, %(level)s, %(status)s, %(thesis)s, %(sections)s, %(glossary)s,
        %(calendar)s, %(holdings)s, %(reactions)s, %(layout)s, %(tiles)s,
        %(signals_snapshot)s, %(signals_version)s, %(skill_version)s, %(trace_id)s
    )
    -- Updating nothing is how a conflicting row still gets returned: RETURNING sees only rows
    -- the statement touched, and DO NOTHING touches none. Without this the caller cannot tell
    -- "stored" from "already there" and goes on to write children against an id that is not here.
    ON CONFLICT (symbol, session_date, level, signals_version, skill_version)
        DO UPDATE SET symbol = EXCLUDED.symbol
    RETURNING id
""")


DEFAULT_HISTORY: Final = 20


class SummaryRepository:
    def __init__(self, pool: Pool) -> None:
        self._pool: Final = pool

    async def find(self, key: SummaryKey) -> Summary | None:
        """The summary already written for exactly this request, if there is one.

        Every field of the key participates, so a summary written against older measurements or an
        older skill is a miss rather than a stale hit.
        """
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

    async def browse(
        self,
        symbol: str | None = None,
        level: str | None = None,
        limit: int = DEFAULT_HISTORY,
        offset: int = 0,
    ) -> Shelf:
        """One screen of what has been written, newest first, with the total.

        Filtering and paging happen here rather than in the caller. A front end that asks for
        everything and keeps the rows it wants has already paid for the ones it throws away, and
        the cost grows with the archive rather than with the screen.
        """
        parameters: Final = {"symbol": symbol, "level": level, "limit": limit, "offset": offset}
        async with self._pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
            _ = await cursor.execute(_BROWSE, parameters)
            rows = await cursor.fetchall()
        return Shelf(
            total=_COUNT.validate_python(rows[0]["total"]) if rows else 0,
            entries=_LISTINGS.validate_python([{name: row[name] for name in LISTING_COLUMNS} for row in rows]),
        )

    async def written(self) -> tuple[Written, ...]:
        """Every instrument with something on file, most written about first."""
        async with self._pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
            _ = await cursor.execute(_WRITTEN)
            rows = await cursor.fetchall()
        return _WRITTEN_ROWS.validate_python(rows)

    async def by_id(self, summary_id: UUID) -> Summary | None:
        """One stored summary, for a reader opening something written earlier."""
        async with self._pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
            _ = await cursor.execute(_BY_ID, {"id": summary_id})
            row = await cursor.fetchone()
        return None if row is None else _ADAPTER.validate_python(row)

    async def add(self, summary: Summary) -> UUID:
        """Stores the summary and answers with the id now on file, which may not be its own.

        A key already present keeps the summary written against it, because the prose a reader
        was shown must not change under them. The id of that row comes back so a caller writing
        claims attaches them to a summary that exists rather than to the one it just built.
        """
        payload: Final = summary.model_dump(mode="json")
        parameters: Final = {
            "id": summary.id,
            "symbol": summary.symbol,
            "session_date": summary.session_date,
            "level": summary.level,
            "status": summary.status,
            "thesis": summary.thesis,
            "sections": Json(payload["sections"]),
            "glossary": Json(payload["glossary"]),
            "calendar": Json(payload["calendar"]),
            "holdings": Json(payload["holdings"]),
            "reactions": Json(payload["reactions"]),
            "layout": Json(payload["layout"]),
            "tiles": Json(payload["tiles"]),
            "signals_snapshot": Json(payload["signals_snapshot"]),
            "signals_version": summary.signals_version,
            "skill_version": summary.skill_version,
            "trace_id": summary.trace_id,
        }
        async with self._pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
            _ = await cursor.execute(_INSERT, parameters)
            row = await cursor.fetchone()
        return summary.id if row is None else _ID.validate_python(row["id"])
