"""Assembling the market backdrop from price series. Pure: no network, no clock.

The ticker sets live here rather than in a provider because they are an editorial choice about
what a summary should mention, not a detail of how Yahoo is called.
"""

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Final

from orient.domain.market import SectorMove
from orient.domain.models import Bar, Breadth, Contributor, CrossAsset, Observation

VIX: Final = "^VIX"

CROSS_ASSET_TICKERS: Final[Mapping[str, str]] = MappingProxyType(
    {
        VIX: "vix",
        "DX-Y.NYB": "dollar_index",
        "CL=F": "crude_oil",
        "GC=F": "gold",
    }
)

# Yields and credit come from FRED rather than Yahoo: Yahoo publishes no 2-year index, so the
# 10s2s spread could not be computed from it at all, and no high-yield spread either.
CROSS_ASSET_SERIES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "DGS10": "yield_10y",
        "DGS2": "yield_2y",
        "BAMLH0A0HYM2": "high_yield_spread",
    }
)

SECTOR_ETFS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "XLB": "Materials",
        "XLC": "Communication Services",
        "XLE": "Energy",
        "XLF": "Financials",
        "XLI": "Industrials",
        "XLK": "Technology",
        "XLP": "Consumer Staples",
        "XLRE": "Real Estate",
        "XLU": "Utilities",
        "XLV": "Health Care",
        "XLY": "Consumer Discretionary",
    }
)

CONTRIBUTOR_COUNT: Final = 3
CLOSES_FOR_A_CHANGE: Final = 2


def _last_close(bars: Sequence[Bar]) -> float | None:
    return bars[-1].close if bars else None


def _session_change(bars: Sequence[Bar]) -> float | None:
    if len(bars) < CLOSES_FOR_A_CHANGE or bars[-2].close == 0:
        return None
    return bars[-1].close / bars[-2].close - 1


def _latest(observations: Sequence[Observation]) -> float | None:
    return observations[-1].value if observations else None


def build_cross_asset(
    bars: Mapping[str, Sequence[Bar]],
    series: Mapping[str, Sequence[Observation]],
) -> CrossAsset:
    levels: Final = {field: _last_close(bars.get(ticker, ())) for ticker, field in CROSS_ASSET_TICKERS.items()}
    rates: Final = {field: _latest(series.get(name, ())) for name, field in CROSS_ASSET_SERIES.items()}
    return CrossAsset(**levels, **rates, vix_change=_session_change(bars.get(VIX, ())))


def build_sector_moves(bars: Mapping[str, Sequence[Bar]]) -> tuple[SectorMove, ...]:
    """Ordered strongest first, so the caller never has to sort to find what led."""
    moves: Final = tuple(
        SectorMove(symbol=symbol, name=name, change_percent=_session_change(bars.get(symbol, ())))
        for symbol, name in SECTOR_ETFS.items()
    )
    return tuple(sorted(moves, key=lambda move: (move.change_percent is None, -(move.change_percent or 0.0))))


def build_sector_breadth(moves: Sequence[SectorMove], count: int = CONTRIBUTOR_COUNT) -> Breadth:
    """Sector-level, never constituent-level. A sector with no price yet counts as neither."""
    measured: Final = tuple(move for move in moves if move.change_percent is not None)
    ranked: Final = tuple(sorted(measured, key=lambda move: -(move.change_percent or 0.0)))
    return Breadth(
        advancers=sum(1 for move in measured if (move.change_percent or 0.0) > 0),
        decliners=sum(1 for move in measured if (move.change_percent or 0.0) < 0),
        unchanged=sum(1 for move in measured if move.change_percent == 0),
        top=tuple(Contributor(symbol=move.symbol, contribution=move.change_percent or 0.0) for move in ranked[:count]),
        bottom=tuple(
            Contributor(symbol=move.symbol, contribution=move.change_percent or 0.0)
            for move in reversed(ranked[-count:])
        ),
    )
