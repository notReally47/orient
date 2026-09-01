"""The narrative layer: what we said, what we attributed it to, and whether it held up.

`similar` is the only reader of the HNSW index and the only place a model's own phrasing
steers retrieval, which is why it is scoped to cross-time analogy rather than general recall.
"""

from collections.abc import Mapping, Sequence
from typing import Final
from uuid import UUID

from pgvector import Vector
from psycopg.rows import dict_row
from psycopg.sql import SQL, Identifier
from pydantic import TypeAdapter

from orient.domain.models import Claim, ClaimResolution
from orient.store.pool import Pool

COLUMNS: Final = (
    "id",
    "summary_id",
    "subject_symbol",
    "session_date",
    "kind",
    "statement",
    "mentioned_symbols",
    "attribution",
    "target_date",
    "resolved_by",
    "resolution",
)

_ADAPTER: Final = TypeAdapter(Claim)
_PROJECTION: Final = SQL(", ").join(Identifier(name) for name in COLUMNS)

_INSERT: Final = SQL("""
    INSERT INTO claims (
        id, summary_id, subject_symbol, session_date, kind, statement,
        mentioned_symbols, attribution, target_date, resolved_by, resolution, embedding
    )
    VALUES (
        %(id)s, %(summary_id)s, %(subject_symbol)s, %(session_date)s, %(kind)s, %(statement)s,
        %(mentioned_symbols)s, %(attribution)s, %(target_date)s, %(resolved_by)s, %(resolution)s, %(embedding)s
    )
""")

_OPEN: Final = SQL("""
    SELECT {columns} FROM claims
    WHERE subject_symbol = %(symbol)s AND resolved_by IS NULL
    ORDER BY session_date DESC
    LIMIT %(limit)s
""").format(columns=_PROJECTION)

_SIMILAR: Final = SQL("""
    SELECT {columns} FROM claims
    WHERE embedding IS NOT NULL
    ORDER BY embedding <=> %(embedding)s
    LIMIT %(limit)s
""").format(columns=_PROJECTION)

_SIMILAR_FOR_SYMBOL: Final = SQL("""
    SELECT {columns} FROM claims
    WHERE embedding IS NOT NULL
      AND (subject_symbol = %(symbol)s OR %(symbol)s = ANY(mentioned_symbols))
    ORDER BY embedding <=> %(embedding)s
    LIMIT %(limit)s
""").format(columns=_PROJECTION)

_SETTLE: Final = SQL("""
    UPDATE claims SET resolved_by = %(resolved_by)s, resolution = %(resolution)s
    WHERE id = ANY(%(ids)s) AND resolved_by IS NULL
""")

DEFAULT_OPEN: Final = 20
DEFAULT_SIMILAR: Final = 10


class ClaimRepository:
    def __init__(self, pool: Pool) -> None:
        self._pool: Final = pool

    async def add(self, claims: Sequence[Claim], embeddings: Sequence[Sequence[float]]) -> None:
        """Embeddings are supplied rather than computed here, so persistence stays free of model calls."""
        if len(claims) != len(embeddings):
            message = f"got {len(claims)} claims and {len(embeddings)} embeddings"
            raise ValueError(message)

        rows: Final = tuple(
            {
                "id": claim.id,
                "summary_id": claim.summary_id,
                "subject_symbol": claim.subject_symbol,
                "session_date": claim.session_date,
                "kind": claim.kind,
                "statement": claim.statement,
                "mentioned_symbols": list(claim.mentioned_symbols),
                "attribution": claim.attribution,
                "target_date": claim.target_date,
                "resolved_by": claim.resolved_by,
                "resolution": claim.resolution,
                "embedding": Vector(list(vector)),
            }
            for claim, vector in zip(claims, embeddings, strict=True)
        )
        async with self._pool.connection() as connection, connection.cursor() as cursor:
            _ = await cursor.executemany(_INSERT, rows)

    async def open_for(self, symbol: str, limit: int = DEFAULT_OPEN) -> tuple[Claim, ...]:
        """Fetched by SQL before the model plans anything, so it cannot forget to ask."""
        async with self._pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
            _ = await cursor.execute(_OPEN, {"symbol": symbol, "limit": limit})
            rows = await cursor.fetchall()
        return tuple(_ADAPTER.validate_python(row) for row in rows)

    async def settle(self, verdicts: Mapping[UUID, ClaimResolution], resolved_by: UUID) -> int:
        """Close out expectations a later summary has judged.

        Nothing wrote these columns before, so `open_for` returned every claim ever made about an
        instrument and the skill's instruction to revisit open expectations could never be
        satisfied. Only unresolved claims are touched, so a verdict cannot be overwritten by a
        later run reading the same history.
        """
        if not verdicts:
            return 0
        rows: Final = tuple(
            {
                "ids": [str(claim) for claim, verdict in verdicts.items() if verdict == resolution],
                "resolution": resolution,
                "resolved_by": resolved_by,
            }
            for resolution in dict.fromkeys(verdicts.values())
        )
        async with self._pool.connection() as connection, connection.cursor() as cursor:
            for row in rows:
                _ = await cursor.execute(_SETTLE, row)
        return len(verdicts)

    async def similar(
        self,
        embedding: Sequence[float],
        symbol: str | None = None,
        limit: int = DEFAULT_SIMILAR,
    ) -> tuple[Claim, ...]:
        """The claims that read most like this one, nearest first.

        Cosine distance over the embedding, which matches on phrasing rather than on measurement.
        Narrowing to a symbol asks what this instrument has been said to do before; leaving it out
        asks the same question across everything written.
        """
        statement: Final = _SIMILAR if symbol is None else _SIMILAR_FOR_SYMBOL
        parameters: Final = {"embedding": Vector(list(embedding)), "limit": limit} | (
            {} if symbol is None else {"symbol": symbol}
        )
        async with self._pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
            _ = await cursor.execute(statement, parameters)
            rows = await cursor.fetchall()
        return tuple(_ADAPTER.validate_python(row) for row in rows)
