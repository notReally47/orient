"""Run records, which are what make a trace in Jaeger correspond to something queryable."""

from collections.abc import Mapping
from typing import Final
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.sql import SQL, Identifier
from psycopg.types.json import Json
from pydantic import TypeAdapter

from orient.domain.models import ModelUsage, Run, RunStatus
from orient.store.pool import Pool

COLUMNS: Final = (
    "id",
    "symbol",
    "session_date",
    "level",
    "status",
    "trace_id",
    "phase_timings",
    "model_usage",
    "started_at",
    "finished_at",
)

_ADAPTER: Final = TypeAdapter(Run)
_PROJECTION: Final = SQL(", ").join(Identifier(name) for name in COLUMNS)

_START: Final = SQL("""
    INSERT INTO runs (id, trace_id, symbol, session_date, level, status, phase_timings, model_usage)
    VALUES (%(id)s, %(trace_id)s, %(symbol)s, %(session_date)s, %(level)s, %(status)s,
            %(phase_timings)s, %(model_usage)s)
""")

_FINISH: Final = SQL("""
    UPDATE runs
    SET status = %(status)s,
        phase_timings = %(phase_timings)s,
        model_usage = %(model_usage)s,
        finished_at = now()
    WHERE id = %(id)s
""")

_GET: Final = SQL("SELECT {columns} FROM runs WHERE id = %(id)s").format(columns=_PROJECTION)


class RunRepository:
    def __init__(self, pool: Pool) -> None:
        self._pool: Final = pool

    async def start(self, run: Run) -> None:
        payload: Final = run.model_dump(mode="json")
        parameters: Final = {
            "id": run.id,
            "trace_id": run.trace_id,
            "symbol": run.symbol,
            "session_date": run.session_date,
            "level": run.level,
            "status": run.status,
            "phase_timings": Json(payload["phase_timings"]),
            "model_usage": Json(payload["model_usage"]),
        }
        async with self._pool.connection() as connection:
            _ = await connection.execute(_START, parameters)

    async def finish(
        self,
        run_id: UUID,
        status: RunStatus,
        phase_timings: Mapping[str, float],
        model_usage: Mapping[str, ModelUsage],
    ) -> None:
        parameters: Final = {
            "id": run_id,
            "status": status,
            "phase_timings": Json(dict(phase_timings)),
            "model_usage": Json({name: usage.model_dump() for name, usage in model_usage.items()}),
        }
        async with self._pool.connection() as connection:
            _ = await connection.execute(_FINISH, parameters)

    async def get(self, run_id: UUID) -> Run | None:
        async with self._pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
            _ = await cursor.execute(_GET, {"id": run_id})
            row = await cursor.fetchone()
        return None if row is None else _ADAPTER.validate_python(row)
