"""The questions, one screen each: entry, asset class, instrument, session, level."""

from collections.abc import Sequence
from datetime import date
from typing import Final

import streamlit as st

from orient.domain.levels import WORD_BUDGETS
from orient.domain.models import ReadingLevel
from orient.gui import _untyped
from orient.gui.client import Match, Orchestrator, OrchestratorError, Shelf, StoredSummary, Written
from orient.gui.flow.shell import (
    ANY,
    ASSET_CLASSES,
    AVATAR,
    LEVELS,
    POPULAR,
    RECENT,
    REVISIT_PAGE,
    SHOWN,
    Choice,
    advance,
    choice,
    class_of,
    options,
    text,
    transcript,
)


def entry() -> None:
    """The first question: summarise something new, or reopen something already written."""
    with st.chat_message("assistant", avatar=AVATAR):
        st.markdown("What would you like to look at?")
        picked = options(
            "entry",
            (
                Choice("Summarise an instrument", ":material/query_stats:"),
                Choice("Revisit a past summary", ":material/history:"),
            ),
        )
    if picked == "Summarise an instrument":
        advance("class", entry=picked)
        st.rerun()
    if picked == "Revisit a past summary":
        advance("revisit", entry=picked)
        st.rerun()


def asset_class() -> None:
    """Which kind of instrument, which decides both the shortlist and the guidance the model reads."""
    transcript()
    with st.chat_message("assistant", avatar=AVATAR):
        st.markdown("Which kind of instrument?")
        picked = st.segmented_control("Asset class", ASSET_CLASSES, label_visibility="collapsed", key="class")
    if picked:
        advance("instrument", asset_class=picked)
        st.rerun()


def _match_label(match: Match) -> str:
    """Ticker, name and the day's move, so a picker can tell two similar listings apart."""
    move: Final = f"  ·  {match.move}" if match.move else ""
    return f"**{match.symbol}** · {match.title}{move}"


def instrument(client: Orchestrator) -> None:
    """Search reaches everything the vendor lists; the shortlist covers what most readers want.

    Yahoo has no way to enumerate a class — `Lookup` filters a query by kind but will not answer
    "every index" — so the shortlist is written here rather than fetched. It is a shortcut past
    the keyboard, not the set of what can be asked for: anything not on it is still one search
    away, and a ticker that has gone stale falls through to the same empty-calendar message any
    other unlisted instrument would.
    """
    transcript()
    with st.chat_message("assistant", avatar=AVATAR):
        st.markdown("Which one? Type a ticker or a name.")
        query = st.text_input("Search", key="query", label_visibility="collapsed", placeholder="S&P 500, AAPL, gold…")
        if not query:
            _shortlist(text(choice(), "asset_class"))
            return
        try:
            matches = client.search(query, asset_class=class_of(choice()))
        except OrchestratorError as exc:
            st.error(f"Search is unavailable. {exc}", icon=":material/error:")
            return
        if not matches:
            st.caption("Nothing matched. Try a ticker, or part of the name.")
        for match in matches:
            if st.button(
                _match_label(match),
                key=f"pick-{match.symbol}",
                width="stretch",
                help=match.kind,
            ):
                advance("session", symbol=match.symbol, name=match.title)
                st.rerun()


def _shortlist(asset_class: str) -> None:
    """The handful of this class most readers came for, before anyone has typed anything."""
    popular: Final = POPULAR.get(asset_class, ())
    if not popular:
        return
    st.caption("Or start with one of these.")
    row: Final = st.container(horizontal=True, horizontal_alignment="left")
    with row:
        for symbol, name in popular:
            if st.button(name, key=f"popular-{symbol}", help=symbol):
                advance("session", symbol=symbol, name=name)
                st.rerun()


def session(client: Orchestrator) -> None:
    """The sessions this instrument actually traded, newest first.

    Offering a calendar day rather than a traded one is how a summary ends up filed under a date
    nobody asked for: the write boundary stores what the market did, so a Sunday becomes the
    Friday before it and never matches on the way back out. Crypto trades that Sunday, which is
    why the list comes from the instrument rather than from a rule about weekends.

    Streamlit's date picker can be bounded but not perforated: `min_value` and `max_value` are all
    it takes, and there is no way to grey out the Sunday in the middle. A date that did not trade
    is therefore accepted and then moved to the session before it, said out loud rather than
    silently, which is the same answer the write boundary would have reached anyway.
    """
    transcript()
    chosen: Final = choice()
    with st.chat_message("assistant", avatar=AVATAR):
        st.markdown("Which session?")
        try:
            traded = client.sessions(str(chosen["symbol"]))
        except OrchestratorError as exc:
            st.error(f"The trading calendar is unavailable. {exc}", icon=":material/error:")
            return
        if not traded:
            st.caption("This instrument has no recent sessions on file.")
            return
        picked = _pick_session(traded)
    if picked is not None:
        advance("level", session_date=picked)
        st.rerun()


def _pick_session(traded: Sequence[date]) -> date | None:
    """The two most recent as one click each, anything older through the calendar."""
    newest: Final = traded[0]
    oldest: Final = traded[-1]
    quick: Final[dict[str, date]] = dict(zip(RECENT, traded, strict=False))

    def written(name: str) -> str:
        return f"{name} · {quick[name]:%a %d %b}"

    shortcut: Final = st.pills(
        "Session",
        list(quick),
        format_func=written,
        label_visibility="collapsed",
        key="when",
    )
    if isinstance(shortcut, str):
        return quick[shortcut]

    st.caption("Or pick a date. Days the market was shut move to the session before them.")
    asked: Final = st.date_input(
        "Or pick a date",
        value=None,
        min_value=oldest,
        max_value=newest,
        key="date",
        label_visibility="collapsed",
    )
    if not isinstance(asked, date):
        return None
    settled: Final = next((day for day in traded if day <= asked), None)
    if settled is None:
        st.warning(f"Nothing traded on or before {asked:%d %B %Y}.", icon=":material/event_busy:")
        return None
    if settled != asked:
        st.info(
            f"{asked:%A %d %B} was not a trading day. Using {settled:%A %d %B %Y}.",
            icon=":material/event_repeat:",
        )
    return settled


def _level_label(level: ReadingLevel) -> str:
    budget: Final = WORD_BUDGETS[level]
    return f"{level.title()} · {budget.minimum}-{budget.maximum} words"


def level() -> None:
    """Who the summary is for, which sets its length and how much it explains."""
    transcript()
    already: Final = text(choice(), "written")
    with st.chat_message("assistant", avatar=AVATAR):
        st.markdown("Who is it for?")
        picked = st.segmented_control(
            "Reading level",
            [level for level in LEVELS if level != already],
            format_func=_level_label,
            label_visibility="collapsed",
            key="level",
        )
        if already:
            st.caption(f"Already written for a {already} reader.")
    if picked:
        advance("run", level=picked)
        st.rerun()


def revisit(client: Orchestrator) -> None:
    """The archive, narrowed before it is listed rather than listed and then scrolled.

    A flat list is fine at a dozen and unusable at a hundred and fifty. What a reader knows when
    they come back is which instrument they were reading about and roughly when, so those are the
    two things the screen is cut by, and only one screen is fetched at a time.

    Streamlit's own Postgres connection would let this page query the table directly and is the
    wrong tool for it: the orchestrator already owns the database, and a second path to it would
    put credentials in the browser's container, duplicate the row-to-model validation, and let
    the two disagree. What was missing was not a shortcut past the service but filtering and
    paging inside it, which is where they now are.
    """
    transcript()
    with st.chat_message("assistant", avatar=AVATAR):
        st.markdown("Which one?")
        try:
            written = client.written()
        except OrchestratorError as exc:
            st.error(f"Stored summaries are unavailable. {exc}", icon=":material/error:")
            return
        if not written:
            st.caption("Nothing has been written yet.")
            return
        symbol, level = _filters(written)
        shown: Final = _untyped.remembered(SHOWN, REVISIT_PAGE)
        try:
            shelf = client.stored(symbol, level, limit=shown)
        except OrchestratorError as exc:
            st.error(f"Stored summaries are unavailable. {exc}", icon=":material/error:")
            return
        _shelf(client, shelf, shown)


def _filters(written: Sequence[Written]) -> tuple[str | None, ReadingLevel | None]:
    """Which instrument and which reading level, offering only instruments that have something.

    A dropdown for the instrument rather than a row of pills: that list is as long as the archive
    is wide, and a row of it wraps to four lines before a reader has read any of them. Reading
    level is three, which is what pills are for.

    Both labels are shown. A collapsed label is still announced to a screen reader, so hiding it
    only costs the sighted reader, who is then looking at three bare words with no way to know
    they narrow anything.
    """
    counted: Final = {f"{entry.symbol} · {entry.count}": entry.symbol for entry in written}

    def named(option: str) -> str:
        return "Any instrument" if option == ANY else option

    row: Final = st.container(horizontal=True, vertical_alignment="bottom")
    with row:
        picked = st.selectbox("Instrument", [ANY, *counted], format_func=named, key="filter-symbol")
        level = st.pills("Reading level", LEVELS, format_func=str.title, key="filter-level")
    return counted.get(str(picked)), level


def _shelf(client: Orchestrator, shelf: Shelf, shown: int) -> None:
    """One screen of the archive, grouped by month so a date is read once rather than per row."""
    if not shelf.entries:
        st.caption("Nothing matches those filters.")
        return
    heading = ""
    for entry in shelf.entries:
        band = entry.session_date.strftime("%B %Y")
        if band != heading:
            heading = band
            st.markdown(f"**{band}**")
        _stored_button(client, entry)
    if len(shelf.entries) < shelf.total:
        st.caption(f"Showing {len(shelf.entries)} of {shelf.total}.")
        if st.button("Show more", key="more", icon=":material/expand_more:"):
            _untyped.remember(SHOWN, shown + REVISIT_PAGE)
            st.rerun()


def _stored_button(client: Orchestrator, entry: StoredSummary) -> None:
    """One row in the archive. Opening it is a fetch, and a fetch is allowed to fail.

    Every other call to the service on this page is wrapped; this one was not, so a summary the
    service could not serve reached the reader as a Streamlit stack trace rather than a sentence.
    """
    label: Final = f"**{entry.symbol}** · {entry.session_date.strftime('%d %b %Y')} · {entry.level} — {entry.thesis}"
    if not st.button(label, key=f"open-{entry.id}", width="stretch"):
        return
    try:
        opened = client.summary(entry.id)
    except OrchestratorError as exc:
        st.error(f"That summary could not be opened. {exc}", icon=":material/error:")
        return
    _untyped.remember("summary", opened)
    _untyped.remember("step", "summary")
    st.rerun()
