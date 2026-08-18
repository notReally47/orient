"""A whole run, over a scripted model and the real tool server.

These are the control-flow tests: how many times the loop goes round, what it does when a draft
does not reconcile, what it writes when it gives up, and what the caller is told at each point. The
prefetch, the schemas and the structured content are real throughout, so a run that would fail on
the wire fails here.
"""

from datetime import timedelta
from typing import Final
from uuid import UUID

from orient.domain.models import (
    Annotation,
    ReadingLevel,
    Returns,
    Section,
    Signals,
    Summary,
    TrendDistance,
)
from orient.llm.chat import Rejected, ToolCall, Unavailable
from orient.orchestrator.agent import RunRequest, run
from orient.orchestrator.events import (
    DraftRejected,
    RunFailed,
    RunFinished,
    ToolFinished,
    ToolStarted,
)
from tests.orchestrator.fakes import (
    EXTRACTED,
    GROUNDED,
    SESSION_DATE,
    UNGROUNDED,
    Recorder,
    RefusingTools,
    ScriptedChat,
    Store,
    answered,
    calls_calendar,
    run_deps,
)

SYMBOL: Final = "AAPL"


def _request(level: ReadingLevel = "beginner") -> RunRequest:
    return RunRequest(symbol=SYMBOL, session_date=SESSION_DATE, level=level)


def _stored_summary() -> Summary:
    return Summary(
        id=UUID(int=99),
        symbol=SYMBOL,
        session_date=SESSION_DATE,
        level="beginner",
        status="ok",
        thesis="Apple gave back Monday's gain",
        sections=(Section(heading="The big picture", body="It fell with technology."),),
        signals_snapshot=Signals(
            symbol=SYMBOL,
            session_date=SESSION_DATE,
            close=100.0,
            returns=Returns(),
            trend=TrendDistance(),
        ),
        annotations=(Annotation(term="breadth", definition="how many rose against how many fell"),),
    )


async def test_a_cached_summary_is_replayed_without_a_model_call() -> None:
    """The key covers everything reaching the prompt, so a hit is the same summary, not a similar one."""
    store: Final = Store(cached=_stored_summary())
    chat: Final = ScriptedChat()
    events: Final = Recorder()

    async with run_deps(chat, store) as deps:
        await run(_request(), deps, events)

    assert chat.asked == []
    assert store.runs == []
    assert events.kinds() == (
        "run_started",
        "phase_started",
        "phase_finished",
        "cache_hit",
        "thesis_ready",
        "section_ready",
        "run_finished",
    )


async def test_a_summary_for_another_level_is_not_a_hit() -> None:
    store: Final = Store(cached=_stored_summary())
    chat: Final = ScriptedChat(answered("nothing to add"), answered(GROUNDED), answered(EXTRACTED))
    events: Final = Recorder()

    async with run_deps(chat, store) as deps:
        await run(_request(level="advanced"), deps, events)

    assert "cache_hit" not in events.kinds()
    assert store.summaries[0].level == "advanced"


async def test_a_run_gathers_writes_extracts_and_persists() -> None:
    store: Final = Store()
    chat: Final = ScriptedChat(
        answered(calls=calls_calendar()),
        answered("The calendar is clear."),
        answered(GROUNDED),
        answered(EXTRACTED),
    )
    events: Final = Recorder()

    async with run_deps(chat, store) as deps:
        await run(_request(), deps, events)

    stored: Final = store.summaries[0]
    assert stored.status == "ok"
    assert stored.thesis == "Apple gave back Monday's gain alongside its sector"
    assert [section.heading for section in stored.sections] == ["The big picture", "What moved, and why"]
    assert stored.annotations[0].term == "breadth"

    assert store.instruments[0].asset_class == "equity"
    assert store.instruments[0].name == "Apple Inc."
    assert store.sessions[0].symbol == SYMBOL
    assert [claim.kind for claim in store.claims] == ["observation", "expectation"]
    assert len(store.vectors) == len(store.claims)
    assert events.only(RunFinished)[0].status == "ok"


async def test_an_expectation_with_no_date_is_due_at_the_end_of_the_week_it_names() -> None:
    """The section it comes from is "what to watch this week", so that is when it can be judged."""
    store: Final = Store()
    chat: Final = ScriptedChat(answered("nothing to add"), answered(GROUNDED), answered(EXTRACTED))

    async with run_deps(chat, store) as deps:
        await run(_request(), deps, Recorder())

    expectation: Final = next(claim for claim in store.claims if claim.kind == "expectation")
    assert expectation.target_date == SESSION_DATE + timedelta(days=7)


async def test_the_prefetch_runs_before_the_model_is_asked_anything() -> None:
    """Signals, context and profile are needed for every summary, so choosing them costs a round trip."""
    store: Final = Store()
    chat: Final = ScriptedChat(answered("nothing to add"), answered(GROUNDED), answered(EXTRACTED))
    events: Final = Recorder()

    async with run_deps(chat, store) as deps:
        await run(_request(), deps, events)

    prefetched: Final = tuple(event.tool for event in events.only(ToolStarted))[:4]
    assert prefetched == (
        "compute_instrument_signals",
        "get_instrument_profile",
        "get_market_context",
        "get_calendar",
    )
    assert "measured" in chat.asked[0].last


async def test_each_phase_names_the_guardrails_it_wants() -> None:
    """A judge on a gather call would score a research note; no judge on the write call scores nothing."""
    store: Final = Store()
    chat: Final = ScriptedChat(answered("nothing to add"), answered(GROUNDED), answered(EXTRACTED))

    async with run_deps(chat, store) as deps:
        await run(_request(), deps, Recorder())

    gather, write, extract = chat.asked
    assert gather.guardrails == ("headroom-compression",)
    assert write.guardrails == ("headroom-compression", "quality-judge")
    assert extract.guardrails == ()
    assert extract.model == "fast-model"
    assert extract.schema is not None


async def test_tool_calls_are_executed_and_reported_in_pairs() -> None:
    store: Final = Store()
    chat: Final = ScriptedChat(
        answered(calls=calls_calendar()),
        answered("done"),
        answered(GROUNDED),
        answered(EXTRACTED),
    )
    events: Final = Recorder()

    async with run_deps(chat, store) as deps:
        await run(_request(), deps, events)

    assert len(events.only(ToolStarted)) == len(events.only(ToolFinished)) == 5
    assert all(event.ok for event in events.only(ToolFinished))


async def test_a_figure_a_gather_tool_returned_is_quotable() -> None:
    """The prefetch is not the whole evidence: anything the model went and fetched counts too."""
    store: Final = Store()
    earnings: Final = (ToolCall(id="call_1", name="get_earnings_detail", arguments='{"symbol": "AAPL"}'),)
    quoting_earnings: Final = "# It beat by 7.1%\n\n## The big picture\n\nReported EPS came in at 1.5.\n"
    chat: Final = ScriptedChat(
        answered(calls=earnings),
        answered("earnings are in"),
        answered(quoting_earnings),
        answered(EXTRACTED),
    )
    events: Final = Recorder()

    async with run_deps(chat, store) as deps:
        await run(_request(), deps, events)

    assert events.only(DraftRejected) == ()
    assert store.summaries[0].status == "ok"


async def test_the_gather_loop_stops_at_its_iteration_cap() -> None:
    """A model that keeps calling tools would otherwise spend the whole request budget on one run."""
    store: Final = Store()
    chat: Final = ScriptedChat(
        *[answered(calls=calls_calendar()) for _ in range(6)],
        answered(GROUNDED),
        answered(EXTRACTED),
    )

    async with run_deps(chat, store) as deps:
        await run(_request(), deps, Recorder())

    assert len([asked for asked in chat.asked if asked.tools]) == 3
    assert store.summaries[0].status == "ok"


async def test_a_draft_quoting_an_unmeasured_figure_is_written_again() -> None:
    store: Final = Store()
    chat: Final = ScriptedChat(
        answered("nothing to add"),
        answered(UNGROUNDED),
        answered(GROUNDED),
        answered(EXTRACTED),
    )
    events: Final = Recorder()

    async with run_deps(chat, store) as deps:
        await run(_request(), deps, events)

    rejected: Final = events.only(DraftRejected)
    assert len(rejected) == 1
    assert rejected[0].reason == "grounding"
    assert "1.93" in chat.asked[2].last
    assert store.summaries[0].status == "ok"


async def test_an_exhausted_revise_is_caveated_rather_than_discarded() -> None:
    """A summary the reader can see with a caveat beats a run that produced nothing at all."""
    store: Final = Store()
    chat: Final = ScriptedChat(
        answered("nothing to add"),
        answered(UNGROUNDED),
        answered(UNGROUNDED),
        answered(EXTRACTED),
    )
    events: Final = Recorder()

    async with run_deps(chat, store) as deps:
        await run(_request(), deps, events)

    assert store.summaries[0].status == "caveated"
    assert events.only(RunFinished)[0].status == "caveated"
    assert store.finished[0][1] == "caveated"


async def test_a_blocked_draft_is_written_again_with_the_verdicts() -> None:
    store: Final = Store()
    chat: Final = ScriptedChat(
        answered("nothing to add"),
        Rejected(feedback="compliance 30/100: the closing line gives advice"),
        answered(GROUNDED),
        answered(EXTRACTED),
    )
    events: Final = Recorder()

    async with run_deps(chat, store) as deps:
        await run(_request(), deps, events)

    assert events.only(DraftRejected)[0].reason == "judge"
    assert "gives advice" in chat.asked[2].last
    assert store.summaries[0].status == "ok"


async def test_a_run_blocked_to_exhaustion_fails_rather_than_inventing_a_summary() -> None:
    """A blocked answer carries no prose, so there is nothing to caveat and nothing to store."""
    store: Final = Store()
    chat: Final = ScriptedChat(
        answered("nothing to add"),
        Rejected(feedback="compliance 30/100"),
        Rejected(feedback="compliance 28/100"),
    )
    events: Final = Recorder()

    async with run_deps(chat, store) as deps:
        await run(_request(), deps, events)

    assert store.summaries == []
    assert events.only(RunFailed)[0].status == "failed"
    assert store.finished[0][1] == "failed"


async def test_an_unreachable_proxy_ends_the_run_as_a_value() -> None:
    store: Final = Store()
    chat: Final = ScriptedChat(Unavailable("HTTP 503: upstream is down"))
    events: Final = Recorder()

    async with run_deps(chat, store) as deps:
        await run(_request(), deps, events)

    failed: Final = events.only(RunFailed)[0]
    assert failed.status == "failed"
    assert "503" in failed.detail


async def test_a_caller_that_disconnects_cancels_the_run() -> None:
    async def gone() -> bool:
        return True

    store: Final = Store()
    chat: Final = ScriptedChat(answered("nothing to add"))
    events: Final = Recorder()

    async with run_deps(chat, store) as deps:
        await run(_request(), deps, events, gone)

    assert chat.asked == []
    assert events.only(RunFailed)[0].status == "cancelled"
    assert store.summaries == []


async def test_a_tool_server_that_will_not_answer_ends_the_run_before_the_model_is_asked() -> None:
    store: Final = Store()
    chat: Final = ScriptedChat()
    events: Final = Recorder()

    async with run_deps(chat, store, catalog=RefusingTools()) as deps:
        await run(_request(), deps, events)

    assert chat.asked == []
    assert "not answering" in events.only(RunFailed)[0].detail


async def test_the_run_record_carries_its_timings_and_what_it_spent() -> None:
    """A trace in Jaeger is only queryable if the run row beside it says what happened."""
    store: Final = Store()
    chat: Final = ScriptedChat(answered("nothing to add"), answered(GROUNDED), answered(EXTRACTED))

    async with run_deps(chat, store) as deps:
        await run(_request(), deps, Recorder())

    assert store.runs[0].status == "running"
    _, status, timings, usage = store.finished[0]
    assert status == "ok"
    assert set(timings) == {"cache", "recall", "prefetch", "gather", "write", "check", "extract", "persist"}
    assert all(seconds > 0 for seconds in timings.values())
    assert {(entry.phase, entry.model, entry.calls) for entry in usage} == {
        ("gather", "primary-model", 1),
        ("write", "primary-model", 1),
        ("extract", "fast-model", 1),
    }
