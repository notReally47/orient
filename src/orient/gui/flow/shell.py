"""The pieces every screen shares: the constants, the session state, and a row of buttons.

Streamlit reruns the whole script on every interaction, so which question is on screen and
what has been answered so far live in session state rather than in a call stack.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from html import escape
from types import MappingProxyType
from typing import Final, NamedTuple

import streamlit as st

from orient.config import GuiEnv
from orient.domain.models import ReadingLevel
from orient.gui import _untyped
from orient.gui.client import Orchestrator, connect

TITLE: Final = "Orient"
GLYPH: Final = "◈"
AVATAR: Final = ":material/query_stats:"
PAGE_ICON: Final = "📈"
POLL: Final = "1s"
DETAIL: Final = "detail"
CHART_HEIGHT: Final = "clamp(16rem, 34vh, 28rem)"
SECTOR_HEIGHT: Final = "clamp(18rem, 38vh, 30rem)"
HOLDINGS_HEIGHT: Final = "clamp(16rem, 32vh, 26rem)"
AGAINST_HEIGHT: Final = "clamp(11rem, 22vh, 17rem)"
REACTIONS_HEIGHT: Final = "clamp(13rem, 26vh, 20rem)"

SECTOR_VIEWS: Final = {"move": "How far each moved", "contribution": "How much each mattered"}
DEFAULT_MARKET: Final = "the US market"
SECTOR_NOTES: Final = {
    "move": (
        "Every sector of {market} that session, ranked by how far it moved. This is the backdrop "
        "the instrument traded against rather than a breakdown of the instrument itself."
    ),
    "contribution": (
        "The same session weighted by how much of {market} each sector carries, so the bars rank "
        "by how much of the index's move they account for rather than by how far they travelled. "
        "Weights come from the tracker that replicates the index, which makes these close to the "
        "index's own arithmetic rather than identical to it."
    ),
}
HISTORY_DAYS: Final = 365
TILES_PER_ROW: Final = 3
SECONDS_PER_MINUTE: Final = 60
WHY: Final = "why"
FAILURE_DETAIL: Final = 160

ASSET_CLASSES: Final = ("Index", "Equity", "ETF", "Currency", "Crypto", "Future", "Fund")

POPULAR: Final[Mapping[str, tuple[tuple[str, str], ...]]] = MappingProxyType(
    {
        "Index": (
            ("^GSPC", "S&P 500"),
            ("^NDX", "Nasdaq 100"),
            ("^DJI", "Dow Jones"),
            ("^FTSE", "FTSE 100"),
            ("^N225", "Nikkei 225"),
            ("^STOXX50E", "Euro Stoxx 50"),
        ),
        "Equity": (
            ("AAPL", "Apple"),
            ("MSFT", "Microsoft"),
            ("NVDA", "NVIDIA"),
            ("AMZN", "Amazon"),
            ("GOOGL", "Alphabet"),
            ("TSLA", "Tesla"),
        ),
        "ETF": (
            ("SPY", "SPDR S&P 500"),
            ("QQQ", "Invesco QQQ"),
            ("VTI", "Vanguard Total Stock Market"),
            ("IWM", "iShares Russell 2000"),
            ("GLD", "SPDR Gold Shares"),
            ("TLT", "iShares 20+ Year Treasury"),
        ),
        "Currency": (
            ("EURUSD=X", "Euro / US dollar"),
            ("GBPUSD=X", "Pound / US dollar"),
            ("USDJPY=X", "US dollar / Japanese yen"),
            ("AUDUSD=X", "Australian / US dollar"),
            ("USDCHF=X", "US dollar / Swiss franc"),
            ("USDCAD=X", "US / Canadian dollar"),
        ),
        "Crypto": (
            ("BTC-USD", "Bitcoin"),
            ("ETH-USD", "Ethereum"),
            ("SOL-USD", "Solana"),
            ("XRP-USD", "XRP"),
            ("ADA-USD", "Cardano"),
            ("DOGE-USD", "Dogecoin"),
        ),
        "Future": (
            ("GC=F", "Gold"),
            ("CL=F", "Crude oil"),
            ("SI=F", "Silver"),
            ("NG=F", "Natural gas"),
            ("ES=F", "S&P 500 E-mini"),
            ("ZC=F", "Corn"),
        ),
        "Fund": (
            ("VFIAX", "Vanguard 500 Index"),
            ("FXAIX", "Fidelity 500 Index"),
            ("VTSAX", "Vanguard Total Stock Market"),
            ("SWPPX", "Schwab S&P 500 Index"),
            ("VBTLX", "Vanguard Total Bond Market"),
            ("VTIAX", "Vanguard Total International Stock"),
        ),
    }
)

REVISIT_PAGE: Final = 12
ANY: Final = "Any"
SHOWN: Final = "shown"
LEVELS: Final[tuple[ReadingLevel, ...]] = ("beginner", "intermediate", "advanced")
RECENT: Final[tuple[str, ...]] = ("Last close", "The one before")


def orchestrator() -> Orchestrator:
    """The client for this browser session, opened once and kept across reruns."""
    if not _untyped.holds("client"):
        _untyped.remember("client", Orchestrator(connect(GuiEnv().orchestrator_base_url)))
    return _untyped.remembered("client", Orchestrator(connect("")))


def reset() -> None:
    _untyped.forget("step", "choice", "watch", "summary", "rendered", "query", SHOWN)


def choice() -> dict[str, object]:
    """What the turns have added up to so far, which is the whole request."""
    if not _untyped.holds("choice"):
        _untyped.remember("choice", {})
    return _untyped.remembered("choice", {})


def advance(step: str, **chosen: object) -> None:
    choice().update(chosen)
    _untyped.remember("step", step)


def asked(question: str, answer: str) -> None:
    """A turn that has been answered, as two sides rather than one block.

    The question and the answer belong to different speakers, and drawing them together reads as
    the assistant talking to itself. The answer is drawn rather than posted as a chat message:
    Streamlit sizes a message from its own line height and leaves the text hanging below any
    border put around it, which at a large window is the whole bubble missing its last line.
    """
    with st.chat_message("assistant", avatar=AVATAR):
        st.markdown(question)
    st.html(f'<div class="orient-said"><span>{escape(answer)}</span></div>')


def text(chosen: dict[str, object], key: str) -> str:
    return str(chosen.get(key, ""))


def instrument_answer(chosen: dict[str, object]) -> str:
    """The instrument as the transcript should read it back: the ticker, and its name if known."""
    name: Final = text(chosen, "name")
    return f"{text(chosen, 'symbol')} · {name}" if name else text(chosen, "symbol")


def session_answer(chosen: dict[str, object]) -> str:
    """The session as the transcript should read it back, spelled out rather than as an ISO date."""
    when: Final = chosen.get("session_date")
    return when.strftime("%d %B %Y") if isinstance(when, date) else ""


ANSWERED: Final[tuple[tuple[str, str, Callable[[dict[str, object]], str]], ...]] = (
    ("entry", "What would you like to look at?", lambda chosen: text(chosen, "entry")),
    ("asset_class", "Which kind of instrument?", lambda chosen: text(chosen, "asset_class")),
    ("symbol", "Which one?", instrument_answer),
    ("session_date", "Which session?", session_answer),
    ("level", "Who is it for?", lambda chosen: text(chosen, "level").title()),
)


def transcript() -> None:
    """Every turn already answered, in the order it was asked.

    The whole conversation stays on screen rather than only the turn before this one. What was
    picked is the request, and a reader choosing a reading level should still be able to see which
    instrument and which session they are choosing it for.
    """
    chosen: Final = choice()
    for key, question, answer in ANSWERED:
        if key in chosen:
            asked(question, answer(chosen))


class Choice(NamedTuple):
    """One option on a row: the words on the button and the icon beside them."""

    label: str
    icon: str


def options(key: str, choices: Sequence[Choice]) -> str | None:
    """A row of choices, answering with the label of whichever was pressed."""
    row: Final = st.container(horizontal=True, horizontal_alignment="left")
    picked: str | None = None
    with row:
        for choice in choices:
            if st.button(choice.label, key=f"{key}-{choice.label}", icon=choice.icon):
                picked = choice.label
    return picked


def class_of(chosen: dict[str, object]) -> str | None:
    """The asset class as the tool layer names it, which is lower case and may be unset."""
    picked: Final = text(chosen, "asset_class").lower()
    return picked or None
