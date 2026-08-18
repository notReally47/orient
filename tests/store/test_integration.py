"""The SQL itself, against the live Postgres from `make up`.

A fake pool can check the parameters a repository builds but not whether the statement is
valid, whether a projection matches the table, or whether an HNSW search over `vector`
returns anything. Those only fail against a real database, so they are checked here.

Run with `make test-integration`. Skipped when MS_DATABASE_URL is unset.
"""

from collections.abc import AsyncIterator
from datetime import date
from typing import Final
from uuid import uuid4

import pytest
from psycopg import AsyncConnection
from pydantic_settings import BaseSettings, SettingsConfigDict

from orient.domain.models import (
    Bar,
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
from orient.store.bars import BarRepository
from orient.store.claims import ClaimRepository
from orient.store.instruments import InstrumentRepository
from orient.store.pool import Pool, create_pool
from orient.store.runs import RunRepository
from orient.store.sessions import SessionRepository
from orient.store.summaries import SummaryRepository


class _StoreEnv(BaseSettings):
    """Reads .env the same way the application does, so the tests need no exported variables."""

    model_config = SettingsConfigDict(env_prefix="MS_", env_file=".env", extra="ignore")

    database_url: str = ""


DSN: Final = _StoreEnv().database_url
EMBEDDING_WIDTH: Final = 1536

pytestmark = [
    pytest.mark.integration,
    pytest.mark.enable_socket,
    pytest.mark.skipif(not DSN, reason="set MS_DATABASE_URL in .env to run the store integration tests"),
]


PREFLIGHT_TIMEOUT: Final = 10


@pytest.fixture
async def pool() -> AsyncIterator[Pool]:
    # Connect directly first. The pool retries on failure and reports a wrong DSN or a
    # stopped stack as an opaque timeout half a minute later; this surfaces the real error.
    async with await AsyncConnection.connect(DSN, connect_timeout=PREFLIGHT_TIMEOUT):
        pass

    created: Final = create_pool(DSN)
    await created.open(wait=True, timeout=PREFLIGHT_TIMEOUT)
    try:
        yield created
    finally:
        await created.close()


@pytest.fixture
async def symbol(pool: Pool) -> AsyncIterator[str]:
    """Unique per test and removed afterwards.

    These run against the same database the application uses, and `search_knowledge` reads
    every claim in it. Fixture rows left behind would quietly become retrievable evidence.
    """
    generated: Final = f"TEST.{uuid4().hex[:10]}"
    try:
        yield generated
    finally:
        async with pool.connection() as connection:
            # instruments cascades to sessions, summaries and their claims; runs and bars stand alone.
            _ = await connection.execute("DELETE FROM runs WHERE symbol = %s", (generated,))
            _ = await connection.execute("DELETE FROM bars WHERE symbol = %s", (generated,))
            _ = await connection.execute("DELETE FROM instruments WHERE symbol = %s", (generated,))
            _ = await connection.execute("DELETE FROM summaries WHERE symbol = %s", (generated,))


async def _seed_instrument(pool: Pool, symbol: str) -> None:
    await InstrumentRepository(pool).upsert(Instrument(symbol=symbol, asset_class="index", name="Integration fixture"))


def _signals(symbol: str, session_date: date) -> Signals:
    return Signals(
        symbol=symbol,
        session_date=session_date,
        close=6000.0,
        returns=Returns(one_day=0.01, one_week=0.02),
        trend=TrendDistance(from_50_day=0.03, from_200_day=0.08),
        realised_volatility_20d=0.12,
    )


async def test_an_instrument_survives_a_round_trip(pool: Pool, symbol: str) -> None:
    repository: Final = InstrumentRepository(pool)
    instrument: Final = Instrument(
        symbol=symbol, asset_class="equity", name="Round Trip Inc.", sector="Technology", currency="USD"
    )

    await repository.upsert(instrument)

    assert await repository.get(symbol) == instrument


async def test_upserting_an_instrument_twice_updates_rather_than_conflicts(pool: Pool, symbol: str) -> None:
    repository: Final = InstrumentRepository(pool)
    await repository.upsert(Instrument(symbol=symbol, asset_class="equity", name="Before"))
    await repository.upsert(Instrument(symbol=symbol, asset_class="equity", name="After"))

    stored: Final = await repository.get(symbol)
    assert stored is not None
    assert stored.name == "After"


def _bar(symbol_date: date, close: float) -> Bar:
    return Bar(session_date=symbol_date, open=close, high=close, low=close, close=close, volume=1_000)


async def test_bars_are_stored_without_an_instrument_row(pool: Pool, symbol: str) -> None:
    """The backdrop prices a basket of funds this system will never profile, and stores those bars."""
    await BarRepository(pool).add(symbol, (_bar(date(2026, 8, 12), 6000.0),))

    assert len(await BarRepository(pool).since(symbol, date(2026, 8, 1))) == 1


async def test_re_fetching_a_session_leaves_the_bar_a_summary_already_cited(pool: Pool, symbol: str) -> None:
    """A past session's bar cannot have changed, so the second write must not rewrite the first."""
    repository: Final = BarRepository(pool)
    session_date: Final = date(2026, 8, 12)
    await repository.add(symbol, (_bar(session_date, 6000.0),))
    await repository.add(symbol, (_bar(session_date, 1.0),))

    stored: Final = await repository.since(symbol, session_date)
    assert [bar.close for bar in stored] == [6000.0]


async def test_bars_come_back_oldest_first_from_the_requested_date(pool: Pool, symbol: str) -> None:
    repository: Final = BarRepository(pool)
    await repository.add(symbol, tuple(_bar(date(2026, 8, day), float(day)) for day in (12, 10, 11)))

    stored: Final = await repository.since(symbol, date(2026, 8, 11))

    assert [bar.session_date.day for bar in stored] == [11, 12]


async def test_sessions_come_back_newest_first(pool: Pool, symbol: str) -> None:
    await _seed_instrument(pool, symbol)
    repository: Final = SessionRepository(pool)
    for day in (10, 11, 12):
        await repository.upsert(_signals(symbol, date(2026, 8, day)))

    recalled: Final = await repository.recent(symbol, "1")

    assert [entry.session_date.day for entry in recalled] == [12, 11, 10]


async def test_a_signals_snapshot_survives_jsonb(pool: Pool, symbol: str) -> None:
    await _seed_instrument(pool, symbol)
    signals: Final = _signals(symbol, date(2026, 8, 12))
    await SessionRepository(pool).upsert(signals)

    assert (await SessionRepository(pool).recent(symbol, "1"))[0] == signals


async def test_a_summary_is_found_by_its_whole_key(pool: Pool, symbol: str) -> None:
    await _seed_instrument(pool, symbol)
    session_date: Final = date(2026, 8, 12)
    summary: Final = Summary(
        id=uuid4(),
        symbol=symbol,
        session_date=session_date,
        level="beginner",
        status="ok",
        thesis="It gave back Monday's gain.",
        sections=(Section(heading="The big picture", body="It rose."),),
        signals_snapshot=_signals(symbol, session_date),
    )
    repository: Final = SummaryRepository(pool)
    await repository.add(summary)

    found: Final = await repository.find(summary.key)
    assert found is not None
    assert found.sections == summary.sections
    assert found.signals_snapshot == summary.signals_snapshot


async def test_a_different_level_is_a_different_cache_entry(pool: Pool, symbol: str) -> None:
    """The level is in the unique index, so the same day at another level must miss."""
    await _seed_instrument(pool, symbol)
    session_date: Final = date(2026, 8, 12)
    repository: Final = SummaryRepository(pool)
    await repository.add(
        Summary(
            id=uuid4(),
            symbol=symbol,
            session_date=session_date,
            level="beginner",
            status="ok",
            thesis="It gave back Monday's gain.",
            sections=(Section(heading="H", body="B"),),
            signals_snapshot=_signals(symbol, session_date),
        )
    )

    miss: Final = await repository.find(SummaryKey(symbol=symbol, session_date=session_date, level="advanced"))
    assert miss is None


async def test_claims_are_retrievable_by_similarity(pool: Pool, symbol: str) -> None:
    await _seed_instrument(pool, symbol)
    session_date: Final = date(2026, 8, 12)
    summary_id: Final = uuid4()
    await SummaryRepository(pool).add(
        Summary(
            id=summary_id,
            symbol=symbol,
            session_date=session_date,
            level="beginner",
            status="ok",
            thesis="It gave back Monday's gain.",
            sections=(Section(heading="H", body="B"),),
            signals_snapshot=_signals(symbol, session_date),
        )
    )

    near: Final = Claim(
        id=uuid4(),
        summary_id=summary_id,
        subject_symbol=symbol,
        session_date=session_date,
        kind="observation",
        statement="Breadth was narrow while volatility stayed low.",
    )
    far: Final = Claim(
        id=uuid4(),
        summary_id=summary_id,
        subject_symbol=symbol,
        session_date=session_date,
        kind="anomaly",
        statement="No explanation was found for the afternoon reversal.",
    )
    repository: Final = ClaimRepository(pool)
    await repository.add(
        (near, far),
        ([1.0] + [0.0] * (EMBEDDING_WIDTH - 1), [0.0] * (EMBEDDING_WIDTH - 1) + [1.0]),
    )

    ranked: Final = await repository.similar([1.0] + [0.0] * (EMBEDDING_WIDTH - 1), symbol=symbol)

    assert ranked[0].id == near.id


async def test_open_claims_exclude_resolved_ones(pool: Pool, symbol: str) -> None:
    await _seed_instrument(pool, symbol)
    session_date: Final = date(2026, 8, 12)
    summary_id: Final = uuid4()
    await SummaryRepository(pool).add(
        Summary(
            id=summary_id,
            symbol=symbol,
            session_date=session_date,
            level="beginner",
            status="ok",
            thesis="It gave back Monday's gain.",
            sections=(Section(heading="H", body="B"),),
            signals_snapshot=_signals(symbol, session_date),
        )
    )

    resolver: Final = Claim(
        id=uuid4(),
        summary_id=summary_id,
        subject_symbol=symbol,
        session_date=session_date,
        kind="observation",
        statement="The expectation held.",
    )
    expectation: Final = Claim(
        id=uuid4(),
        summary_id=summary_id,
        subject_symbol=symbol,
        session_date=session_date,
        kind="expectation",
        statement="Volatility should compress into the print.",
        target_date=date(2026, 8, 19),
        resolved_by=resolver.id,
        resolution="supported",
    )
    repository: Final = ClaimRepository(pool)
    await repository.add((resolver,), ([0.0] * EMBEDDING_WIDTH,))
    await repository.add((expectation,), ([0.0] * EMBEDDING_WIDTH,))

    open_claims: Final = await repository.open_for(symbol)

    assert [claim.id for claim in open_claims] == [resolver.id]


async def test_a_run_records_its_outcome(pool: Pool, symbol: str) -> None:
    run: Final = Run(
        id=uuid4(),
        symbol=symbol,
        session_date=date(2026, 8, 12),
        level="advanced",
        status="running",
        trace_id="0af7651916cd43dd8448eb211c80319c",
    )
    repository: Final = RunRepository(pool)
    await repository.start(run)
    await repository.finish(
        run.id,
        "ok",
        {"gather": 2.5, "write": 4.0},
        (
            ModelUsage(phase="gather", model="primary-model", calls=3, prompt_tokens=1_200),
            ModelUsage(phase="write", model="primary-model", calls=1, prompt_tokens=8_400),
        ),
    )

    stored: Final = await repository.get(run.id)
    assert stored is not None
    assert stored.status == "ok"
    assert stored.phase_timings["gather"] == pytest.approx(2.5)
    assert {(usage.phase, usage.prompt_tokens) for usage in stored.model_usage} == {
        ("gather", 1_200),
        ("write", 8_400),
    }
    assert stored.finished_at is not None
