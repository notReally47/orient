"""One place that says what an instrument's session measured.

Three callers need this and they must not disagree. The tool hands the figures to the writer, the
grounding check re-derives them to decide what the writer was allowed to quote, and the snapshot
stores them so the summary can be reopened months later. When those three assemble the answer
separately they drift, and the drift is invisible until a run fails.

It already happened once. The comparison against a benchmark and a sector was added to the tool
alone, so the writer was handed an excess return of 0.0061, wrote "0.61%", and was refused by a
check that had rebuilt the evidence without it — three times in one run, until the writer gave up
and deleted the sentence. The feature was working and unquotable at the same time.

Everything here degrades on its own. A vendor surface that fails costs its own figures and never
the rest, because a summary short one measurement is worth far more than no summary at all.
"""

from collections.abc import Awaitable
from datetime import date, timedelta
from typing import Final

from orient.domain.market import MarketContext
from orient.domain.models import Frozen, Signals
from orient.domain.signals import compute_signals
from orient.mcp.deps import ToolDeps

SIGNALS_LOOKBACK: Final = timedelta(days=400)


async def gathered(source: Awaitable[Frozen | None]) -> Frozen | None:
    """One dead vendor surface costs its own evidence, never the whole summary.

    A vendor can fail one endpoint while serving the rest: Yahoo's calendar rejects a stale crumb
    while its prices answer normally. Letting that reach the caller would mean no summary can be
    written at all while one surface is down. What was lost narrows the set of figures the prose
    may quote, which is the safe direction to fail in.
    """
    try:
        return await source
    except Exception:  # noqa: BLE001  # a vendor raises whatever its client raises
        return None


async def session_signals(
    deps: ToolDeps,
    symbol: str,
    session_date: date,
    context: MarketContext | None = None,
) -> Signals | None:
    """Everything this instrument's own history says about the session, plus what it moved with.

    `context` is the market backdrop, folded in when the caller wants a snapshot that can redraw
    the panels beside the prose. The tool leaves it out because the writer fetches the backdrop
    itself and does not need it twice.
    """
    bars: Final = await deps.prices.bars(symbol, session_date - SIGNALS_LOOKBACK, session_date)
    measured: Final = compute_signals(
        symbol,
        bars,
        breadth=None if context is None else context.sector_breadth,
        sectors=() if context is None else context.sectors,
        sector_market=None if context is None else context.sector_market,
        cross_asset=None if context is None else context.cross_asset,
    )
    if measured is None:
        return None
    profile: Final = await gathered(deps.reference.profile(symbol))
    asset_class: Final = getattr(profile, "asset_class", None)
    sector: Final = getattr(profile, "sector", None)
    exchange: Final = getattr(profile, "exchange", None)
    relative: Final = await gathered(
        deps.market.relative(symbol, measured.returns.one_day, measured.session_date, asset_class, sector, exchange)
    )
    return measured.model_copy(
        update={
            "relative": relative,
            "asset_class": asset_class,
            "currency": getattr(profile, "currency", None),
            "sector": sector,
        }
    )
