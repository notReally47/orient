"""The loop: what it hands the model, what it does with the answers, and how a run can end.

The shape being asserted is that the orchestrator decides almost nothing. It looks in the cache,
it hands over a catalog, and then it executes what the model asks for until `save_summary`
accepts a summary. A test that passes here while the loop quietly fetched something on the
model's behalf would be asserting the wrong system.
"""

from datetime import date
from typing import Final
from uuid import UUID

from orient.domain.models import (
    ReadingLevel,
    Returns,
    Section,
    Signals,
    Summary,
    Term,
    TrendDistance,
)
from orient.orchestrator.agent import RunRequest, run
from orient.orchestrator.events import (
    CacheHit,
    RunFailed,
    RunFinished,
    SectionReady,
    SkillLoaded,
    ThesisReady,
    ToolStarted,
    TurnFinished,
)
from tests.orchestrator.fakes import (
    GROUNDED,
    SESSION_DATE,
    SYMBOL,
    UNGROUNDED,
    Cache,
    Recorder,
    RefusingTools,
    ScriptedChat,
    answered,
    calls,
    run_deps,
    saving,
    unavailable,
)


def _request(level: ReadingLevel = "beginner") -> RunRequest:
    return RunRequest(symbol=SYMBOL, session_date=SESSION_DATE, level=level)


def _stored() -> Summary:
    return Summary(
        id=UUID(int=99),
        symbol=SYMBOL,
        session_date=SESSION_DATE,
        level="beginner",
        status="ok",
        thesis="The index gave back Monday's gain",
        sections=(Section(heading="The big picture", body="It fell with the market."),),
        signals_snapshot=Signals(
            symbol=SYMBOL,
            session_date=SESSION_DATE,
            close=100.0,
            returns=Returns(),
            trend=TrendDistance(),
        ),
        glossary=(Term(term="breadth", meaning="how many rose against how many fell"),),
    )


async def test_the_opening_message_carries_the_catalog_and_not_a_single_skill_body() -> None:
    """The whole point of the rebuild. A body here means tier one and tier two collapsed again."""
    chat: Final = ScriptedChat(answered(calls=saving()))

    async with run_deps(chat) as deps:
        await run(_request(), deps, Recorder())

    system: Final = chat.asked[0].system
    assert "<available_skills>" in system
    assert "<name>analysis</name>" in system
    assert "Establish whether the move was its own" not in system
    assert "references/" not in system


async def test_nothing_is_fetched_before_the_model_has_spoken() -> None:
    """Prefetch is gone: what an instrument needs is the instrument skill's judgement, not a
    hardcoded list that only ever suited an equity."""
    events: Final = Recorder()
    chat: Final = ScriptedChat(answered(calls=saving()))

    async with run_deps(chat) as deps:
        await run(_request(), deps, events)

    before: Final = events.kinds().index("turn_finished")
    assert "tool_started" not in events.kinds()[:before]


async def test_the_whole_tool_surface_is_offered_including_the_skills_and_the_save() -> None:
    chat: Final = ScriptedChat(answered(calls=saving()))

    async with run_deps(chat) as deps:
        await run(_request(), deps, Recorder())

    offered: Final = set(chat.asked[0].tools)
    assert {"activate_skill", "read_skill_resource", "save_summary", "recall_history"} <= offered


async def test_a_run_ends_when_the_save_is_accepted() -> None:
    events: Final = Recorder()
    chat: Final = ScriptedChat(answered(calls=saving()))

    async with run_deps(chat) as deps:
        await run(_request(), deps, events)

    finished: Final = events.only(RunFinished)
    assert len(finished) == 1
    assert finished[0].status == "ok"
    assert len(chat.asked) == 1


async def test_the_saved_markdown_is_what_reaches_the_reader() -> None:
    """The prose the model saved is the prose announced, so the stream cannot drift from the row."""
    events: Final = Recorder()

    async with run_deps(ScriptedChat(answered(calls=saving()))) as deps:
        await run(_request(), deps, events)

    assert events.only(ThesisReady)[0].thesis.startswith("The index gave back")
    assert [section.heading for section in events.only(SectionReady)] == [
        "The big picture",
        "What moved, and why",
    ]


async def test_a_refused_save_does_not_end_the_run() -> None:
    """The grounding gate is a decision the model acts on, not an error the loop swallows."""
    events: Final = Recorder()
    chat: Final = ScriptedChat(
        answered(calls=saving(markdown=UNGROUNDED)),
        answered(calls=saving(markdown=GROUNDED)),
    )

    async with run_deps(chat) as deps:
        await run(_request(), deps, events)

    assert len(chat.asked) == 2
    assert events.only(RunFinished)[0].status == "ok"


async def test_loading_a_skill_body_is_reported_with_its_tier() -> None:
    """On-demand loading is only a claim unless it is observable, and this is where it is observed."""
    events: Final = Recorder()
    chat: Final = ScriptedChat(
        answered(calls=calls(("activate_skill", '{"name": "analysis"}'))),
        answered(calls=saving()),
    )

    async with run_deps(chat) as deps:
        await run(_request(), deps, events)

    loaded: Final = events.only(SkillLoaded)
    assert [(entry.skill, entry.tier) for entry in loaded] == [("analysis", "body")]
    assert loaded[0].characters > 0


async def test_reading_a_reference_is_reported_with_the_path() -> None:
    events: Final = Recorder()
    chat: Final = ScriptedChat(
        answered(calls=calls(("read_skill_resource", '{"skill": "analysis", "path": "references/index.md"}'))),
        answered(calls=saving()),
    )

    async with run_deps(chat) as deps:
        await run(_request(), deps, events)

    loaded: Final = events.only(SkillLoaded)[0]
    assert loaded.tier == "reference"
    assert loaded.path == "references/index.md"


async def test_independent_calls_in_one_turn_are_executed_together() -> None:
    """The model batches because the skill tells it to; running them in series spends that back."""
    events: Final = Recorder()
    chat: Final = ScriptedChat(
        answered(
            calls=calls(
                ("activate_skill", '{"name": "analysis"}'),
                ("get_instrument_profile", f'{{"symbol": "{SYMBOL}"}}'),
                ("recall_history", f'{{"symbol": "{SYMBOL}"}}'),
            )
        ),
        answered(calls=saving()),
    )

    async with run_deps(chat) as deps:
        await run(_request(), deps, events)

    assert len(events.only(ToolStarted)) == 4
    assert events.only(TurnFinished)[0].tools == (
        "activate_skill",
        "get_instrument_profile",
        "recall_history",
    )


async def test_a_turn_reports_what_it_cost() -> None:
    events: Final = Recorder()

    async with run_deps(ScriptedChat(answered(calls=saving()))) as deps:
        await run(_request(), deps, events)

    turn: Final = events.only(TurnFinished)[0]
    assert turn.turn == 1
    assert turn.prompt_tokens == 10
    assert turn.seconds > 0


async def test_a_cached_summary_is_replayed_without_a_model_call() -> None:
    events: Final = Recorder()
    chat: Final = ScriptedChat()

    async with run_deps(chat, Cache(_stored())) as deps:
        await run(_request(), deps, events)

    assert chat.asked == []
    assert events.only(CacheHit)
    assert events.kinds()[-1] == "run_finished"


async def test_a_summary_for_another_level_is_not_a_hit() -> None:
    chat: Final = ScriptedChat(answered(calls=saving()))

    async with run_deps(chat, Cache(_stored())) as deps:
        await run(_request(level="advanced"), deps, Recorder())

    assert len(chat.asked) == 1


async def test_a_model_that_stops_without_saving_is_nudged_once_then_fails() -> None:
    """Nothing else bounds a run that has stopped asking for tools: the model decides when it is
    finished, so a model that decides wrongly would sit in the loop until the turn cap."""
    events: Final = Recorder()
    chat: Final = ScriptedChat(answered("I think that is enough"), answered("still nothing"))

    async with run_deps(chat) as deps:
        await run(_request(), deps, events)

    assert len(chat.asked) == 2
    assert "You stopped without saving" in chat.asked[1].messages[-1].content
    assert events.only(RunFailed)[0].status == "failed"


async def test_a_run_that_never_saves_stops_at_the_turn_cap() -> None:
    turns: Final = 3
    chat: Final = ScriptedChat(*[answered(calls=calls(("recall_history", f'{{"symbol": "{SYMBOL}"}}')))] * 10)
    events: Final = Recorder()

    async with run_deps(chat, max_turns=turns) as deps:
        await run(_request(), deps, events)

    assert len(chat.asked) == turns
    assert "no summary after" in events.only(RunFailed)[0].detail


async def test_an_unreachable_proxy_ends_the_run_as_a_value() -> None:
    events: Final = Recorder()

    async with run_deps(ScriptedChat(unavailable("HTTP 429: quota"))) as deps:
        await run(_request(), deps, events)

    failed: Final = events.only(RunFailed)[0]
    assert failed.status == "failed"
    assert "429" in failed.detail


async def test_a_caller_that_disconnects_cancels_before_the_model_is_asked() -> None:
    events: Final = Recorder()
    chat: Final = ScriptedChat(answered(calls=saving()))

    async def gone() -> bool:
        return True

    async with run_deps(chat) as deps:
        await run(_request(), deps, events, gone)

    assert chat.asked == []
    assert events.only(RunFailed)[0].status == "cancelled"


async def test_a_tool_server_that_will_not_answer_leaves_the_run_recoverable() -> None:
    """One dead tool is a result the model reads, not a reason to abandon the run."""
    events: Final = Recorder()
    chat: Final = ScriptedChat(
        answered(calls=calls(("activate_skill", '{"name": "analysis"}'))),
        answered("I cannot continue"),
        answered("still cannot"),
    )

    async with run_deps(chat, catalog=RefusingTools()) as deps:
        await run(_request(), deps, events)

    assert events.only(RunFailed)
    assert not events.only(RunFinished)


async def test_every_turn_carries_compression_and_the_tool_policy() -> None:
    """Quality review is not named here: a summary travels as a tool-call argument, so the
    proxy's post-call judge would score an empty string. It runs inside `save_summary` instead."""
    chat: Final = ScriptedChat(answered(calls=saving()))

    async with run_deps(chat) as deps:
        await run(_request(), deps, Recorder())

    assert chat.asked[0].guardrails == ("headroom-compression", "tool-budget")


async def test_the_research_loop_can_run_on_a_different_model_than_the_writing() -> None:
    chat: Final = ScriptedChat(answered(calls=saving()))

    async with run_deps(chat, gather_model="fast-model") as deps:
        await run(_request(), deps, Recorder())

    assert chat.asked[0].model == "fast-model"


async def test_a_date_the_market_was_shut_is_saved_under_the_session_that_traded() -> None:
    """The write boundary owns this now: it files the summary under the date it measured."""
    events: Final = Recorder()
    shut: Final = date(SESSION_DATE.year, SESSION_DATE.month, SESSION_DATE.day)

    async with run_deps(ScriptedChat(answered(calls=saving(session=shut)))) as deps:
        await run(_request(), deps, events)

    assert events.only(RunFinished)[0].status == "ok"


async def test_every_turn_is_tagged_with_what_it_was() -> None:
    """Tags are the dimension daily spend aggregates by, so they describe the kind of call. The
    run itself is a session rather than a tag, because the dashboard filters on sessions."""
    chat: Final = ScriptedChat(answered(calls=saving()))

    async with run_deps(chat) as deps:
        await run(_request(), deps, Recorder())

    tags: Final = chat.asked[0].tags
    assert f"symbol:{SYMBOL}" in tags
    assert "level:beginner" in tags
    assert "phase:agent" in tags
    assert not any(tag.startswith("run:") for tag in tags)


async def test_every_turn_of_one_run_shares_a_session() -> None:
    """The dashboard groups a conversation by litellm_session_id. Without it a run's turns are
    scattered among every other run's rows and cannot be read back as one thing."""
    chat: Final = ScriptedChat(
        answered(calls=calls(("activate_skill", '{"name": "analysis"}'))),
        answered(calls=saving()),
    )

    async with run_deps(chat) as deps:
        await run(_request(), deps, Recorder())

    sessions: Final = {asked.session for asked in chat.asked}
    assert len(sessions) == 1
    assert sessions != {None}
