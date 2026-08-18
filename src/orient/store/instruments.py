"""Instrument reference data."""

from typing import Final

from psycopg.rows import dict_row
from psycopg.sql import SQL, Identifier
from pydantic import TypeAdapter

from orient.domain.models import Instrument
from orient.store.pool import Pool

COLUMNS: Final = ("symbol", "asset_class", "name", "sector", "exchange", "currency")

_ADAPTER: Final = TypeAdapter(Instrument)
_SELECT: Final = SQL("SELECT {columns} FROM instruments WHERE symbol = %(symbol)s").format(
    columns=SQL(", ").join(Identifier(name) for name in COLUMNS)
)
_UPSERT: Final = SQL("""
    INSERT INTO instruments (symbol, asset_class, name, sector, exchange, currency)
    VALUES (%(symbol)s, %(asset_class)s, %(name)s, %(sector)s, %(exchange)s, %(currency)s)
    ON CONFLICT (symbol) DO UPDATE SET
        asset_class  = EXCLUDED.asset_class,
        name         = EXCLUDED.name,
        sector       = EXCLUDED.sector,
        exchange     = EXCLUDED.exchange,
        currency     = EXCLUDED.currency
""")


class InstrumentRepository:
    def __init__(self, pool: Pool) -> None:
        self._pool: Final = pool

    async def upsert(self, instrument: Instrument) -> None:
        async with self._pool.connection() as connection:
            _ = await connection.execute(_UPSERT, instrument.model_dump())

    async def get(self, symbol: str) -> Instrument | None:
        async with self._pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
            _ = await cursor.execute(_SELECT, {"symbol": symbol})
            row = await cursor.fetchone()
        return None if row is None else _ADAPTER.validate_python(row)
