"""Watching a run: the progress panel, its pacing, and why a run stopped."""

from typing import TYPE_CHECKING, Final, Literal, cast
from uuid import UUID

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from orient.domain.models import ReadingLevel, Summary

if TYPE_CHECKING:
    from datetime import date

from orient.gui import _untyped, progress
from orient.gui.client import Orchestrator, OrchestratorError
from orient.gui.flow.shell import DETAIL, POLL, SECONDS_PER_MINUTE, WHY, choice, transcript


def _recap() -> None:
    transcript()
    chosen: Final = choice()
    when: Final = cast("date", chosen["session_date"])
    st.caption(f"{chosen['symbol']} · {when.strftime('%d %B %Y')} · written for a {chosen['level']} reader")


@st.fragment(run_every=POLL)
def _watch(client: Orchestrator) -> None:
    """Redraws on a timer while the run is going, so Stop is answerable and the page is not stuck.

    The panel is written into rather than entered. `st.status` used as a context manager sets
    itself to "complete" when the block exits — that is documented behaviour, and it is meant for
    a script that opens the panel, does the work inside it and leaves. Here the block is entered
    and left once per poll while the run is still going, so the reader watches a tick appear a
    fraction of a second after every redraw instead of a spinner that keeps turning. Writing to
    the returned container gives the same layout without ever exiting it.
    """
    watch: Final = _untyped.remembered("watch", progress.Watch.idle())
    watch.drain()
    state: Final = watch.progress

    panel: Final = st.status(_headline(state), expanded=True, state=_state(state))
    panel.progress(state.share(_ceiling(client)), text=_pace(state))
    _steps(panel, state)
    if watch.running and panel.button("Stop", key="stop", icon=":material/stop:"):
        watch.cancel()
        panel.update(state="error")
        st.rerun()

    if watch.error:
        st.error(watch.error[0], icon=":material/error:")
    if state.finished:
        _untyped.remember(WHY, state.failure or (watch.error[0] if watch.error else ""))
        _untyped.remember("step", "summary")
        if state.summary_id and not _untyped.holds("summary"):
            _untyped.remember("summary", _fetch(client, state.summary_id))
        st.rerun()


def _ceiling(client: Orchestrator) -> int:
    """The most turns a run may take, asked once and kept for the session."""
    if not _untyped.holds("ceiling"):
        _untyped.remember("ceiling", client.health().max_turns)
    return _untyped.remembered("ceiling", 0)


def _state(state: progress.Progress) -> Literal["running", "complete", "error"]:
    if state.failure:
        return "error"
    return "complete" if state.finished else "running"


def _headline(state: progress.Progress) -> str:
    if state.cached:
        return "Found it already written"
    if state.failure:
        return state.failure
    if state.finished:
        return f"Read the session in {state.turns} steps, {state.seconds:.0f} seconds"
    return state.steps[-1].label if state.steps else "Reading the session"


def _pace(state: progress.Progress) -> str:
    """What the bar says, which while a turn is in flight is the elapsed time and nothing else.

    A turn takes anywhere from two seconds to several minutes, and between two of them no step
    appears and no bar moves. A reader watching a still panel concludes it has hung and navigates
    away, which disconnects the stream and cancels a run that was still working.
    """
    if state.finished:
        return "Done"
    elapsed: Final = _elapsed(state.waited)
    return f"Step {state.turns} · {elapsed}" if state.turns else f"Starting · {elapsed}"


def _elapsed(seconds: float) -> str:
    if seconds < SECONDS_PER_MINUTE:
        return f"{seconds:.0f}s"
    return f"{int(seconds // SECONDS_PER_MINUTE)}m {int(seconds % SECONDS_PER_MINUTE):02d}s"


def _steps(panel: DeltaGenerator, state: progress.Progress) -> None:
    """What has been done so far, in the reader's terms, with what each of them took.

    There is no bar per step. A step is either running or finished, so anything drawn between the
    two would be an invention; what a reader actually wants from a step that is over is how long
    it took, and that is measured.

    Nothing is greyed. Streamlit's `:gray[]` is the body colour at six tenths, which against a
    light page measures 3.7:1 and so misses the 4.5:1 that ordinary text has to clear. Streamlit
    draws its own captions at full strength and a size smaller, and that is the order this
    follows too: rank by weight and size, never by fading the ink.
    """
    detailed: Final = _untyped.remembered(DETAIL, False)
    for step in state.steps:
        mark = ":material/error:" if step.warning else ":material/check:"
        tools = "  " + " ".join(f"`{tool}`" for tool in step.tools) if detailed and step.tools else ""
        panel.markdown(f"{mark} {step.label} — {step.took}{tools}")
        if step.warning:
            panel.caption(step.warning)
    if detailed and state.turns:
        panel.caption(f"{state.turns} model turns · {state.tools_used} tool calls · {state.tokens:,} tokens")


def _fetch(client: Orchestrator, summary_id: str) -> Summary | None:
    try:
        return client.summary(UUID(summary_id))
    except (OrchestratorError, ValueError):
        return None


def run(client: Orchestrator) -> None:
    """Start a run and hand the screen to the progress panel until it finishes or is stopped."""
    _recap()
    chosen: Final = choice()
    if not _untyped.holds("watch"):
        _untyped.remember(
            "watch",
            progress.start(
                client,
                str(chosen["symbol"]),
                cast("date", chosen["session_date"]),
                cast("ReadingLevel", chosen["level"]),
            ),
        )
    _watch(client)
