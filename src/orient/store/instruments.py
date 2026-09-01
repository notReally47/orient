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
    ON CONFLICT (symbol) DO NOTHING
""")


class InstrumentRepository:
    def __init__(self, pool: Pool) -> None:
        self._pool: Final = pool

    async def add(self, instrument: Instrument) -> None:
        """The first description of an instrument wins, and later ones are discarded.

        Name and sector are mutable at the vendor. Taking a new one would move the reference
        data an already published summary was written against, so a symbol already on file is
        left as it is rather than updated."""
        async with self._pool.connection() as connection:
            _ = await connection.execute(
                _UPSERT,
                {
                    "symbol": instrument.symbol,
                    "asset_class": instrument.asset_class,
                    "name": instrument.name,
                    "sector": instrument.sector,
                    "exchange": instrument.exchange,
                    "currency": instrument.currency,
                },
            )

    async def get(self, symbol: str) -> Instrument | None:
        """What is known about one instrument, or nothing if it has never been summarised."""
        async with self._pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
            _ = await cursor.execute(_SELECT, {"symbol": symbol})
            row = await cursor.fetchone()
        return None if row is None else _ADAPTER.validate_python(row)
