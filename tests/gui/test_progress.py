"""What a watcher is shown while a run happens.

The event stream is the orchestrator's contract and this is the only thing that reads it for a
person, so what gets asserted is the translation: which events earn a line, what that line says,
and that a run always reaches a state the page can stop drawing a spinner for.
"""

import threading
from datetime import date
from typing import Final
from uuid import UUID

from orient.gui import progress
from orient.orchestrator.events import (
    CacheHit,
    Event,
    RunFailed,
    RunFinished,
    RunStarted,
    SkillLoaded,
    SummaryRefused,
    ToolFinished,
    ToolStarted,
    TurnFinished,
)

SYMBOL: Final = "^GSPC"
SESSION: Final = date(2026, 8, 13)


def _turn(number: int, *tools: str, prompt: int = 1000, completion: int = 100) -> TurnFinished:
    return TurnFinished(turn=number, seconds=1.0, prompt_tokens=prompt, completion_tokens=completion, tools=tools)


def _folded(*events: Event) -> progress.Progress:
    state: Final = progress.Progress()
    for event in events:
        progress.absorb(state, event)
    return state


def test_a_turn_becomes_a_sentence_rather_than_a_list_of_tool_names() -> None:
    """The panel is read by somebody waiting, not by whoever wrote the tool layer."""
    state: Final = _folded(_turn(1, "get_market_context", "get_calendar"))

    assert [step.label for step in state.steps] == ["Placing it against the wider market"]
    assert state.steps[0].tools == ("get_market_context", "get_calendar")


def test_a_tool_with_no_sentence_of_its_own_still_earns_a_step() -> None:
    """A step that vanishes because nobody wrote a line for it looks like a hang."""
    state: Final = _folded(_turn(1, "some_tool_added_later"))

    assert [step.label for step in state.steps] == [progress.THINKING]


def test_a_turn_that_asked_for_nothing_is_not_a_step() -> None:
    """The model thinking without calling anything is not progress worth a line."""
    state: Final = _folded(_turn(1))

    assert state.steps == []
    assert state.turns == 1


def test_the_running_total_is_the_latest_turn_rather_than_a_sum() -> None:
    """Each turn resends the transcript, so adding the prompts up would count it many times."""
    state: Final = _folded(_turn(1, prompt=1000), _turn(2, prompt=4000, completion=250))

    assert state.turns == 2
    assert state.tokens == 4250


def test_a_refusal_is_shown_rather_than_hidden() -> None:
    """The grounding gate turning a draft away is the checks working, and worth seeing."""
    state: Final = _folded(SummaryRefused(reason="grounding", detail="These figures were not measured: 16"))

    assert "did not reconcile" in state.steps[0].label
    assert state.steps[0].warning is not None


def test_a_review_refusal_reads_differently_from_a_grounding_one() -> None:
    state: Final = _folded(SummaryRefused(reason="quality", detail="too much jargon"))

    assert "review sent it back" in state.steps[0].label


def test_a_finished_run_carries_the_summary_it_wrote() -> None:
    state: Final = _folded(_turn(1, "save_summary"), RunFinished(status="ok", summary_id=UUID(int=3)))

    assert state.finished
    assert state.summary_id == str(UUID(int=3))
    assert state.failure is None


def test_a_cached_run_says_so_and_still_names_the_summary() -> None:
    """Nothing was researched, so a list of steps would be a lie about what happened."""
    state: Final = _folded(CacheHit(summary_id=UUID(int=9)))

    assert state.cached
    assert state.summary_id == str(UUID(int=9))
    assert state.steps == []


def test_a_failed_run_finishes_with_its_reason() -> None:
    state: Final = _folded(RunFailed(status="failed", detail="HTTP 429: quota"))

    assert state.finished
    assert state.failure == "HTTP 429: quota"


def test_events_without_a_line_of_their_own_change_nothing() -> None:
    """Only some events are progress. The rest must not leave blank rows behind."""
    state: Final = _folded(
        RunStarted(run_id=UUID(int=1), symbol=SYMBOL, session_date=SESSION, level="beginner"),
        ToolStarted(tool="search_news", arguments="{}"),
        ToolFinished(tool="search_news", ok=True, detail="2 results"),
        SkillLoaded(skill="analysis", tier="body", characters=4000),
    )

    assert state.steps == []
    assert not state.finished


def test_tools_used_counts_across_every_step() -> None:
    state: Final = _folded(_turn(1, "activate_skill"), _turn(2, "get_calendar", "search_news"))

    assert state.tools_used == 3


def test_draining_folds_everything_queued_without_waiting_for_more() -> None:
    watch: Final = progress.Watch.idle()
    watch.progress = progress.Progress()
    watch.events.put(_turn(1, "activate_skill"))
    watch.events.put(_turn(2, "search_news"))

    watch.drain()

    assert [step.label for step in watch.progress.steps] == [
        "Deciding what this instrument needs",
        "Asking the news why it moved",
    ]
    assert watch.running


def test_the_end_of_the_queue_ends_the_watch() -> None:
    """The worker closes the queue when the stream ends, however it ended."""
    watch: Final = progress.Watch.idle()
    watch.progress = progress.Progress()
    watch.events.put(None)

    watch.drain()

    assert not watch.running


def test_stopping_sets_the_flag_the_reader_is_watching() -> None:
    """Stop works by disconnecting, so the flag has to be the one the stream loop reads."""
    watch: Final = progress.Watch(
        events=progress.queue.Queue(), stop=threading.Event(), worker=threading.Thread(target=lambda: None)
    )

    watch.cancel()

    assert watch.stop.is_set()
    assert not watch.running
    assert watch.progress.failure == "Stopped"


def test_prose_arrives_in_groups_that_reassemble_into_the_original() -> None:
    """The reveal must not change a word of what the grounding check already accepted."""
    body: Final = "The index gave back Monday's gain alongside its sector."

    assert "".join(progress.words(body)).strip() == body
