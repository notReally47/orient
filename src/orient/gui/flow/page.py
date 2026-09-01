"""The page itself: which screen is showing, and the settings behind it."""

from typing import Final

import streamlit as st

from orient.gui import _untyped, style
from orient.gui.client import Orchestrator
from orient.gui.flow.shell import DETAIL, GLYPH, TITLE, orchestrator, reset
from orient.gui.flow.summary import show
from orient.gui.flow.turns import asset_class, entry, instrument, level, revisit, session
from orient.gui.flow.watching import run


def settings() -> None:
    """App-level switches, beside the app-level control rather than in the main menu.

    Streamlit's own menu takes three fixed items and nothing else, so there is nowhere to put
    this among Print and Record screen. A sidebar would add a whole navigation drawer for one
    switch; the header already holds Restart, which is where a reader looks for the app itself.
    """
    with st.popover("", icon=":material/settings:", help="Display options"):
        _ = st.toggle(
            "Show technical detail",
            key=DETAIL,
            help="Which tools each step used, and what the run cost. Off for everyday reading.",
        )


def render() -> None:
    """Draw whichever turn the reader has reached."""
    client: Final = orchestrator()

    style.apply()
    header = st.container(horizontal=True, vertical_alignment="bottom")
    with header:
        st.title(f"{GLYPH} {TITLE}", anchor=False, width="stretch")
        settings()
        if st.button("Restart", icon=":material/refresh:", type="tertiary"):
            reset()
            st.rerun()

    with st.empty().container():
        step(client)


def step(client: Orchestrator) -> None:
    """Draw whichever turn the reader has reached, and nothing else."""
    step: Final = _untyped.remembered("step", "entry")
    match step:
        case "entry":
            entry()
        case "class":
            asset_class()
        case "instrument":
            instrument(client)
        case "session":
            session(client)
        case "level":
            level()
        case "run":
            run(client)
        case "revisit":
            revisit(client)
        case "summary":
            show(client, live=not _untyped.remembered("rendered", False))
        case _:
            entry()
