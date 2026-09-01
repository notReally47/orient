"""The schema against the code that writes into it.

Two widths are declared in SQL and computed in Python, and nothing connects them at runtime: a
vector of the wrong length is refused by Postgres at insert time, which is the middle of a run
that has already spent every model call it is going to spend. These read the file instead.
"""

import re
from pathlib import Path
from typing import Final

from orient.config import Settings
from orient.domain import resemblance
from orient.store.summaries import COLUMNS

SCHEMA: Final = Path("db/migrations/0001_schema.sql")


def _schema() -> str:
    return SCHEMA.read_text(encoding="utf-8")


def _width(column: str) -> int:
    found: Final = re.search(rf"^\s*{column}\s+vector\((\d+)\)", _schema(), re.MULTILINE)
    assert found is not None, f"{column} is not declared as a vector in {SCHEMA}"
    return int(found.group(1))


def test_the_session_vector_is_as_wide_as_the_features_it_is_built_from() -> None:
    """Appending to `FEATURES` without widening the column fails at the insert, after the run has
    paid for everything it did."""
    assert _width("shape") == resemblance.DIMENSIONS


def test_the_claim_embedding_is_as_wide_as_the_model_that_fills_it() -> None:
    settings: Final = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]  # defaults are the contract here

    assert _width("embedding") == settings.embedding_dimensions


def test_every_column_the_repository_reads_back_exists_in_the_schema() -> None:
    """A projection naming a column the schema dropped is a 500 on the browse path, and the only
    place the two lists meet is a query nobody runs offline."""
    table: Final = _schema().partition("CREATE TABLE IF NOT EXISTS summaries")[2].partition(");")[0]

    for column in COLUMNS:
        assert re.search(rf"^\s*{column}\s", table, re.MULTILINE), f"summaries has no column {column!r}"
