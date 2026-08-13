"""A pool stand-in that records the SQL a repository issues and serves canned rows back.

This exercises everything a repository does either side of the database: the parameters it
builds, the jsonb and vector wrapping, and the validation of rows into domain models. The SQL
itself is only meaningfully checked against a real Postgres, which is what test_integration
does.
"""

from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Final, Self, cast

from psycopg.sql import Composable

from orient.store.pool import Pool

Row = Mapping[str, object]


@dataclass(frozen=True, slots=True)
class Executed:
    text: str
    parameters: object


def _render(statement: object) -> str:
    return statement.as_string(None) if isinstance(statement, Composable) else str(statement)


class FakePool:
    def __init__(self, *batches: Sequence[Row]) -> None:
        self.executed: Final[list[Executed]] = []
        self._batches: Final[list[Sequence[Row]]] = list(batches)

    def record(self, statement: object, parameters: object) -> None:
        self.executed.append(Executed(text=_render(statement), parameters=parameters))

    def next_batch(self) -> Sequence[Row]:
        return self._batches.pop(0) if self._batches else ()

    @property
    def only(self) -> Executed:
        """The single statement issued, asserted rather than indexed so a stray write is caught."""
        if len(self.executed) != 1:
            message = f"expected exactly one statement, got {len(self.executed)}"
            raise AssertionError(message)
        return self.executed[0]

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator["_Connection", None]:
        yield _Connection(self)


class _Cursor:
    def __init__(self, pool: FakePool) -> None:
        self._pool: Final = pool

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, statement: object, parameters: object = None) -> Self:
        self._pool.record(statement, parameters)
        return self

    async def executemany(self, statement: object, parameters: Sequence[object]) -> None:
        for row in parameters:
            self._pool.record(statement, row)

    async def fetchone(self) -> Row | None:
        batch: Final = self._pool.next_batch()
        return batch[0] if batch else None

    async def fetchall(self) -> Sequence[Row]:
        return self._pool.next_batch()


class _Connection:
    def __init__(self, pool: FakePool) -> None:
        self._pool: Final = pool

    async def execute(self, statement: object, parameters: object = None) -> _Cursor:
        self._pool.record(statement, parameters)
        return _Cursor(self._pool)

    def cursor(self, row_factory: object = None) -> _Cursor:
        del row_factory
        return _Cursor(self._pool)


def as_pool(fake: FakePool) -> Pool:
    """The repositories take psycopg's concrete pool; the fake matches the slice they use."""
    return cast("Pool", fake)
