"""What each repository does either side of the database.

The column-drift tests are the load-bearing ones. Every SELECT projects an explicit column
list into a model with `extra="forbid"`, so a column added to a model without being added to
the projection, or vice versa, breaks reads at runtime. These catch it at `make check` instead.
"""

from datetime import date
from typing import Final
from uuid import UUID, uuid4

import pytest
from pgvector import Vector
from psycopg.types.json import Json

from orient.domain.models import (
    Annotation,
    Claim,
    Instrument,
    ModelUsage,
    Returns,
    Run,
    Section,
    Signals,
    Summary,
    SummaryKey,
    TrendDistance,
)
from orient.store import claims as claims_module
from orient.store import instruments as instruments_module
from orient.store import runs as runs_module
from orient.store import summaries as summaries_module
from orient.store.claims import ClaimRepository
from orient.store.instruments import InstrumentRepository
from orient.store.runs import RunRepository
from orient.store.sessions import SessionRepository
from orient.store.summaries import SummaryRepository
from tests.store.fakes import FakePool, as_pool

_SESSION_DATE: Final = date(2026, 8, 12)


def _signals(symbol: str = "^GSPC") -> Signals:
    return Signals(
        symbol=symbol,
        session_date=_SESSION_DATE,
        close=6000.0,
        returns=Returns(one_day=0.01),
        trend=TrendDistance(from_50_day=0.02),
    )


def _summary(summary_id: UUID) -> Summary:
    return Summary(
        id=summary_id,
        symbol="^GSPC",
        session_date=_SESSION_DATE,
        level="beginner",
        status="ok",
        sections=(Section(heading="The big picture", body="It rose."),),
        annotations=(Annotation(term="breadth", definition="how many rose versus fell"),),
        signals_snapshot=_signals(),
    )


@pytest.mark.parametrize(
    ("columns", "model"),
    [
        (instruments_module.COLUMNS, Instrument),
        (summaries_module.COLUMNS, Summary),
        (claims_module.COLUMNS, Claim),
        (runs_module.COLUMNS, Run),
    ],
)
def test_every_projection_matches_its_model_exactly(columns: tuple[str, ...], model: type[Summary]) -> None:
    assert set(columns) == set(model.model_fields)


async def test_finding_a_summary_passes_every_key_field_to_the_query() -> None:
    """A field that reaches the prompt but not the WHERE clause would serve a stale summary."""
    pool: Final = FakePool([])
    key: Final = SummaryKey(symbol="^GSPC", session_date=_SESSION_DATE, level="beginner")

    result: Final = await SummaryRepository(as_pool(pool)).find(key)

    assert result is None
    assert pool.only.parameters == {
        "symbol": "^GSPC",
        "session_date": _SESSION_DATE,
        "level": "beginner",
        "signals_version": key.signals_version,
        "skill_version": key.skill_version,
    }


async def test_a_stored_summary_round_trips_back_into_its_model() -> None:
    summary: Final = _summary(uuid4())
    row: Final = summary.model_dump(mode="json")
    pool: Final = FakePool([row])

    found: Final = await SummaryRepository(as_pool(pool)).find(summary.key)

    assert found == summary


async def test_summary_json_columns_are_wrapped_for_jsonb() -> None:
    """A bare dict is not adapted to jsonb by psycopg, so the wrapping is load-bearing."""
    pool: Final = FakePool()
    await SummaryRepository(as_pool(pool)).add(_summary(uuid4()))

    parameters = pool.only.parameters
    assert isinstance(parameters, dict)
    for column in ("sections", "annotations", "signals_snapshot"):
        assert isinstance(parameters[column], Json)


async def test_sessions_store_the_snapshot_as_json_and_read_only_that_column() -> None:
    signals: Final = _signals()
    pool: Final = FakePool()
    await SessionRepository(as_pool(pool)).upsert(signals)

    parameters = pool.only.parameters
    assert isinstance(parameters, dict)
    assert isinstance(parameters["signals"], Json)
    assert parameters["signals_version"] == signals.version


async def test_recent_sessions_come_back_as_signals() -> None:
    signals: Final = _signals()
    pool: Final = FakePool([{"signals": signals.model_dump(mode="json")}])

    recalled: Final = await SessionRepository(as_pool(pool)).recent("^GSPC", signals.version)

    assert recalled == (signals,)


async def test_claims_and_embeddings_must_line_up() -> None:
    """Silently zipping the shorter of the two would attach vectors to the wrong claims."""
    claim: Final = Claim(
        id=uuid4(),
        summary_id=uuid4(),
        subject_symbol="^GSPC",
        session_date=_SESSION_DATE,
        kind="observation",
        statement="Breadth was narrow.",
    )
    with pytest.raises(ValueError, match="1 claims and 0 embeddings"):
        await ClaimRepository(as_pool(FakePool())).add((claim,), ())


async def test_a_symbol_narrows_the_similarity_search_to_claims_that_mention_it() -> None:
    pool: Final = FakePool([], [])
    repository: Final = ClaimRepository(as_pool(pool))

    _ = await repository.similar([0.1, 0.2])
    _ = await repository.similar([0.1, 0.2], symbol="GOOGL")

    unfiltered, filtered = pool.executed
    assert "ANY(mentioned_symbols)" not in unfiltered.text
    assert "ANY(mentioned_symbols)" in filtered.text


async def test_a_query_embedding_is_wrapped_for_the_vector_column() -> None:
    """A bare list of floats is not adapted to `vector`, so the wrapping decides whether it binds."""
    pool: Final = FakePool([])
    _ = await ClaimRepository(as_pool(pool)).similar([0.1, 0.2])

    parameters = pool.only.parameters
    assert isinstance(parameters, dict)
    assert isinstance(parameters["embedding"], Vector)


async def test_adding_claims_wraps_each_vector_and_flattens_the_symbol_tuple() -> None:
    """psycopg adapts a list to text[] but not a tuple, and a raw list is not a `vector`."""
    claim: Final = Claim(
        id=uuid4(),
        summary_id=uuid4(),
        subject_symbol="^GSPC",
        session_date=_SESSION_DATE,
        kind="observation",
        statement="Breadth was narrow.",
        mentioned_symbols=("GOOGL", "MSFT"),
    )
    pool: Final = FakePool()
    await ClaimRepository(as_pool(pool)).add((claim,), ([0.1, 0.2],))

    parameters = pool.only.parameters
    assert isinstance(parameters, dict)
    assert parameters["mentioned_symbols"] == ["GOOGL", "MSFT"]
    assert isinstance(parameters["embedding"], Vector)


async def test_upserting_an_instrument_sends_every_column() -> None:
    instrument: Final = Instrument(symbol="AAPL", asset_class="equity", name="Apple Inc.")
    pool: Final = FakePool()
    await InstrumentRepository(as_pool(pool)).upsert(instrument)

    assert pool.only.parameters == instrument.model_dump()


async def test_starting_a_run_serialises_both_json_columns() -> None:
    run: Final = Run(id=uuid4(), symbol="^GSPC", session_date=_SESSION_DATE, level="beginner", status="running")
    pool: Final = FakePool()
    await RunRepository(as_pool(pool)).start(run)

    parameters = pool.only.parameters
    assert isinstance(parameters, dict)
    assert isinstance(parameters["phase_timings"], Json)
    assert isinstance(parameters["model_usage"], Json)


async def test_pinning_targets_a_single_summary_by_id() -> None:
    summary_id: Final = uuid4()
    pool: Final = FakePool()
    await SummaryRepository(as_pool(pool)).set_pinned(summary_id, pinned=True)

    assert pool.only.parameters == {"id": summary_id, "pinned": True}


async def test_open_claims_are_the_unresolved_ones() -> None:
    pool: Final = FakePool([])
    _ = await ClaimRepository(as_pool(pool)).open_for("^GSPC")
    assert "resolved_by IS NULL" in pool.only.text


async def test_finishing_a_run_serialises_its_usage_map() -> None:
    run_id: Final = uuid4()
    pool: Final = FakePool()

    await RunRepository(as_pool(pool)).finish(
        run_id,
        "ok",
        {"gather": 1.5},
        {"primary-model": ModelUsage(calls=2, prompt_tokens=100, completion_tokens=50)},
    )

    parameters = pool.only.parameters
    assert isinstance(parameters, dict)
    assert isinstance(parameters["model_usage"], Json)
    assert parameters["status"] == "ok"


async def test_an_instrument_round_trips_through_its_projection() -> None:
    instrument: Final = Instrument(symbol="AAPL", asset_class="equity", name="Apple Inc.", sector="Technology")
    pool: Final = FakePool([instrument.model_dump()])

    assert await InstrumentRepository(as_pool(pool)).get("AAPL") == instrument


async def test_a_missing_instrument_is_none_rather_than_an_error() -> None:
    assert await InstrumentRepository(as_pool(FakePool([]))).get("NOPE") is None


async def test_a_run_row_round_trips_back_into_its_model() -> None:
    run: Final = Run(
        id=uuid4(),
        symbol="^GSPC",
        session_date=_SESSION_DATE,
        level="advanced",
        status="running",
        trace_id="abc123",
    )
    pool: Final = FakePool([run.model_dump(mode="json")])

    assert await RunRepository(as_pool(pool)).get(run.id) == run
