"""What each repository does either side of the database.

The column-drift tests are the load-bearing ones. Every SELECT projects an explicit column
list into a model with `extra="forbid"`, so a column added to a model without being added to
the projection, or vice versa, breaks reads at runtime. These catch it at `make check` instead.
"""

from datetime import date
from typing import Final, cast
from uuid import UUID, uuid4

import pytest
from pgvector import Vector
from psycopg.types.json import Json

from orient.domain.models import (
    Bar,
    Claim,
    Instrument,
    Returns,
    Section,
    Signals,
    Summary,
    SummaryKey,
    Term,
    TrendDistance,
)
from orient.store import bars as bars_module
from orient.store import claims as claims_module
from orient.store import instruments as instruments_module
from orient.store import summaries as summaries_module
from orient.store.bars import BarRepository
from orient.store.claims import ClaimRepository
from orient.store.instruments import InstrumentRepository
from orient.store.sessions import SessionRepository
from orient.store.summaries import SummaryRepository
from tests.store.fakes import FakePool, as_pool

_SESSION_DATE: Final = date(2026, 8, 12)


def _bar(session_date: date, close: float = 6000.0) -> Bar:
    return Bar(session_date=session_date, open=close, high=close, low=close, close=close, volume=1_000)


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
        thesis="The index gave back Monday's gain.",
        sections=(Section(heading="The big picture", body="It rose."),),
        glossary=(Term(term="breadth", meaning="how many rose versus fell"),),
        signals_snapshot=_signals(),
    )


@pytest.mark.parametrize(
    ("columns", "model"),
    [
        (instruments_module.COLUMNS, Instrument),
        (summaries_module.COLUMNS, Summary),
        (claims_module.COLUMNS, Claim),
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

    parameters = pool.only.bound
    for column in ("sections", "glossary", "signals_snapshot"):
        assert isinstance(parameters[column], Json)


async def test_sessions_store_the_snapshot_as_json_and_read_only_that_column() -> None:
    signals: Final = _signals()
    pool: Final = FakePool()
    await SessionRepository(as_pool(pool)).upsert(signals)

    parameters = pool.only.bound
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
        kind="attribution",
        attribution="the sector fell with it",
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

    parameters = pool.only.bound
    assert isinstance(parameters["embedding"], Vector)


async def test_adding_claims_wraps_each_vector_and_flattens_the_symbol_tuple() -> None:
    """psycopg adapts a list to text[] but not a tuple, and a raw list is not a `vector`."""
    claim: Final = Claim(
        id=uuid4(),
        summary_id=uuid4(),
        subject_symbol="^GSPC",
        session_date=_SESSION_DATE,
        kind="attribution",
        attribution="the sector fell with it",
        statement="Breadth was narrow.",
        mentioned_symbols=("GOOGL", "MSFT"),
    )
    pool: Final = FakePool()
    await ClaimRepository(as_pool(pool)).add((claim,), ([0.1, 0.2],))

    parameters = pool.only.bound
    assert parameters["mentioned_symbols"] == ["GOOGL", "MSFT"]
    assert isinstance(parameters["embedding"], Vector)


async def test_upserting_an_instrument_sends_every_column() -> None:
    """Bound by name, so a column the statement names and the parameters omit is a runtime error.

    Asserting against `model_dump()` instead used to pass and hid exactly that: models serialise
    without their nulls, an index has no sector, and the statement had nothing to bind to it.
    """
    pool: Final = FakePool()

    await InstrumentRepository(as_pool(pool)).add(Instrument(symbol="^GSPC", asset_class="index", name="S&P 500"))

    written: Final = cast("dict[str, object]", pool.only.parameters)
    assert set(written) == {"symbol", "asset_class", "name", "sector", "exchange", "currency"}
    assert written["sector"] is None


async def test_open_claims_are_the_unresolved_ones() -> None:
    pool: Final = FakePool([])
    _ = await ClaimRepository(as_pool(pool)).open_for("^GSPC")
    assert "resolved_by IS NULL" in pool.only.text


async def test_the_bar_projection_is_the_model_minus_the_symbol_it_is_keyed_by() -> None:
    """The symbol is the query's argument, so selecting it back would break `extra="forbid"`."""
    assert set(bars_module.COLUMNS) == set(Bar.model_fields)


async def test_bars_are_read_back_oldest_first() -> None:
    """Every window calculation reads the last row as the latest, whether it came from a vendor or here."""
    pool: Final = FakePool([])
    _ = await BarRepository(as_pool(pool)).between("^GSPC", _SESSION_DATE, _SESSION_DATE)

    assert "ORDER BY session_date" in pool.only.text
    assert pool.only.parameters == {"symbol": "^GSPC", "start": _SESSION_DATE, "end": _SESSION_DATE}


async def test_storing_bars_leaves_the_sessions_already_recorded_alone() -> None:
    """A past session's bar cannot have changed, so a re-fetch must not rewrite what cited it."""
    pool: Final = FakePool()
    await BarRepository(as_pool(pool)).add("^GSPC", (_bar(_SESSION_DATE),))

    assert "ON CONFLICT (symbol, session_date) DO NOTHING" in pool.only.text
    assert pool.only.bound == {"symbol": "^GSPC", **_bar(_SESSION_DATE).model_dump()}


async def test_storing_nothing_issues_no_statement_at_all() -> None:
    pool: Final = FakePool()
    await BarRepository(as_pool(pool)).add("^GSPC", ())

    assert pool.executed == []


async def test_stored_bars_round_trip_back_into_their_model() -> None:
    bar: Final = _bar(_SESSION_DATE)
    pool: Final = FakePool([bar.model_dump(mode="json")])

    assert await BarRepository(as_pool(pool)).between("^GSPC", _SESSION_DATE, _SESSION_DATE) == (bar,)


async def test_an_instrument_round_trips_through_its_projection() -> None:
    instrument: Final = Instrument(symbol="AAPL", asset_class="equity", name="Apple Inc.", sector="Technology")
    pool: Final = FakePool([instrument.model_dump()])

    assert await InstrumentRepository(as_pool(pool)).get("AAPL") == instrument


async def test_a_missing_instrument_is_none_rather_than_an_error() -> None:
    assert await InstrumentRepository(as_pool(FakePool([]))).get("NOPE") is None


async def test_browsing_narrows_pages_and_orders_in_the_query_rather_than_after_it() -> None:
    """An archive grows and a screen does not, so the cut has to happen in SQL."""
    pool: Final = FakePool([])

    _ = await SummaryRepository(as_pool(pool)).browse("^GSPC", "beginner", 12, 24)

    assert pool.only.parameters == {"symbol": "^GSPC", "level": "beginner", "limit": 12, "offset": 24}
    assert "LIMIT %(limit)s OFFSET %(offset)s" in pool.only.text
    assert "ORDER BY session_date DESC, created_at DESC" in pool.only.text


async def test_browsing_without_filters_uses_the_same_statement() -> None:
    """Two statements for one listing is two places for the ordering to drift apart."""
    pool: Final = FakePool([])

    _ = await SummaryRepository(as_pool(pool)).browse()

    assert pool.only.bound["symbol"] is None
    assert pool.only.bound["level"] is None
    assert "IS NULL OR symbol" in pool.only.text


async def test_browsing_reads_only_the_columns_a_list_draws() -> None:
    """Whole rows carry the prose and the snapshot, which a list of headings never shows."""
    pool: Final = FakePool([])

    _ = await SummaryRepository(as_pool(pool)).browse()

    assert "thesis" in pool.only.text
    assert "signals_snapshot" not in pool.only.text
    assert "sections" not in pool.only.text


async def test_a_page_carries_how_many_matched_rather_than_how_many_came_back() -> None:
    """ "Twelve of a hundred and thirty-seven" is only true if the count is of the whole match."""
    row: Final = {
        "id": uuid4(),
        "symbol": "^GSPC",
        "session_date": _SESSION_DATE,
        "level": "beginner",
        "thesis": "It rose",
        "pinned": False,
        "total": 137,
    }

    page: Final = await SummaryRepository(as_pool(FakePool([row]))).browse()

    assert page.total == 137
    assert len(page.entries) == 1
    assert page.entries[0].thesis == "It rose"


async def test_nothing_stored_is_an_empty_page_rather_than_an_error() -> None:
    page: Final = await SummaryRepository(as_pool(FakePool([]))).browse()

    assert page.total == 0
    assert page.entries == ()


async def test_the_instruments_offered_as_filters_are_the_ones_written_about() -> None:
    """Offering a filter that matches nothing is a dead end a reader has to back out of."""
    row: Final = {"symbol": "^GSPC", "count": 14, "latest": _SESSION_DATE}

    written: Final = await SummaryRepository(as_pool(FakePool([row]))).written()

    assert written[0].symbol == "^GSPC"
    assert written[0].count == 14


async def test_a_summary_is_fetched_by_its_own_id_rather_than_scanned_for() -> None:
    pool: Final = FakePool([])
    wanted: Final = uuid4()

    found: Final = await SummaryRepository(as_pool(pool)).by_id(wanted)

    assert found is None
    assert pool.only.parameters == {"id": wanted}


async def test_storing_a_summary_answers_with_the_id_now_on_file() -> None:
    """A conflicting key keeps the row already written, and the caller has to learn which one that
    is: claims hang off the id, so taking the one that was not stored orphans every one of them."""
    already: Final = uuid4()
    pool: Final = FakePool([{"id": already}])
    summary: Final = _summary(uuid4())

    stored: Final = await SummaryRepository(as_pool(pool)).add(summary)

    assert stored == already
    assert "RETURNING id" in pool.only.text
    assert "DO UPDATE" in pool.only.text


async def test_a_summary_stored_for_the_first_time_keeps_its_own_id() -> None:
    pool: Final = FakePool([])
    summary: Final = _summary(uuid4())

    assert await SummaryRepository(as_pool(pool)).add(summary) == summary.id


async def test_a_bar_binds_every_column_the_statement_names() -> None:
    pool: Final = FakePool()

    await BarRepository(as_pool(pool)).add(
        "MU", (Bar(session_date=date(2026, 8, 26), open=1.0, high=2.0, low=0.5, close=1.5, volume=10),)
    )

    written: Final = cast("dict[str, object]", pool.executed[0].parameters)
    assert set(written) == {"symbol", "session_date", "open", "high", "low", "close", "volume"}
