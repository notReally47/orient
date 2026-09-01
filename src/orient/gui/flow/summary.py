"""The finished summary on the page: the prose, the tiles, and every panel beside it."""

from datetime import date
from typing import Final, cast

import streamlit as st

from orient.domain import figures
from orient.domain.models import Bar, Summary
from orient.gui import _untyped, charts, glossary, panels, progress
from orient.gui.client import Orchestrator, OrchestratorError
from orient.gui.flow.shell import (
    AGAINST_HEIGHT,
    AVATAR,
    CHART_HEIGHT,
    DEFAULT_MARKET,
    FAILURE_DETAIL,
    HISTORY_DAYS,
    HOLDINGS_HEIGHT,
    REACTIONS_HEIGHT,
    SECTOR_HEIGHT,
    SECTOR_NOTES,
    SECTOR_VIEWS,
    TILES_PER_ROW,
    WHY,
    Choice,
    choice,
    options,
    reset,
)


def _tiles(summary: Summary) -> None:
    """Three across rather than six. Six in a reading column leaves each too narrow for a price."""
    quote: Final = panels.headline_quote(summary.signals_snapshot)
    measured: Final = charts.headline(summary.signals_snapshot, quote)
    said: Final = panels.meanings(summary)
    wanted: Final = panels.headline(summary.tiles, [tile.figure for tile in measured])
    rows: Final = tuple(tile for tile in measured if tile.figure in wanted)
    for index in range(0, len(rows), TILES_PER_ROW):
        band = rows[index : index + TILES_PER_ROW]
        for column, tile in zip(st.columns(TILES_PER_ROW), band, strict=False):
            with column:
                st.metric(tile.label, tile.value, delta=tile.change, help=said.get(tile.label, tile.meaning))


def _visual(kind: str, summary: Summary, client: Orchestrator) -> None:
    """Draw one panel. A name from a stored layout this build no longer renders draws nothing."""
    match kind:
        case "price":
            _price_panel(summary, client)
        case "candles":
            _candles_panel(summary, client)
        case "against":
            _against_panel(summary)
        case "sectors":
            _sector_panel(summary)
        case "holdings":
            _holdings_panel(summary)
        case "shape":
            _shape_panel(summary)
        case "reactions":
            _reactions_panel(summary)
        case "backdrop":
            _backdrop_panel(summary)
        case "calendar":
            _calendar_panel(summary)
        case _:
            return


def _against_panel(summary: Summary) -> None:
    """One company beside its own sector and the market, which is the question about one company.

    The eleven-sector board belongs to an index. Asked about a single name, a reader wants to know
    whether the move was the company's, its industry's, or the whole market's, and three bars
    answer that where eleven only imply it.
    """
    snapshot: Final = summary.signals_snapshot
    option: Final = charts.against(snapshot.relative, summary.symbol, snapshot.returns.one_day)
    if option is None:
        return
    st.markdown("**Was it the company, the sector, or the market?**")
    _untyped.chart(option, AGAINST_HEIGHT, f"against-{summary.id}")
    st.caption(
        "The same session for this instrument, the sector fund that tracks its industry, and the "
        "broad market. The gaps between the bars are what the instrument did on its own."
    )


def _reactions_panel(summary: Summary) -> None:
    """How the market took the last few results, for a company with one coming."""
    option: Final = charts.reacted(summary.reactions)
    if option is None:
        return
    st.markdown("**How its last results were taken**")
    _untyped.chart(option, REACTIONS_HEIGHT, f"reactions-{summary.id}")
    st.caption(
        "The move on the session after each of the last few reports. It says how this company's "
        "results tend to be received, not what the next one will say."
    )


def _shape_panel(summary: Summary) -> None:
    """Where the move happened: before the open, or during the session.

    Two numbers rather than a figure. A gap and an intraday move are one day split in two, and a
    chart of two bars says nothing a sentence does not, but the split itself changes what the day
    means and is easy to miss inside a paragraph.
    """
    shape: Final = summary.signals_snapshot.shape
    if shape is None or shape.gap is None or shape.intraday is None:
        return
    known: Final = figures.addressable(summary.signals_snapshot)
    said: Final = panels.meanings(summary)
    st.markdown("**Where the move happened**")
    row: Final = st.container(horizontal=True, horizontal_alignment="left")
    with row:
        for label, name, meaning in (
            ("Before the open", "shape.gap", "The change from the last close to this session's open."),
            ("During the session", "shape.intraday", "The change from the open to the close."),
            ("Closed in its range", "shape.close_location", "Where the close sat between the low and the high."),
        ):
            if name in known:
                st.metric(label, figures.written(known[name]), help=said.get(label, meaning), border=False)


def _holdings_panel(summary: Summary) -> None:
    """What the fund actually holds, which is the whole explanation of a basket's session.

    A tracker does not move for reasons of its own. It moves because the handful of names at the
    top of this list moved, and the weights say how much each of them could have contributed.
    """
    option: Final = charts.holdings(summary.holdings)
    if option is None:
        return
    st.markdown("**What it holds**")
    _untyped.chart(option, HOLDINGS_HEIGHT, f"holdings-{summary.id}")
    st.caption(
        "The largest positions on the day this was written, by share of the fund. A basket's "
        "session is the weighted sum of these, so the names at the top are the ones that moved it."
    )


def _candles_panel(summary: Summary, client: Orchestrator) -> None:
    """The same history as open, high, low and close rather than as a line.

    A line is one number a day and reads as a shape. A candle is four, and shows where each
    session opened against where it closed — which is what a reader looking for the character of
    the trading rather than the direction of the trend is after.
    """
    option: Final = charts.candles(_bars(client, summary))
    if option is None:
        return
    _untyped.chart(option, CHART_HEIGHT, f"candles-{summary.id}")
    st.caption("Each bar is one session: the body runs from the open to the close, the line to the extremes.")


def _price_panel(summary: Summary, client: Orchestrator) -> None:
    option: Final = charts.price(_series(client, summary))
    if option is None:
        return
    _untyped.chart(option, CHART_HEIGHT, f"price-{summary.id}")
    st.caption("Drag the bar beneath the chart to look further back.")


def _sector_panel(summary: Summary) -> None:
    """The US equity market's own session: about the instrument, or merely beside it.

    For an index, a share or a fund these eleven bars are the anatomy of the day. For a
    cryptocurrency, a currency pair or a commodity future they are backdrop and nothing more, and
    drawing them under a heading like "how the market split" invites a reader to take them for the
    instrument's own composition. Those get the sentence, which is the part that carries risk
    appetite, and not the chart.
    """
    snapshot: Final = summary.signals_snapshot
    market: Final = snapshot.sector_market or DEFAULT_MARKET
    split: Final = charts.rose_and_fell(snapshot.breadth)
    if not charts.sectors_describe(summary.symbol):
        if split:
            st.markdown(f"**The equity backdrop** — {split}")
            st.caption(
                f"How {market} traded the same day. It is context for risk appetite rather than "
                "a breakdown of this instrument, which has no sectors."
            )
        return
    st.markdown(f"**How the market split** — {split}" if split else "**How the market split**")
    weighted: Final = any(move.contribution is not None for move in snapshot.sectors)
    view: Final = _sector_view() if weighted else charts.MOVE
    option: Final = charts.sectors(snapshot.sectors, view)
    if option is None:
        return
    _untyped.chart(option, SECTOR_HEIGHT, f"sectors-{summary.id}-{view}")
    st.caption(SECTOR_NOTES[view].format(market=market))


def _sector_label(view: str) -> str:
    return SECTOR_VIEWS[view]


def _sector_view() -> str:
    """Which question the sector board answers, chosen by the reader.

    Two charts rather than one because they disagree, and the disagreement is the point: the
    sector that moved furthest is routinely not the sector that moved the market.
    """
    picked: Final = st.segmented_control(
        "Sector view",
        (charts.MOVE, charts.CONTRIBUTION),
        format_func=_sector_label,
        default=charts.MOVE,
        key="sector-view",
        label_visibility="collapsed",
    )
    return picked if isinstance(picked, str) else charts.MOVE


def _backdrop_panel(summary: Summary) -> None:
    """What the rest of the market was doing, grouped by the question each part of it answers.

    Eight figures on unrelated scales laid out as eight identical cards leaves the reader to work
    out which of them matters. Grouped under what they are for, with the boundary each sits against
    stated once above them, the same numbers read as three answers instead of eight facts.
    """
    snapshot: Final = summary.signals_snapshot
    said: Final = panels.meanings(summary)
    for group in charts.conditions(snapshot.cross_asset, snapshot.asset_class, snapshot.sector):
        with st.container(border=True):
            st.markdown(f"**{group.heading}**")
            if group.note:
                st.caption(group.note)
            row = st.container(horizontal=True, horizontal_alignment="left")
            with row:
                for reading in group.readings:
                    st.metric(
                        reading.label,
                        reading.value,
                        help=said.get(reading.field, reading.meaning),
                        border=False,
                    )


def _calendar_panel(summary: Summary) -> None:
    """The week ahead as a card per day rather than a stack of undifferentiated lines.

    Two columns of markdown put every day at the same weight and left the reader counting forward
    from a date to work out whether "Thu 27 Aug" was tomorrow. A day is now a card with the date
    and the distance to it, and the instrument's own event is marked, because in a week of forty
    companies that is the one row anybody came for.
    """
    ahead: Final = charts.diary(summary.calendar, summary.symbol, summary.session_date)
    if not ahead:
        return
    for day in ahead:
        with st.container(border=True):
            heading = st.container(horizontal=True, vertical_alignment="bottom")
            with heading:
                st.markdown(f"**{day.when:%A %d %B}**", width="content")
                st.caption(day.when_said, width="stretch")
                if day.mine:
                    st.badge(summary.symbol, color="orange", icon=":material/push_pin:")
            for line in day.lines:
                st.markdown(f"{':material/star: ' if line.mine else ''}**{line.kind}** — {line.summary}")


def _bars(client: Orchestrator, summary: Summary) -> tuple[Bar, ...]:
    """A year fetched once and shared by every panel that draws from it.

    Both price charts read this, so asking for a candle after a line costs nothing: the second
    panel finds the series already in hand rather than making a second round trip for the same
    twelve months.
    """
    key: Final = f"bars-{summary.id}"
    if not _untyped.holds(key):
        try:
            _untyped.remember(key, client.bars(summary.symbol, summary.session_date, HISTORY_DAYS))
        except OrchestratorError:
            _untyped.remember(key, ())
    return _untyped.remembered(key, cast("tuple[Bar, ...]", ()))


def _series(client: Orchestrator, summary: Summary) -> tuple[tuple[date, float], ...]:
    return tuple((bar.session_date, bar.close) for bar in _bars(client, summary))


def show(client: Orchestrator, *, live: bool) -> None:
    """The finished summary: prose, tiles, and whichever panels the writer placed under each heading.

    `live` paces the reveal for a run the reader has just watched. A summary reopened from the
    archive appears at once, because nothing is being waited for.
    """
    summary: Final = _untyped.remembered("summary", cast("Summary | None", None))
    if summary is None:
        st.warning(_unfinished(), icon=":material/warning:")
        _followups()
        return

    with st.chat_message("assistant", avatar=AVATAR):
        st.caption(f"{summary.symbol} · {summary.session_date.strftime('%d %B %Y')} · {summary.level}")
        if live:
            _ = st.write_stream(progress.words(f"### {summary.thesis}"))
        else:
            st.markdown(f"### {summary.thesis}")
        if live:
            progress.beat()
        _tiles(summary)
        said = figures.addressable(summary.signals_snapshot)
        for section in summary.sections:
            st.markdown(f"##### {section.heading}")
            body = figures.render(section.body, said)
            slot = st.empty()
            if live:
                with slot:
                    _ = st.write_stream(progress.words(body))
            slot.markdown(glossary.annotate(body, summary.glossary), unsafe_allow_html=True)
            if live:
                progress.beat()
            for panel in panels.for_section(section.heading, summary):
                _visual(panel, summary, client)
        _glossary(summary)
    _untyped.remember("rendered", True)
    _followups()


def _glossary(summary: Summary) -> None:
    """Every term the summary explained, listed under it.

    The same definitions the prose hovers, somewhere a reader can find them without a cursor. A
    hover does not exist on a phone or on paper, and the prose stopped explaining terms inline on
    the understanding that this is here.
    """
    terms: Final = glossary.listed(summary.glossary)
    if not terms:
        return
    with st.expander(f"What the words mean ({len(terms)})"):
        for term in terms:
            st.markdown(f"**{term.term}** — {term.meaning}")


def _unfinished() -> str:
    """Why there is no summary, in the reader's terms rather than the system's.

    "The summary could not be read back" describes the last thing that went wrong rather than the
    first, and sends a reader looking for a storage fault when the model never got far enough to
    write anything.
    """
    why: Final = _untyped.remembered(WHY, "")
    if not why:
        return "The run ended before a summary was written."
    return f"No summary was written. {_plainly(why)}"


def _plainly(detail: str) -> str:
    """A vendor's error as a sentence rather than as the JSON it arrived in.

    What reaches here is a proxy error wrapping a provider error wrapping a JSON body, and pasting
    that in front of a reader tells them nothing they can act on. The cases worth naming are the
    ones with a different answer: wait, come back tomorrow, or press Stop was you.
    """
    lowered: Final = detail.lower()
    if "503" in detail or "high demand" in lowered or "unavailable" in lowered:
        return "The model was busy and stayed busy. Nothing was saved — trying again usually works."
    if "429" in detail or "quota" in lowered or "rate limit" in lowered:
        return "The daily allowance for this model is used up. It resets tomorrow."
    if "timeout" in lowered or "timed out" in lowered:
        return "The model took too long to answer and the run was given up on."
    if detail.strip().lower() == "stopped":
        return "You stopped it."
    return _one_line(detail)


def _one_line(detail: str) -> str:
    """The first sentence, trimmed, so an unrecognised failure is still one readable line."""
    flattened: Final = " ".join(detail.split())
    return flattened if len(flattened) <= FAILURE_DETAIL else flattened[:FAILURE_DETAIL].rstrip() + "…"


def _followups() -> None:
    picked: Final = options(
        "followup",
        (
            Choice("Another reading level", ":material/tune:"),
            Choice("Look at something else", ":material/search:"),
        ),
    )
    if picked == "Look at something else":
        reset()
        st.rerun()
    if picked == "Another reading level":
        chosen = choice()
        chosen["written"] = chosen.get("level", "")
        _untyped.forget("summary", "watch", "rendered", "level")
        _untyped.remember("step", "level" if chosen.get("symbol") else "class")
        st.rerun()
