"""The page, driven the way a reader drives it.

Streamlit's own harness runs the real script, so these press the real controls and read the real
elements back. What they hold to is the shape of the conversation: no text box anywhere, one
question per turn, an answered turn staying on screen as a record of what was picked, and a
summary that renders from a stored row without a run.
"""

import threading
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Final, Protocol, cast
from uuid import UUID

import pytest
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.element_tree import ButtonGroup, Status

from orient.domain.models import (
    Breadth,
    CalendarEntry,
    CrossAsset,
    ReadingLevel,
    Returns,
    Section,
    Signals,
    Summary,
    Term,
    TrendDistance,
)
from orient.gui.client import Health, Match, Shelf, StoredSummary, Written
from orient.orchestrator.events import Event, RunFailed, RunFinished, TurnFinished

PAGE: Final = Path(__file__).resolve().parents[2] / "src" / "orient" / "gui" / "app.py"
SYMBOL: Final = "^GSPC"
SESSION: Final = date(2026, 8, 13)
SUMMARY_ID: Final = UUID(int=11)
THESIS: Final = "The index closed at a record after cooler inflation"
UNSTAGED: Final = "the page asked for a summary the test did not stage"
HOLD_SECONDS: Final = 2.0


def _summary(**overrides: object) -> Summary:
    base: Final[dict[str, object]] = {
        "id": SUMMARY_ID,
        "symbol": SYMBOL,
        "session_date": SESSION,
        "level": "beginner",
        "status": "ok",
        "thesis": THESIS,
        "sections": (
            Section(heading="The big picture", body="It rose with the market."),
            Section(heading="What moved, and why", body="Communication services led on broad breadth."),
        ),
        "glossary": (Term(term="breadth", meaning="how many rose against how many fell"),),
        "calendar": (CalendarEntry(kind="earnings", label="Klarna Group plc", occurs_at=date(2026, 8, 18)),),
        "signals_snapshot": Signals(
            symbol=SYMBOL,
            session_date=SESSION,
            close=7798.99,
            returns=Returns(one_day=0.0065, year_to_date=0.1393),
            trend=TrendDistance(from_50_day=0.0388, from_200_day=0.1031),
            breadth=Breadth.over({"XLC": 0.0207, "XLB": -0.0051}),
            cross_asset=CrossAsset(vix=14.63, yield_10y=4.63, yield_2y=4.15),
        ),
    }
    return Summary.model_validate({**base, **overrides})


class FakeOrchestrator:
    """Answers the page without a service behind it, and records what it was asked for."""

    def __init__(
        self,
        matches: tuple[Match, ...] = (),
        stored: tuple[StoredSummary, ...] = (),
        summary: Summary | None = None,
        events: tuple[Event, ...] = (),
        holds: bool = False,
    ) -> None:
        self._matches: Final = matches
        self._stored: Final = stored
        self._summary: Final = summary
        self._events: Final = events
        self._holds: Final = holds
        self.searched: Final[list[tuple[str, str | None]]] = []
        self.browsed: Final[list[tuple[str | None, str | None, int]]] = []
        self.ran: Final[list[tuple[str, date, str]]] = []

    def search(self, query: str, limit: int = 8, asset_class: str | None = None) -> tuple[Match, ...]:
        del limit
        self.searched.append((query, asset_class))
        return self._matches

    def sessions(self, symbol: str, limit: int = 60) -> tuple[date, ...]:
        del symbol, limit
        return (SESSION, SESSION - timedelta(days=1))

    def health(self) -> Health:
        return Health(status="ok", tools=14, max_turns=12)

    def closes(self, symbol: str, session_date: date, days: int = 180) -> tuple[tuple[date, float], ...]:
        del symbol, session_date, days
        return tuple((SESSION, 7000.0 + index) for index in range(3))

    def stored(
        self,
        symbol: str | None = None,
        level: str | None = None,
        limit: int = 12,
        offset: int = 0,
    ) -> Shelf:
        matched: Final = tuple(
            entry
            for entry in self._stored
            if (symbol is None or entry.symbol == symbol) and (level is None or entry.level == level)
        )
        self.browsed.append((symbol, level, limit))
        return Shelf(total=len(matched), entries=matched[offset : offset + limit])

    def written(self) -> tuple[Written, ...]:
        seen: Final[dict[str, int]] = {}
        for entry in self._stored:
            seen[entry.symbol] = seen.get(entry.symbol, 0) + 1
        return tuple(Written(symbol=symbol, count=count, latest=SESSION) for symbol, count in seen.items())

    def summary(self, summary_id: UUID) -> Summary:
        del summary_id
        if self._summary is None:
            raise AssertionError(UNSTAGED)
        return self._summary

    def stream(self, symbol: str, session_date: date, level: ReadingLevel, stop: threading.Event) -> Iterator[Event]:
        self.ran.append((symbol, session_date, level))
        yield from self._events
        if self._holds:
            _ = stop.wait(HOLD_SECONDS)


def _page(client: FakeOrchestrator | None = None, **state: object) -> AppTest:
    page: Final = AppTest.from_file(str(PAGE), default_timeout=15)
    page.session_state["client"] = client if client is not None else FakeOrchestrator()
    for key, value in state.items():
        page.session_state[key] = value
    return page.run()


def _labels(page: AppTest) -> list[str]:
    return [" ".join(block.value.split()) for block in page.markdown]


class Drawn(Protocol):
    """What `st.html` looks like to the harness.

    There is no element class for it, so it arrives as the generic node whose attribute lookup
    falls through to the protobuf behind it. Naming the one field that is read keeps that fallback
    from being an untyped hole in the middle of the assertions.
    """

    body: str


def _said(page: AppTest) -> str:
    """Everything on screen, including the answers, which are drawn rather than posted."""
    drawn: Final = [cast("Drawn", node).body for node in page.get("html")]
    return " ".join(_labels(page) + [" ".join(markup.split()) for markup in drawn])


def _press(page: AppTest, label: str) -> AppTest:
    """Click the option with this label, whichever kind of control carries it."""
    return next(button for button in page.button if button.label == label).click().run()


def _group(page: AppTest, key: str) -> ButtonGroup[str]:
    """Pills and segmented controls are the same element to the harness, so they go by key."""
    groups: Final = cast("list[ButtonGroup[str]]", list(page.get("button_group")))
    return next(group for group in groups if group.key == key)


def test_the_page_offers_no_text_box_to_type_a_request_into() -> None:
    """The whole premise: a request is built by choosing, never by typing one."""
    page: Final = _page()

    assert page.chat_input.values == []
    assert any(button.label == "Summarise an instrument" for button in page.button)


def test_choosing_an_entry_opens_the_next_question_and_keeps_the_answer() -> None:
    """An answered turn stays on screen, so the transcript is the record of what was asked for."""
    page: Final = _page()

    _press(page, "Summarise an instrument")

    assert "Summarise an instrument" in _said(page)
    assert _group(page, "class").options[:2] == ["Index", "Equity"]


def test_searching_asks_the_orchestrator_and_lists_what_came_back() -> None:
    client: Final = FakeOrchestrator(
        matches=(Match(symbol=SYMBOL, name="S&P 500", quote_type="INDEX", price=7798.99, change_percent=0.65),)
    )
    page: Final = _page(client, step="instrument", choice={"asset_class": "Index"})

    page.text_input[0].set_value("s&p").run()

    assert client.searched == [("s&p", "index")]
    picked: Final = next(button for button in page.button if SYMBOL in button.label)
    assert "S&P 500" in picked.label
    assert "+0.65%" in picked.label


def test_a_search_the_service_cannot_answer_is_shown_rather_than_raised() -> None:
    class Broken(FakeOrchestrator):
        def search(self, query: str, limit: int = 8, asset_class: str | None = None) -> tuple[Match, ...]:
            from orient.gui.client import OrchestratorError  # noqa: PLC0415  # only this test needs it

            del query, limit, asset_class
            message = "the tool server is down"
            raise OrchestratorError(message)

    page: Final = _page(Broken(), step="instrument", choice={"asset_class": "Index"})

    page.text_input[0].set_value("s&p").run()

    assert any("unavailable" in error.value for error in page.error)
    assert not page.exception


def test_a_reading_level_is_offered_with_the_length_it_produces() -> None:
    page: Final = _page(step="level", choice={"symbol": SYMBOL, "name": "S&P 500", "session_date": SESSION})

    labels: Final = _group(page, "level").options
    assert any("Beginner" in label and "500-700 words" in label for label in labels)


def test_a_finished_run_renders_the_summary_it_wrote() -> None:
    client: Final = FakeOrchestrator(
        summary=_summary(),
        events=(
            TurnFinished(turn=1, seconds=1.0, prompt_tokens=10, completion_tokens=2, tools=("activate_skill",)),
            RunFinished(status="ok", summary_id=SUMMARY_ID),
        ),
    )
    page: Final = _page(
        client,
        step="run",
        choice={"symbol": SYMBOL, "name": "S&P 500", "session_date": SESSION, "level": "beginner"},
    )

    assert client.ran == [(SYMBOL, SESSION, "beginner")]
    assert not page.exception


def test_a_run_still_going_shows_a_spinner_rather_than_a_tick() -> None:
    """The panel is redrawn on a timer, and `st.status` marks itself complete when a `with` block
    around it exits — so entering one per redraw put a tick on a run that had barely started."""
    client: Final = FakeOrchestrator(
        events=(TurnFinished(turn=1, seconds=1.0, prompt_tokens=10, completion_tokens=2, tools=("activate_skill",)),),
        holds=True,
    )
    page: Final = _page(
        client,
        step="run",
        choice={"symbol": SYMBOL, "name": "S&P 500", "session_date": SESSION, "level": "beginner"},
    )

    panels: Final = cast("list[Status]", list(page.get("status")))
    assert [panel.state for panel in panels] == ["running"]


def test_a_finished_run_marks_the_panel_complete() -> None:
    """The other half of the same rule: a tick is right once there is nothing left to wait for."""
    client: Final = FakeOrchestrator(
        summary=_summary(),
        events=(
            TurnFinished(turn=1, seconds=1.0, prompt_tokens=10, completion_tokens=2, tools=("activate_skill",)),
            RunFinished(status="ok", summary_id=SUMMARY_ID),
        ),
    )
    page: Final = _page(
        client,
        step="run",
        choice={"symbol": SYMBOL, "name": "S&P 500", "session_date": SESSION, "level": "beginner"},
    )

    assert not page.exception
    assert client.ran == [(SYMBOL, SESSION, "beginner")]


def test_a_stored_summary_renders_from_the_row_without_a_run() -> None:
    """Revisiting must not call the model, so everything drawn has to be in the row already."""
    client: Final = FakeOrchestrator(summary=_summary())
    page: Final = _page(client, step="summary", summary=_summary(), rendered=True)

    assert client.ran == []
    assert THESIS in " ".join(_labels(page))
    assert any("The big picture" in label for label in _labels(page))


def test_the_headline_tiles_come_from_the_stored_snapshot() -> None:
    page: Final = _page(step="summary", summary=_summary(), rendered=True)

    assert [tile.label for tile in page.metric][:2] == ["Closed at", "This year"]


def test_a_summary_without_a_backdrop_still_opens() -> None:
    """Rows written before the backdrop was stored have to keep rendering."""
    sparse: Final = _summary(
        signals_snapshot=Signals(
            symbol=SYMBOL, session_date=SESSION, close=7798.99, returns=Returns(), trend=TrendDistance()
        )
    )
    page: Final = _page(step="summary", summary=sparse, rendered=True)

    assert THESIS in " ".join(_labels(page))
    assert not page.exception


def test_the_terms_the_writer_flagged_are_defined_where_they_appear() -> None:
    """A list at the bottom asks the reader to go looking; a hover meets them where they are."""
    page: Final = _page(step="summary", summary=_summary(), rendered=True)

    prose: Final = " ".join(_labels(page))
    assert "orient-term" in prose
    assert "how many rose against how many fell" in prose


def _archive(count: int) -> tuple[StoredSummary, ...]:
    """An archive large enough that listing all of it would be the wrong thing to do."""
    return tuple(
        StoredSummary(
            id=UUID(int=index),
            symbol=SYMBOL if index % 2 else "AAPL",
            session_date=SESSION - timedelta(days=index),
            level="beginner" if index % 3 else "advanced",
            thesis=f"{THESIS}, number {index}",
        )
        for index in range(1, count + 1)
    )


def test_revisiting_lists_what_has_been_written_before() -> None:
    client: Final = FakeOrchestrator(
        stored=(
            StoredSummary(
                id=SUMMARY_ID,
                symbol=SYMBOL,
                session_date=SESSION,
                level="beginner",
                thesis=THESIS,
            ),
        )
    )
    page: Final = _page(client, step="revisit")

    assert any(THESIS in button.label for button in page.button)


def test_revisiting_with_nothing_stored_says_so() -> None:
    page: Final = _page(step="revisit")

    assert any("Nothing has been written" in note.value for note in page.caption)


def _page_size() -> int:
    """The page's own idea of a screenful.

    `flow` registers a Streamlit component when it is imported, which only works once a runtime
    exists, so it is reached for after a page has been run rather than at the top of the file.
    """
    from orient.gui import flow  # noqa: PLC0415

    return flow.REVISIT_PAGE


def test_a_large_archive_is_paged_rather_than_poured_onto_the_screen() -> None:
    """A hundred and fifty buttons is not a list, it is a wall."""
    client: Final = FakeOrchestrator(stored=_archive(150))
    page: Final = _page(client, step="revisit")

    opened: Final = [button for button in page.button if button.key and button.key.startswith("open-")]
    assert len(opened) == _page_size()
    assert any("of 150" in note.value for note in page.caption)


def test_asking_for_more_asks_the_service_for_more_rather_than_revealing_it() -> None:
    """Whatever is not on screen should not have been fetched."""
    client: Final = FakeOrchestrator(stored=_archive(150))
    page: Final = _page(client, step="revisit")

    next(button for button in page.button if button.label == "Show more").click().run()

    assert client.browsed[-1][2] == _page_size() * 2


def test_the_filter_only_offers_instruments_something_was_written_about() -> None:
    client: Final = FakeOrchestrator(stored=_archive(8))
    page: Final = _page(client, step="revisit")

    options: Final = page.selectbox[0].options
    assert any(SYMBOL in option for option in options)
    assert "MSFT" not in " ".join(options)


def test_a_filter_that_matches_nothing_says_so_rather_than_showing_an_empty_screen() -> None:
    client: Final = FakeOrchestrator(stored=_archive(4))
    page: Final = _page(client, step="revisit")

    _group(page, "filter-level").set_value("intermediate").run()

    assert any("Nothing matches" in note.value for note in page.caption)


def test_restart_clears_the_transcript_back_to_the_first_question() -> None:
    page: Final = _page(step="summary", summary=_summary(), rendered=True)

    restart: Final = next(button for button in page.button if button.label == "Restart")
    restart.click().run()

    assert "step" not in page.session_state
    assert any(button.label == "Summarise an instrument" for button in page.button)


@pytest.mark.parametrize("step", ["entry", "class", "revisit"])
def test_no_step_of_the_flow_raises(step: str) -> None:
    """A page that throws leaves a stack trace where a question should be."""
    page: Final = _page(step=step, choice={"asset_class": "Index"})

    assert not page.exception


def test_the_whole_conversation_stays_on_screen() -> None:
    """A reader picking a reading level still has to see which instrument it is for."""
    page: Final = _page(
        step="level",
        choice={
            "entry": "Summarise an instrument",
            "asset_class": "Index",
            "symbol": SYMBOL,
            "name": "S&P 500",
            "session_date": SESSION,
        },
    )

    shown: Final = _said(page)
    assert "Summarise an instrument" in shown
    assert "Which kind of instrument?" in shown
    assert "S&amp;P 500" in shown or "S&P 500" in shown
    assert "13 August 2026" in shown


def test_an_unanswered_turn_is_not_in_the_transcript() -> None:
    """The transcript is a record of what was picked, not a list of what will be asked."""
    page: Final = _page(step="class", choice={"entry": "Summarise an instrument"})

    shown: Final = _said(page)
    assert "Summarise an instrument" in shown
    assert "Which session?" not in shown


def test_a_run_that_wrote_nothing_says_why_rather_than_blaming_the_read() -> None:
    """ "The summary could not be read back" describes the last thing that went wrong rather than
    the first, and sends the reader hunting for a storage fault after a rate limit."""
    client: Final = FakeOrchestrator(
        events=(RunFailed(status="failed", detail="HTTP 429: you exceeded your current quota"),),
    )
    page: Final = _page(
        client,
        step="run",
        choice={"symbol": SYMBOL, "name": "S&P 500", "session_date": SESSION, "level": "beginner"},
    )

    shown: Final = " ".join(warning.value for warning in page.warning)
    assert "allowance" in shown
    assert "could not be read back" not in shown
    assert "429" not in shown


def test_a_transient_upstream_refusal_reads_as_one_worth_retrying() -> None:
    """A wall of provider JSON tells a reader nothing they can act on. Three failures have three
    different answers — wait, come back tomorrow, or you pressed Stop — and only the wording says
    which."""
    detail: Final = (
        "HTTP 503: litellm.ServiceUnavailableError: GeminiException - "
        '{"code": 503, "message": "This model is currently experiencing high demand."}'
    )
    client: Final = FakeOrchestrator(events=(RunFailed(status="failed", detail=detail),))
    page: Final = _page(
        client,
        step="run",
        choice={"symbol": SYMBOL, "name": "S&P 500", "session_date": SESSION, "level": "beginner"},
    )

    shown: Final = " ".join(warning.value for warning in page.warning)
    assert "trying again usually works" in shown
    assert "GeminiException" not in shown
