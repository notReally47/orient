"""One pool for the process, with the pgvector codec registered on every connection.

Registration is a per-connection concern rather than a per-query one, so it belongs in the
pool's configure hook. Without it `claims.embedding` round-trips as an opaque string.
"""

from typing import Final, TypeAlias

from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection
from psycopg.rows import TupleRow
from psycopg_pool import AsyncConnectionPool

Pool: TypeAlias = AsyncConnectionPool[AsyncConnection[TupleRow]]

DEFAULT_MIN_SIZE: Final = 1
DEFAULT_MAX_SIZE: Final = 8


async def _configure(connection: AsyncConnection[TupleRow]) -> None:
    await register_vector_async(connection)


def create_pool(dsn: str, *, min_size: int = DEFAULT_MIN_SIZE, max_size: int = DEFAULT_MAX_SIZE) -> Pool:
    """Opened by the caller, so a process that fails to start does not leave connections behind."""
    return AsyncConnectionPool(dsn, min_size=min_size, max_size=max_size, configure=_configure, open=False)
