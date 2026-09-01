"""ECharts options, built from a stored snapshot rather than from anything fetched at render time.

Every builder returns `None` when the measurement it draws is absent, and the caller renders the
section's prose without it. A summary written before a measurement existed, or one whose vendor
surface was down that day, still opens.

Two rules run through all of it. Nothing is labelled in the trade's shorthand: a panel that says
`XLK` or `10s2s` is unreadable to the reader the beginner level exists for, so the plain name is
the label and the shorthand lives in the explanation beside it. And colour is never the only
carrier of meaning — a rising sector is named, signed and placed above the axis as well as drawn
in green, so the chart survives a reader who cannot separate the two hues.

Palette comes from `theme="streamlit"` at the call site, which follows the app's light and dark
modes. The two semantic colours are named here because rising and falling must not swap meaning
with the theme; both are chosen to hold their contrast on either ground.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Final, NamedTuple

from orient.domain import figures, vocabulary
from orient.domain.market import EarningsReaction
from orient.domain.models import (
    LEVEL_PLACES,
    Bar,
    Breadth,
    CalendarEntry,
    CrossAsset,
    Holding,
    Relative,
    SectorMove,
    Signals,
    commodities_bear_on,
)

UP: Final = "#0f9d58"
DOWN: Final = "#d93a40"
PRICE: Final = "#2f6fed"
FIFTY: Final = "#c9761f"
TWO_HUNDRED: Final = "#8b5cf6"

ENTRY_MS: Final = 700
EASING: Final = "cubicOut"
ENTRY_DELAY_MS: Final = 120
GRID: Final = {"left": 8, "right": 16, "top": 24, "bottom": 24, "containLabel": True}

PLOTTABLE: Final = 2

TOP_HOLDINGS: Final = 10

CANDLE_WINDOW: Final = 63

MOVE: Final = "move"
CONTRIBUTION: Final = "contribution"
PLACES: Final = {MOVE: 2, CONTRIBUTION: 3}
AXIS_UNITS: Final = {MOVE: "{value}%", CONTRIBUTION: "{value}pp"}
BAR_UNITS: Final = {MOVE: "{c}%", CONTRIBUTION: "{c}pp"}

Option = Mapping[str, object]


def _moving_average(closes: Sequence[float], window: int) -> list[float | None]:
    """Null until the window is full, so a short series draws no line rather than a wrong one."""
    out: Final[list[float | None]] = []
    running = 0.0
    for index, close in enumerate(closes):
        running += close
        if index >= window:
            running -= closes[index - window]
        out.append(round(running / window, 2) if index >= window - 1 else None)
    return out


def price(series: Sequence[tuple[date, float]]) -> Option | None:
    """Close against its fifty and two-hundred day averages, with the session marked.

    The whole year is drawn and the view opens on the last quarter. A reader who wants the longer
    shape drags the handle rather than waiting for another fetch, and one who does not is not made
    to read twelve months of noise to find the week they asked about.
    """
    if len(series) < PLOTTABLE:
        return None
    labels: Final = [when.strftime("%d %b %Y") for when, _ in series]
    closes: Final = [round(close, LEVEL_PLACES) for _, close in series]
    lows, highs = min(closes), max(closes)
    padding: Final = (highs - lows) * 0.08 or 1.0
    opening: Final = max(0, 100 - round(100 * 63 / len(closes)))
    return {
        "animationDuration": ENTRY_MS,
        "animationEasing": EASING,
        "tooltip": {"trigger": "axis"},
        "legend": {"data": ["Price", "50-day average", "200-day average"], "bottom": 0, "itemGap": 18},
        "grid": {**GRID, "bottom": 64},
        "xAxis": {"type": "category", "data": labels, "boundaryGap": False},
        "yAxis": {
            "type": "value",
            "min": round(lows - padding, 2),
            "max": round(highs + padding, 2),
            "splitLine": {"lineStyle": {"opacity": 0.35}},
        },
        "dataZoom": [
            {"type": "inside", "start": opening, "end": 100},
            {"type": "slider", "start": opening, "end": 100, "bottom": 28, "height": 18},
        ],
        "series": [
            {
                "name": "Price",
                "type": "line",
                "data": closes,
                "showSymbol": False,
                "itemStyle": {"color": PRICE},
                "lineStyle": {"width": 2.4, "color": PRICE},
                "areaStyle": {"opacity": 0.14, "color": PRICE},
            },
            {
                "name": "50-day average",
                "type": "line",
                "data": _moving_average(closes, 50),
                "showSymbol": False,
                "itemStyle": {"color": FIFTY},
                "lineStyle": {"width": 1.8, "type": "dashed", "color": FIFTY},
            },
            {
                "name": "200-day average",
                "type": "line",
                "data": _moving_average(closes, 200),
                "showSymbol": False,
                "itemStyle": {"color": TWO_HUNDRED},
                "lineStyle": {"width": 1.8, "type": "dotted", "color": TWO_HUNDRED},
            },
        ],
    }


NOT_EQUITY_LINKED: Final = ("-USD", "=X", "=F")


def sectors_describe(symbol: str) -> bool:
    """Whether the eleven US equity sectors are about this instrument's session or merely beside it."""
    return not symbol.endswith(NOT_EQUITY_LINKED)


def candles(bars: Sequence[Bar]) -> Option | None:
    """The same history as open, high, low and close rather than as a single line.

    A line plots one number a day and reads as a trend. A candle plots four and reads as
    behaviour: a run of sessions that opened high and closed low is a different tape from one
    that closed where it opened, and the line through them is identical.
    """
    if len(bars) < PLOTTABLE:
        return None
    ordered: Final = sorted(bars, key=lambda bar: bar.session_date)
    opening: Final = max(0, 100 - round(100 * CANDLE_WINDOW / len(ordered)))
    return {
        "animationDuration": ENTRY_MS,
        "animationEasing": EASING,
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "cross"}},
        "grid": {**GRID, "bottom": 64},
        "xAxis": {"type": "category", "data": [f"{bar.session_date:%d %b %Y}" for bar in ordered]},
        "yAxis": {"type": "value", "scale": True, "splitLine": {"lineStyle": {"opacity": 0.35}}},
        "dataZoom": [
            {"type": "inside", "start": opening, "end": 100},
            {"type": "slider", "start": opening, "end": 100, "bottom": 28, "height": 18},
        ],
        "series": [
            {
                "type": "candlestick",
                "name": "Session",
                "data": [
                    [
                        round(bar.open, LEVEL_PLACES),
                        round(bar.close, LEVEL_PLACES),
                        round(bar.low, LEVEL_PLACES),
                        round(bar.high, LEVEL_PLACES),
                    ]
                    for bar in ordered
                ],
                "itemStyle": {"color": UP, "color0": DOWN, "borderColor": UP, "borderColor0": DOWN},
            }
        ],
    }


def sectors(moves: Sequence[SectorMove], by: str = MOVE) -> Option | None:
    """Every sector's session, weakest at the bottom, named rather than tickered.

    All eleven are drawn rather than the strongest and weakest few. Five missing from the middle
    makes a day look more polarised than it was, and a reader counting the bars against prose that
    says how many rose has to be able to find them all.

    `by` chooses which question the chart answers, and they are different questions. Ranked by
    move, the biggest bar is the sector that travelled furthest. Ranked by contribution — the move
    multiplied by the sector's weight in the market — the biggest bar is the sector that actually
    moved the index, which is often not the same one. A 1.78% fall in a sector weighing 37% drags
    the market four times as hard as a 1.29% rise in one weighing 12%, and only the second view
    shows it.
    """
    reading: Final = (
        (move.name or move.symbol, move.contribution if by == CONTRIBUTION else move.change_percent) for move in moves
    )
    ranked: Final = sorted(
        ((name, value) for name, value in reading if value is not None),
        key=lambda entry: entry[1],
    )
    if not ranked:
        return None
    return {
        "animationDuration": ENTRY_MS,
        "animationEasing": EASING,
        "animationDelay": ENTRY_DELAY_MS,
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "grid": {**GRID, "left": 16, "right": 56},
        "xAxis": {
            "type": "value",
            "axisLabel": {"formatter": AXIS_UNITS[by]},
            "splitLine": {"lineStyle": {"opacity": 0.3}},
        },
        "yAxis": {"type": "category", "data": [name for name, _ in ranked], "axisTick": {"show": False}},
        "series": [
            {
                "type": "bar",
                "data": [
                    {"value": round(move * 100, PLACES[by]), "itemStyle": {"color": UP if move >= 0 else DOWN}}
                    for _, move in ranked
                ],
                "label": {"show": True, "position": "right", "formatter": BAR_UNITS[by]},
                "barMaxWidth": 18,
            }
        ],
    }


def against(relative: Relative | None, symbol: str, session_return: float | None) -> Option | None:
    """One company's session beside the two things it moved with.

    This replaces the eleven-sector board for a single name, because the board answers a question
    nobody asked about it. What a reader of one company wants is narrower and sharper: did this
    move belong to the company, to its industry, or to the market? Three bars answer that, and
    the eleven do not.
    """
    if relative is None or session_return is None:
        return None
    bars: Final[list[tuple[str, float]]] = [(symbol, session_return)]
    if relative.peer and relative.peer_return is not None:
        bars.append((relative.peer_name or relative.peer, relative.peer_return))
    if relative.benchmark and relative.benchmark_return is not None:
        bars.append((f"The market ({relative.benchmark})", relative.benchmark_return))
    if len(bars) < PLOTTABLE:
        return None
    return {
        "animationDuration": ENTRY_MS,
        "animationEasing": EASING,
        "animationDelay": ENTRY_DELAY_MS,
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "grid": {**GRID, "left": 16, "right": 64},
        "xAxis": {
            "type": "value",
            "axisLabel": {"formatter": "{value}%"},
            "splitLine": {"lineStyle": {"opacity": 0.3}},
        },
        "yAxis": {"type": "category", "data": [name for name, _ in reversed(bars)], "axisTick": {"show": False}},
        "series": [
            {
                "type": "bar",
                "data": [
                    {"value": round(move * 100, 2), "itemStyle": {"color": UP if move >= 0 else DOWN}}
                    for _, move in reversed(bars)
                ],
                "label": {"show": True, "position": "right", "formatter": "{c}%"},
                "barMaxWidth": 22,
            }
        ],
    }


def reacted(events: Sequence[EarningsReaction]) -> Option | None:
    """How the shares took each of the last few results.

    A company that is sold on most of its prints carries that into the next one, and four bars
    say it faster than a sentence can. Ordered oldest to newest so the shape reads left to right.
    """
    ordered: Final = sorted(events, key=lambda entry: entry.reported_on)
    if not ordered:
        return None
    return {
        "animationDuration": ENTRY_MS,
        "animationEasing": EASING,
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "grid": {**GRID, "bottom": 32},
        "xAxis": {
            "type": "category",
            "data": [f"{entry.reported_on:%b %Y}" for entry in ordered],
            "axisTick": {"show": False},
        },
        "yAxis": {
            "type": "value",
            "axisLabel": {"formatter": "{value}%"},
            "splitLine": {"lineStyle": {"opacity": 0.3}},
        },
        "series": [
            {
                "type": "bar",
                "data": [
                    {
                        "value": round(entry.next_session_move * 100, 2),
                        "itemStyle": {"color": UP if entry.next_session_move >= 0 else DOWN},
                    }
                    for entry in ordered
                ],
                "label": {"show": True, "position": "top", "formatter": "{c}%"},
                "barMaxWidth": 40,
            }
        ],
    }


def holdings(held: Sequence[Holding], most: int = TOP_HOLDINGS) -> Option | None:
    """The largest positions in a fund, as a share of it.

    Weights only, never moves. What each holding did on the day is not measured here, and a bar
    coloured by direction would imply it was. The bars answer one question — how concentrated is
    this fund, and in what — which for a tracker is most of why its session looked as it did.
    """
    ranked: Final = sorted(
        ((entry.name or entry.symbol or "", entry.weight) for entry in held if entry.weight),
        key=lambda entry: entry[1],
    )[-most:]
    if not ranked:
        return None
    return {
        "animationDuration": ENTRY_MS,
        "animationEasing": EASING,
        "animationDelay": ENTRY_DELAY_MS,
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "grid": {**GRID, "left": 16, "right": 64},
        "xAxis": {
            "type": "value",
            "axisLabel": {"formatter": "{value}%"},
            "splitLine": {"lineStyle": {"opacity": 0.3}},
        },
        "yAxis": {"type": "category", "data": [name for name, _ in ranked], "axisTick": {"show": False}},
        "series": [
            {
                "type": "bar",
                "data": [{"value": round(weight * 100, 2), "itemStyle": {"color": PRICE}} for _, weight in ranked],
                "label": {"show": True, "position": "right", "formatter": "{c}%"},
                "barMaxWidth": 18,
            }
        ],
    }


class Reading(NamedTuple):
    """One backdrop figure as a reader meets it: what it is, what it says, what it means.

    `field` is the measurement's own name, kept beside the label so a definition the writer wrote
    for this instrument can be looked up against it.
    """

    field: str
    label: str
    value: str
    meaning: str


class Tile(NamedTuple):
    """One headline figure, carrying both the name the writer picks it by and the words a reader
    reads it by. Those are not the same string, and conflating them silently showed five tiles to
    a writer that had asked for three."""

    figure: str
    label: str
    value: str
    meaning: str
    change: str | None = None


class Conditions(NamedTuple):
    """A group of readings that answer one question, with the answer stated above them."""

    heading: str
    note: str
    readings: tuple[Reading, ...]


GROUPS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("How nervous the market was", ("vix",)),
    ("What it cost to borrow", ("yield_10y", "yield_2y", "spread_10s2s", "high_yield_spread")),
    ("Everywhere else", ("dollar_index", "gold", "crude_oil")),
)

COMMODITY_GROUP: Final = "Everywhere else"


def _relevant(heading: str, asset_class: str | None, sector: str | None) -> bool:
    """Whether a backdrop group earns its place beside this particular instrument."""
    return heading != COMMODITY_GROUP or commodities_bear_on(asset_class, sector)


def _note(field_values: Mapping[str, float]) -> str:
    """What the group adds up to, from thresholds rather than from an opinion.

    Each line is a restatement of where a measured number sits against a boundary the market
    itself uses. Nothing here forecasts, and nothing is asserted that the figure beside it does
    not already say."""
    vix: Final = field_values.get("vix")
    if vix is not None:
        return f"Below twenty is usually called calm. This was {vix:,.2f}."
    spread: Final = field_values.get("spread_10s2s")
    if spread is not None:
        shape = "the usual way round" if spread >= 0 else "inverted, which is unusual"
        return f"Long-term borrowing cost minus short-term is {spread:+,.2f}, {shape}."
    return ""


def conditions(
    cross: CrossAsset | None,
    asset_class: str | None = None,
    sector: str | None = None,
) -> tuple[Conditions, ...]:
    """The backdrop, grouped by the question each part of it answers, and cut to what applies.

    `asset_class` and `sector` decide whether the commodity and dollar block belongs. Left unset
    everything is shown, which is the right default for a caller that does not know what it is
    looking at and the wrong one for a page that does.
    """
    if cross is None:
        return ()
    readings: Final[Mapping[str, object]] = dict(cross.model_dump())
    measured: Final = {
        field: float(value)
        for field, value in readings.items()
        if isinstance(value, int | float) and not isinstance(value, bool)
    }
    out: Final[list[Conditions]] = []
    for heading, fields in GROUPS:
        if not _relevant(heading, asset_class, sector):
            continue
        rows = tuple(
            Reading(
                field=field,
                label=vocabulary.BACKDROP[field].label,
                value=f"{measured[field]:,.2f}{'%' if field.startswith('yield') else ''}",
                meaning=vocabulary.BACKDROP[field].meaning,
            )
            for field in fields
            if field in measured and field in vocabulary.BACKDROP
        )
        if rows:
            out.append(
                Conditions(
                    heading=heading, note=_note({f: measured[f] for f in fields if f in measured}), readings=rows
                )
            )
    return tuple(out)


def headline(signals: Signals, quote: str = "Closed at") -> tuple[Tile, ...]:
    """The tiles above the prose: the measurement, its label, its value and what the label means.

    Formatted through `figures`, the same path the prose takes, so a close cannot read one way in
    a tile and another in the sentence under it.
    """
    known: Final = figures.addressable(signals)
    day: Final = known.get("one_day")
    return tuple(
        Tile(
            figure=name,
            label=quote if name == "close" else term.label,
            value=figures.written(known[name]),
            meaning=term.meaning,
            change=None if name != "close" or day is None else figures.written(day),
        )
        for name, term in vocabulary.HEADLINE.items()
        if name in known and not (name == "one_day" and "close" in known)
    )


def rose_and_fell(breadth: Breadth | None) -> str | None:
    """How the market split, as a sentence, because two counts are not worth a chart."""
    if breadth is None or not breadth.total:
        return None
    return f"{breadth.advancers} of {breadth.total} sectors rose, {breadth.decliners} fell"


class Diary(NamedTuple):
    """One line of the week ahead: a kind of event, and who it concerns."""

    kind: str
    named: tuple[str, ...]
    mine: bool = False

    @property
    def summary(self) -> str:
        return ", ".join(self.named)


class Day(NamedTuple):
    """One day of the week ahead, with everything scheduled on it and how far off it is."""

    when: date
    away: int
    lines: tuple[Diary, ...]

    @property
    def mine(self) -> bool:
        return any(line.mine for line in self.lines)

    @property
    def when_said(self) -> str:
        """How far away in words, because a reader counts days off a date badly and often.

        "Thu 27 Aug" and "tomorrow" are the same fact, and only one of them tells a reader whether
        they have time to act on it.
        """
        match self.away:
            case 0:
                return "today"
            case 1:
                return "tomorrow"
            case _:
                return f"in {self.away} days"


def diary(entries: Sequence[CalendarEntry], symbol: str | None = None, since: date | None = None) -> tuple[Day, ...]:
    """The week ahead, by day, with this instrument's own events picked out.

    A raw calendar for a single week runs to forty-odd rows, most of them share splits at companies
    nobody reading this has heard of, and several of them repeats of each other. Grouped, the same
    week is half a dozen lines and the results that matter are visible among them.

    The instrument's own entry is promoted to the front of its line and flagged, because that is
    the one row in the week the reader came for, and it was previously fourth in an alphabetical
    list of strangers.
    """
    grouped: Final[dict[tuple[date, str], list[str]]] = {}
    mine: Final[set[tuple[date, str]]] = set()
    for entry in entries:
        if entry.occurs_at is None:
            continue
        key = (entry.occurs_at, entry.kind)
        seen = grouped.setdefault(key, [])
        if entry.label not in seen:
            seen.append(entry.label)
        if symbol is not None and entry.symbol == symbol:
            mine.add(key)
            seen.remove(entry.label)
            seen.insert(0, entry.label)
    days: Final[dict[date, list[Diary]]] = {}
    for (when, kind), labels in sorted(grouped.items()):
        days.setdefault(when, []).append(
            Diary(
                kind=vocabulary.EVENTS.get(kind, kind.title()),
                named=tuple(labels),
                mine=(when, kind) in mine,
            )
        )
    first: Final = since or (min(days) if days else None)
    return tuple(
        Day(when=when, away=(when - first).days if first else 0, lines=tuple(lines))
        for when, lines in sorted(days.items())
    )
