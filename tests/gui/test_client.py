"""The front end's view of the orchestrator, driven over a stubbed transport.

Two things matter here. Responses are validated rather than indexed, so a service that changes
shape fails with a name attached instead of drawing a blank tile. And a run must be stoppable:
the stream loop reads the flag between events, which is what turns a Stop click into a
disconnected client and a cancelled run.
"""

import json
import threading
from collections.abc import Iterator
from datetime import date
from typing import Final
from uuid import UUID

import httpx
import pytest

from orient.gui.client import Orchestrator, OrchestratorError, StoredSummary
from orient.orchestrator.events import Event, RunFinished, TurnFinished, as_sse

SESSION: Final = date(2026, 8, 13)
SUMMARY_ID: Final = UUID(int=5)
REFUSED: Final = "connection refused"


def _client(handler: object) -> Orchestrator:
    transport: Final = httpx.MockTransport(handler)  # pyright: ignore[reportArgumentType]  # no stubs
    return Orchestrator(httpx.Client(transport=transport, base_url="http://orchestrator"))


def _answering(payload: object, status: int = 200) -> Orchestrator:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(status, content=json.dumps(payload).encode())

    return _client(handler)


def test_a_search_comes_back_as_matches_the_picker_can_list() -> None:
    served: Final = _answering(
        {
            "query": "s&p",
            "matches": [
                {"symbol": "^GSPC", "name": "S&P 500", "quote_type": "INDEX", "price": 7798.99, "change_percent": 0.65}
            ],
        }
    )

    matches: Final = served.search("s&p")

    assert [match.symbol for match in matches] == ["^GSPC"]
    assert matches[0].title == "S&P 500"
    assert matches[0].kind == "index"
    assert matches[0].move == "7,798.99 (+0.65%)"


def test_a_match_without_a_name_still_shows_its_ticker() -> None:
    """A vendor row missing a name must not render as an unlabelled button."""
    served: Final = _answering({"matches": [{"symbol": "NEWCO"}]})

    only: Final = served.search("newco")[0]
    assert only.title == "NEWCO"
    assert only.kind == "instrument"
    assert only.move == ""


def test_a_service_that_is_down_is_an_error_the_page_can_show() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        del request
        raise httpx.ConnectError(REFUSED)

    with pytest.raises(OrchestratorError, match="ConnectError"):
        _ = _client(refuse).search("anything")


def test_an_error_status_carries_what_the_service_said() -> None:
    served: Final = _answering({"detail": "the tool server is down"}, status=502)

    with pytest.raises(OrchestratorError, match="502"):
        _ = served.search("anything")


def test_a_price_window_arrives_oldest_first() -> None:
    served: Final = _answering(
        {
            "symbol": "^GSPC",
            "bars": [
                {"session_date": "2026-08-13", "open": 1, "high": 1, "low": 1, "close": 7798.99, "volume": 1},
                {"session_date": "2026-08-12", "open": 1, "high": 1, "low": 1, "close": 7748.50, "volume": 1},
            ],
        }
    )

    series: Final = served.closes("^GSPC", SESSION)

    assert [when for when, _ in series] == [date(2026, 8, 12), date(2026, 8, 13)]
    assert series[-1][1] == 7798.99


def test_a_price_window_that_cannot_be_read_draws_nothing_rather_than_raising() -> None:
    """The chart is one panel of a summary. Losing it must not lose the prose beside it."""
    served: Final = _answering({"bars": [{"session_date": "not-a-date"}]})

    assert served.closes("^GSPC", SESSION) == ()


def test_stored_summaries_come_back_as_rows_a_list_can_render() -> None:
    served: Final = _answering(
        {
            "total": 137,
            "entries": [
                {
                    "id": str(SUMMARY_ID),
                    "symbol": "^GSPC",
                    "session_date": "2026-08-13",
                    "level": "beginner",
                    "thesis": "A record close",
                }
            ],
        }
    )

    shelf: Final = served.stored()

    assert shelf.total == 137
    assert shelf.entries == (
        StoredSummary(
            id=SUMMARY_ID,
            symbol="^GSPC",
            session_date=SESSION,
            level="beginner",
            thesis="A record close",
        ),
    )


def test_a_filtered_page_asks_the_service_for_it_rather_than_trimming_the_answer() -> None:
    """Whatever the page does not show, it should not have paid to fetch."""
    asked: Final[list[httpx.URL]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.url)
        return httpx.Response(200, content=json.dumps({"total": 0, "entries": []}).encode())

    _ = _client(handler).stored("^GSPC", "beginner", limit=12, offset=24)

    query: Final = dict(asked[0].params)
    assert query == {"limit": "12", "offset": "24", "symbol": "^GSPC", "level": "beginner"}


def test_the_instruments_written_about_come_back_for_the_filter() -> None:
    served: Final = _answering([{"symbol": "^GSPC", "count": 14, "latest": "2026-08-13"}])

    written: Final = served.written()

    assert written[0].symbol == "^GSPC"
    assert written[0].count == 14


def test_a_listing_in_an_unexpected_shape_is_refused_by_name() -> None:
    served: Final = _answering({"entries": [{"id": "not-a-uuid"}]})

    with pytest.raises(OrchestratorError, match="unexpected shape"):
        _ = served.stored()


def _sse(*events: Event) -> bytes:
    """Encoded by the orchestrator's own renderer, so the two sides cannot drift apart."""
    return b"".join(as_sse(event).encode() for event in events)


def _streaming(body: bytes) -> Orchestrator:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, content=body)

    return _client(handler)


def test_a_run_arrives_as_typed_events() -> None:
    served: Final = _streaming(
        _sse(
            TurnFinished(turn=1, seconds=1.0, prompt_tokens=10, completion_tokens=2, tools=("activate_skill",)),
            RunFinished(status="ok", summary_id=SUMMARY_ID),
        )
    )

    seen: Final = list(served.stream("^GSPC", SESSION, "beginner", threading.Event()))

    assert [event.kind for event in seen] == ["turn_finished", "run_finished"]


def test_a_line_that_is_not_an_event_is_skipped_rather_than_fatal() -> None:
    """Keep-alives and comments share the wire with events and must not end the run."""
    served: Final = _streaming(
        b': keep-alive\n\ndata: {"kind": "nonsense"}\n\n' + _sse(RunFinished(status="ok", summary_id=SUMMARY_ID))
    )

    seen: Final = list(served.stream("^GSPC", SESSION, "beginner", threading.Event()))

    assert [event.kind for event in seen] == ["run_finished"]


def test_setting_the_stop_flag_ends_the_stream_where_it_stands() -> None:
    """Stop is a disconnect: the loop stops reading, which is what the orchestrator notices."""
    served: Final = _streaming(
        _sse(
            TurnFinished(turn=1, seconds=1.0, prompt_tokens=10, completion_tokens=2, tools=("activate_skill",)),
            TurnFinished(turn=2, seconds=1.0, prompt_tokens=20, completion_tokens=4, tools=("search_news",)),
            RunFinished(status="ok", summary_id=SUMMARY_ID),
        )
    )
    stop: Final = threading.Event()

    def until_first() -> Iterator[Event]:
        for event in served.stream("^GSPC", SESSION, "beginner", stop):
            yield event
            stop.set()

    assert len(list(until_first())) == 1


def test_a_run_the_service_refuses_says_so_before_any_event() -> None:
    served: Final = _answering({"detail": "still starting"}, status=503)

    with pytest.raises(OrchestratorError, match="503"):
        _ = list(served.stream("^GSPC", SESSION, "beginner", threading.Event()))


def test_the_sessions_offered_come_back_as_dates() -> None:
    served: Final = _answering(["2026-08-21", "2026-08-20"])

    assert served.sessions("^GSPC") == (date(2026, 8, 21), date(2026, 8, 20))


def test_an_instrument_with_no_recent_sessions_is_an_answer_rather_than_an_error() -> None:
    """A thinly traded or delisted instrument has nothing to summarise, which the page says."""
    assert _answering([]).sessions("DEAD") == ()


def test_a_search_can_be_narrowed_to_one_asset_class() -> None:
    asked: Final[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, content=b'{"matches": []}')

    served: Final = _client(handler)
    _ = served.search("s&p", asset_class="index")

    assert "asset_class=index" in asked[0]


def test_a_search_without_a_class_does_not_send_one() -> None:
    asked: Final[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, content=b'{"matches": []}')

    _ = _client(handler).search("s&p")

    assert "asset_class" not in asked[0]
