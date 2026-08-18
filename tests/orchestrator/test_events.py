"""Events are the only window a caller has into a run, so the wire form is what gets asserted.

A tag that does not survive serialisation is a client subscribing to an event name that never
arrives, which looks exactly like a run that stalled.
"""

from datetime import date
from typing import Final
from uuid import UUID

import pytest
from pydantic import TypeAdapter

from orient.orchestrator.events import (
    CacheHit,
    DraftRejected,
    Event,
    PhaseFinished,
    PhaseStarted,
    RunFailed,
    RunFinished,
    RunStarted,
    SectionReady,
    ThesisReady,
    ToolFinished,
    ToolStarted,
    as_sse,
)

RUN_ID: Final = UUID("11111111-2222-3333-4444-555555555555")
_EVENT: Final[TypeAdapter[Event]] = TypeAdapter(Event)

EVERY_EVENT: Final = (
    RunStarted(run_id=RUN_ID, symbol="^GSPC", session_date=date(2026, 8, 13), level="beginner"),
    CacheHit(summary_id=RUN_ID),
    PhaseStarted(phase="gather"),
    PhaseFinished(phase="gather", seconds=1.5),
    ToolStarted(tool="get_calendar", arguments="{}"),
    ToolFinished(tool="get_calendar", ok=True, detail="82 characters"),
    ThesisReady(thesis="The index gave back Monday's gain."),
    SectionReady(heading="The big picture", body="Two sectors carried the week."),
    DraftRejected(reason="grounding", detail="1.93", attempt=1),
    RunFinished(status="caveated", summary_id=RUN_ID),
    RunFailed(status="cancelled", detail="the caller disconnected"),
)


@pytest.mark.parametrize("event", EVERY_EVENT, ids=[event.kind for event in EVERY_EVENT])
def test_every_event_is_sent_under_its_own_tag(event: Event) -> None:
    rendered: Final = as_sse(event)
    assert rendered.event == event.kind
    assert isinstance(rendered.data, str)


@pytest.mark.parametrize("event", EVERY_EVENT, ids=[event.kind for event in EVERY_EVENT])
def test_every_event_round_trips_through_its_discriminator(event: Event) -> None:
    """A client reading the stream validates against the same union, so it has to be reversible."""
    assert _EVENT.validate_json(event.model_dump_json()) == event


def test_the_union_covers_every_event_the_module_defines() -> None:
    """A new event that is not in the union serialises fine and never reaches a client."""
    tagged: Final = {event.kind for event in EVERY_EVENT}
    assert len(tagged) == len(EVERY_EVENT)
