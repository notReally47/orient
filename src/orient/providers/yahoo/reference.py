"""Instrument reference data: what a thing is, what analysts expect of it, what options imply."""

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from functools import partial
from math import sqrt
from types import MappingProxyType
from typing import Final

from anyio import to_thread
from pydantic import TypeAdapter

from orient.domain.market import (
    EarningsDetail,
    EarningsEvent,
    EpsRevisions,
    Holding,
    ImpliedMove,
    InstrumentProfile,
    PriceTargets,
    RatingAction,
)
from orient.domain.models import AssetClass, Frozen
from orient.providers._untyped import (
    Records,
    yahoo_earnings_dates,
    yahoo_eps_revisions,
    yahoo_fund_holdings,
    yahoo_fund_sector_weights,
    yahoo_info,
    yahoo_option_calls,
    yahoo_option_expiries,
    yahoo_price_targets,
    yahoo_rating_actions,
)

DAYS_IN_YEAR: Final = 365.0
RECENT_ACTIONS: Final = 10
FUND_CLASSES: Final = frozenset({"etf", "fund"})

REPORTED_QUARTERS: Final = 8

REITERATION: Final = "main"


def _changed_its_mind(row: Mapping[str, object]) -> bool:
    """An upgrade, a downgrade or a new initiation. Never a firm repeating itself."""
    if row.get("action") == REITERATION:
        return False
    to_grade, from_grade = row.get("to_grade"), row.get("from_grade")
    return not (to_grade and to_grade == from_grade)


QUOTE_TYPES: Final[Mapping[str, AssetClass]] = MappingProxyType(
    {
        "EQUITY": "equity",
        "ETF": "etf",
        "INDEX": "index",
        "FUTURE": "future",
        "CURRENCY": "currency",
        "CRYPTOCURRENCY": "crypto",
        "MUTUALFUND": "fund",
    }
)

_PROFILE: Final = TypeAdapter(InstrumentProfile)
_HOLDINGS: Final = TypeAdapter(tuple[Holding, ...])
_EVENTS: Final = TypeAdapter(tuple[EarningsEvent, ...])
_REVISIONS: Final = TypeAdapter(tuple[EpsRevisions, ...])
_TARGETS: Final = TypeAdapter(PriceTargets)
_ACTIONS: Final = TypeAdapter(tuple[RatingAction, ...])
_WEIGHTS: Final = TypeAdapter(Mapping[str, float])


class _Call(Frozen):
    strike: float
    implied_volatility: float | None = None
    last_price: float | None = None
    in_the_money: bool | None = None


_CALLS: Final = TypeAdapter(tuple[_Call, ...])


def _asset_class(info: Mapping[str, object]) -> AssetClass | None:
    return QUOTE_TYPES.get(str(info.get("quoteType") or "").upper())


def _profile_fields(symbol: str, info: Mapping[str, object]) -> Mapping[str, object]:
    return {
        "symbol": symbol,
        "name": info.get("longName") or info.get("shortName"),
        "asset_class": _asset_class(info),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "exchange": info.get("exchange"),
        "currency": info.get("currency"),
        "market_cap": info.get("marketCap"),
        "beta": info.get("beta"),
        "trailing_pe": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "dividend_yield": info.get("dividendYield"),
        "average_volume": info.get("averageVolume"),
        "shares_outstanding": info.get("sharesOutstanding"),
    }


class YahooReference:
    def __init__(
        self,
        info: Callable[[str], Mapping[str, object]] = yahoo_info,
        holdings: Callable[[str], Records] = yahoo_fund_holdings,
        weights: Callable[[str], Mapping[str, object]] = yahoo_fund_sector_weights,
        expiries: Callable[[str], Sequence[str]] = yahoo_option_expiries,
        calls: Callable[[str, str], Records] = yahoo_option_calls,
    ) -> None:
        self._info: Final = info
        self._holdings: Final = holdings
        self._weights: Final = weights
        self._expiries: Final = expiries
        self._calls: Final = calls

    async def profile(self, symbol: str) -> InstrumentProfile:
        return await to_thread.run_sync(partial(self._profile, symbol))

    def _profile(self, symbol: str) -> InstrumentProfile:
        """Fund holdings are fetched only for funds, so an equity costs one request rather than three."""
        info: Final = self._info(symbol)
        base: Final = _PROFILE.validate_python(_profile_fields(symbol, info))
        if base.asset_class not in FUND_CLASSES:
            return base
        return base.model_copy(
            update={
                "holdings": _HOLDINGS.validate_python(self._holdings(symbol)),
                "sector_weights": _WEIGHTS.validate_python(self._weights(symbol)),
            }
        )

    async def implied_move(self, symbol: str, spot: float, today: date) -> ImpliedMove | None:
        return await to_thread.run_sync(partial(self._implied_move, symbol, spot, today))

    def _implied_move(self, symbol: str, spot: float, today: date) -> ImpliedMove | None:
        """The nearest expiry's at-the-money implied volatility, scaled to that expiry.

        One figure, from one expiry. Anything richer invites the writer to talk about options
        positioning, which is a different product and a compliance problem.
        """
        expiries: Final = self._expiries(symbol)
        if not expiries or spot <= 0:
            return None

        expiry: Final = date.fromisoformat(expiries[0])
        calls: Final = _CALLS.validate_python(self._calls(symbol, expiries[0]))
        priced: Final = tuple(call for call in calls if call.implied_volatility)
        if not priced:
            return None

        nearest: Final = min(priced, key=lambda call: abs(call.strike - spot))
        volatility: Final = nearest.implied_volatility or 0.0
        days: Final = max((expiry - today).days, 1)
        return ImpliedMove(
            expiry=expiry,
            implied_volatility=volatility,
            implied_move_percent=volatility * sqrt(days / DAYS_IN_YEAR),
        )


class YahooEarnings:
    def __init__(
        self,
        events: Callable[[str], Records] = yahoo_earnings_dates,
        revisions: Callable[[str], Records] = yahoo_eps_revisions,
        targets: Callable[[str], Mapping[str, object]] = yahoo_price_targets,
        actions: Callable[[str], Records] = yahoo_rating_actions,
    ) -> None:
        self._events: Final = events
        self._revisions: Final = revisions
        self._targets: Final = targets
        self._actions: Final = actions

    async def detail(self, symbol: str, recent: int = RECENT_ACTIONS) -> EarningsDetail:
        return await to_thread.run_sync(partial(self._detail, symbol, recent))

    def _detail(self, symbol: str, recent: int) -> EarningsDetail:
        """Trimmed at both ends, because the long tail of both lists is history rather than news.

        Yahoo returns every earnings event it holds, which for a long-listed company is twenty-five
        quarters reaching back to 2020. What a beat this week means is set by the last two years of
        them; the ones before that are half the answer's length and none of its meaning.

        Rating actions run to hundreds of rows going back years, and most of them are firms
        restating the grade they already had. A reiteration is not a change of mind, so only the
        upgrades, downgrades and initiations survive.

        Forward estimates and their revision history are not here. They describe the next quarter
        and the one after, which is the wrong cadence for a single session: two live summaries were
        handed sixty-four numbers of it between them and quoted none.
        """
        events: Final = _EVENTS.validate_python(self._events(symbol))
        actions: Final = tuple(row for row in self._actions(symbol) if _changed_its_mind(row))
        return EarningsDetail(
            symbol=symbol,
            events=events[:REPORTED_QUARTERS],
            revisions=_REVISIONS.validate_python(self._revisions(symbol)),
            price_targets=_TARGETS.validate_python(self._targets(symbol)),
            recent_actions=_ACTIONS.validate_python(actions[:recent]),
        )
