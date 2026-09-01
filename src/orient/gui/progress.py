"""A run, watched from a Streamlit script that must stay responsive while it happens.

Streamlit runs a script top to bottom, so reading the event stream inline would hold the page for
the length of the run and leave nothing able to answer a Stop click. The read therefore happens on
a worker thread that owns nothing but a queue and a flag, and the page drains the queue on a timer.

The worker never touches Streamlit. Everything it produces crosses back as plain values, which is
what makes it safe to run outside a script context.
"""

import queue
import threading
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date
from time import monotonic, sleep
from types import MappingProxyType
from typing import Final

from orient.domain.models import ReadingLevel
from orient.gui.client import Orchestrator, OrchestratorError
from orient.orchestrator.events import (
    CacheHit,
    Event,
    RunFailed,
    RunFinished,
    SummaryRefused,
    ToolStarted,
    TurnFinished,
)

NARRATION: Final[dict[str, str]] = {
    "activate_skill": "Deciding what this instrument needs",
    "read_skill_resource": "Reading the guidance for this kind of instrument",
    "discover_instruments": "Finding the instrument",
    "compute_instrument_signals": "Measuring the session",
    "get_instrument_profile": "Measuring the session",
    "get_price_history": "Reading the price history",
    "get_market_context": "Placing it against the wider market",
    "get_calendar": "Checking the week ahead",
    "get_earnings_detail": "Reading the earnings detail",
    "search_news": "Asking the news why it moved",
    "recall_history": "Recalling what came before",
    "search_knowledge": "Looking for what it said last time",
    "find_similar_sessions": "Looking for a session that resembled this one",
    "check_summary": "Reading the draft back against the data",
    "save_summary": "Checking every figure against the data",
}
THINKING: Final = "Thinking it over"
SHORT: Final = 10.0
TYPICAL_STEPS: Final = 9
CHUNK: Final = 2
PACE: Final = 0.055
BEAT: Final = 0.35


SENT_BACK: Final = "The review sent it back"
REFUSALS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "grounding": "One figure did not reconcile",
        "incomplete": "The summary left out something the session made unavoidable",
        "unfiled": "There was nothing to file it under",
    }
)


def beat(pause: float = BEAT) -> None:
    """Held between a passage and the visual under it, so the page arrives in reading order."""
    sleep(pause)


@dataclass(slots=True)
class Step:
    """One line in the progress list: what happened, how long it took, and what it used."""

    label: str
    seconds: float = 0.0
    tools: tuple[str, ...] = ()
    warning: str | None = None

    @property
    def took(self) -> str:
        """Rounded to whole seconds past ten, because tenths of a minute-long wait are noise."""
        if self.seconds < 1:
            return "under a second"
        return f"{self.seconds:.1f}s" if self.seconds < SHORT else f"{self.seconds:.0f}s"


@dataclass(slots=True)
class Progress:
    """Everything a watcher needs, rebuilt from the events seen so far."""

    steps: list[Step] = field(default_factory=list)
    turns: int = 0
    tokens: int = 0
    summary_id: str | None = None
    cached: bool = False
    failure: str | None = None
    finished: bool = False
    started_at: float = field(default_factory=monotonic)

    @property
    def waited(self) -> float:
        """Seconds since the run began, which is the only thing moving while a turn is in flight.

        A model turn can take a few seconds or a few minutes depending on what the upstream is
        doing, and between two turns nothing on the panel changes. Without a clock a reader
        cannot tell a slow answer from a dead one, and the reasonable thing to do with a page
        that looks dead is leave it — which cancels the run that was about to succeed.
        """
        return monotonic() - self.started_at

    @property
    def tools_used(self) -> int:
        return sum(len(step.tools) for step in self.steps)

    @property
    def seconds(self) -> float:
        return sum(step.seconds for step in self.steps)

    def share(self, ceiling: int) -> float:
        """How far along, against the most turns a run is allowed.

        The model decides how many steps it takes, so there is no total to count towards. The
        turn cap is a real ceiling though, and a bar filling against it is honest as long as it
        is labelled by what has happened rather than by what is left. A finished run fills it
        whatever it took."""
        if self.finished:
            return 1.0
        return min(0.95, self.turns / max(ceiling, TYPICAL_STEPS))


def narrate(tools: tuple[str, ...]) -> str:
    """A turn's sentence, taken from the first tool that has one. Silence is still a step."""
    return next((NARRATION[tool] for tool in tools if tool in NARRATION), THINKING)


def absorb(progress: Progress, event: Event) -> None:
    """Fold one event into the view. Anything without a line of its own is deliberately ignored."""
    match event:
        case TurnFinished():
            progress.turns = event.turn
            progress.tokens = event.prompt_tokens + event.completion_tokens
            if event.tools:
                progress.steps.append(Step(label=narrate(event.tools), seconds=event.seconds, tools=event.tools))
        case SummaryRefused():
            progress.steps.append(
                Step(label=f"{REFUSALS.get(event.reason, SENT_BACK)} — rewriting", warning=event.detail)
            )
        case CacheHit():
            progress.cached = True
            progress.summary_id = str(event.summary_id)
        case RunFinished():
            progress.summary_id = str(event.summary_id)
            progress.finished = True
        case RunFailed():
            progress.failure = event.detail
            progress.finished = True
        case ToolStarted():
            pass
        case _:
            pass


@dataclass(slots=True)
class Watch:
    """A running summary: the worker, the queue it fills, and the flag that ends it early."""

    events: "queue.Queue[Event | None]"
    stop: threading.Event
    worker: threading.Thread
    progress: Progress = field(default_factory=Progress)
    error: list[str] = field(default_factory=list)

    def drain(self) -> None:
        """Fold everything that has arrived since the last look, without waiting for more."""
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                return
            if event is None:
                self.progress.finished = True
                return
            absorb(self.progress, event)

    def cancel(self) -> None:
        self.stop.set()
        self.progress.finished = True
        self.progress.failure = "Stopped"

    @property
    def running(self) -> bool:
        return not self.progress.finished

    @classmethod
    def idle(cls) -> "Watch":
        """A watch over nothing, so a caller reading one back is handed a value not a null."""
        return cls(
            events=queue.Queue(),
            stop=threading.Event(),
            worker=threading.Thread(target=lambda: None),
            progress=Progress(finished=True),
        )


def start(client: Orchestrator, symbol: str, session_date: date, level: ReadingLevel) -> Watch:
    """Begin a run on a worker thread and hand back the handle the page polls."""
    events: queue.Queue[Event | None] = queue.Queue()
    stop: Final = threading.Event()
    errors: Final[list[str]] = []

    def read() -> None:
        try:
            for event in client.stream(symbol, session_date, level, stop):
                events.put(event)
        except OrchestratorError as exc:
            errors.append(str(exc))
        finally:
            events.put(None)

    worker: Final = threading.Thread(target=read, name=f"orient-run-{symbol}", daemon=True)
    worker.start()
    return Watch(events=events, stop=stop, worker=worker, error=errors)


def words(text: str, chunk: int = CHUNK, pace: float = PACE) -> Iterator[str]:
    """Prose in small groups, which is what makes a finished summary arrive as if it were spoken.

    The pause is the whole effect. A model streaming over a network sets its own rhythm, but this
    prose was written minutes ago and is already in memory, so without a wait between groups the
    entire summary lands in one frame and the reveal is invisible.

    Roughly thirty words a second: faster than anyone reads, so it never holds a reader up, and
    slow enough that the page is visibly writing rather than pasting."""
    parts: Final = text.split(" ")
    for index in range(0, len(parts), chunk):
        if index:
            sleep(pace)
        yield " ".join(parts[index : index + chunk]) + " "


Streamer = Callable[[str], Iterator[str]]
