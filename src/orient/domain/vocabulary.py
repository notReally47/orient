"""Every word the page puts in front of a reader.

Domain rather than presentation, because the writer has to know what the page already says: it
renders from here, and `references/page.md` briefs the writer from the same table. The definitions
are a fallback for wherever the summary's own glossary said nothing.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, Literal, NamedTuple, get_args

Shown = Literal["level", "yield", "change", "percent", "share", "multiple", "ratio", "plain"]


class Label(NamedTuple):
    """One figure the page can show: what it is called, what it means, and how it is written."""

    label: str
    meaning: str
    shown: Shown = "change"


HEADLINE: Final[Mapping[str, Label]] = MappingProxyType(
    {
        "close": Label(
            "Closed at",
            "The last price of the session, which is what the summary is written about.",
            "level",
        ),
        "one_day": Label("On the day", "How far it moved from the session before."),
        "one_week": Label("Over the week", "How far it has moved across the last five sessions."),
        "one_month": Label("Over the month", "How far it has moved across the last twenty-one sessions."),
        "three_month": Label("Over three months", "How far it has moved across the last quarter of trading."),
        "year_to_date": Label("This year", "How far it has moved since the first session of the year."),
        "from_50_day": Label(
            "Against its ten-week average",
            "The close compared with the average of the last fifty sessions, which is the line most "
            "often used to describe the current stretch rather than the long run.",
        ),
        "from_200_day": Label(
            "Against its year average",
            "The close compared with the average of the last two hundred sessions, which is the line "
            "most often used to describe a long-run trend.",
        ),
        "two_hundred_day_slope": Label(
            "Where the trend is pointing",
            "How far the two-hundred day average itself has moved over the last month. The distance "
            "from a line says nothing about which way the line is going.",
        ),
        "realised_volatility_20d": Label(
            "How much it swung",
            "How widely the price moved over the last twenty sessions, stated as a yearly rate. "
            "Higher means a bumpier ride.",
            "percent",
        ),
        "volume_multiple_20d": Label(
            "Trading activity",
            "How much changed hands against the average of the last twenty sessions. 1.00x is an "
            "ordinary day, below that a quieter one, and 2.00x is double the usual.",
            "multiple",
        ),
        "drawdown_from_52_week_high": Label(
            "Below its year high",
            "How far the close sits under the highest price of the last twelve months. Zero means "
            "the session finished at that high.",
        ),
        "above_52_week_low": Label(
            "Above its year low",
            "How far the close sits over the lowest price of the last twelve months. A name 2% off "
            "its high and one 60% off its low are different instruments.",
        ),
        "gap_share_of_move": Label(
            "How much happened overnight",
            "The share of the day's move that was already done at the opening bell. 1.00 is a move "
            "that was over before trading began, 0.00 one that happened entirely during the day.",
            "ratio",
        ),
        "close_location": Label(
            "Where it finished",
            "Where the close sat between the low and the high of the day. 100% is a close on the "
            "high, 0% on the low, 50% in the middle.",
            "share",
        ),
        "up_down_volume_60d": Label(
            "Which side the volume was on",
            "Volume traded on rising days against falling days over the last quarter. Above 1.00 "
            "means more shares changed hands while the price rose.",
            "ratio",
        ),
    }
)

HEADLINE_FIGURES: Final = tuple(HEADLINE)

DEFAULT_TILES: Final = (
    "close",
    "year_to_date",
    "from_200_day",
    "realised_volatility_20d",
    "volume_multiple_20d",
)

BACKDROP: Final[Mapping[str, Label]] = MappingProxyType(
    {
        "vix": Label(
            "Expected swings",
            "The VIX, which is how much movement traders are pricing in for the month ahead.",
            "level",
        ),
        "yield_10y": Label("10-year borrowing cost", "What the US government pays to borrow for ten years.", "yield"),
        "yield_2y": Label("2-year borrowing cost", "What the US government pays to borrow for two years.", "yield"),
        "spread_10s2s": Label(
            "Ten-year minus two-year",
            "The gap between the two, called the 10s2s spread. Positive is the normal shape; "
            "negative has often come before a slowdown.",
            "level",
        ),
        "high_yield_spread": Label(
            "Risky-borrower premium",
            "The extra return demanded to lend to weaker companies. It widens when lenders turn cautious.",
            "level",
        ),
        "dollar_index": Label("US dollar", "The dollar against a basket of other major currencies.", "level"),
        "gold": Label("Gold", "The price of an ounce of gold, in US dollars.", "level"),
        "crude_oil": Label("Crude oil", "The price of a barrel of US crude, in US dollars.", "level"),
    }
)

EVENTS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "earnings": "Results",
        "economic": "Economic releases",
        "ipo": "New listings",
        "split": "Share splits",
    }
)

PanelName = Literal[
    "price",
    "candles",
    "against",
    "sectors",
    "holdings",
    "shape",
    "reactions",
    "backdrop",
    "calendar",
]

PANELS: Final[tuple[PanelName, ...]] = get_args(PanelName)
"""Every panel a writer may lay out, in the order they are drawn when a section holds more than one.

The one list. The tool argument that accepts a panel name, the renderer that dispatches on it and
the gate that decides whether there is data behind it all read from here, because a name that
exists in one of those and not the others is a panel the writer can ask for and never see.
`references/visuals.md` in the writing skill says what each one draws and when it is worth having.
"""

SERIES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "Close": "The closing price of each session over the last year.",
        "50-day average": "The average close of the last fifty sessions, redrawn each day.",
        "200-day average": "The average close of the last two hundred sessions, redrawn each day.",
    }
)
