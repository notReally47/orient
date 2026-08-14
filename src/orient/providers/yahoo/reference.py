"""Instrument reference data: what a thing is, what analysts expect of it, what options imply."""

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from math import sqrt
from types import MappingProxyType
from typing import Final

from pydantic import TypeAdapter

from orient.domain.market import (
    EarningsDetail,
    EarningsEstimate,
    EarningsEvent,
    EpsRevisions,
    EpsTrend,
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
    yahoo_earnings_estimate,
    yahoo_eps_revisions,
    yahoo_eps_trend,
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
_ESTIMATES: Final = TypeAdapter(tuple[EarningsEstimate, ...])
_TREND: Final = TypeAdapter(tuple[EpsTrend, ...])
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
        "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
        "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
        "average_volume": info.get("averageVolume"),
        "shares_outstanding": info.get("sharesOutstanding"),
        "description": info.get("longBusinessSummary"),
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

    def profile(self, symbol: str) -> InstrumentProfile:
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

    def implied_move(self, symbol: str, spot: float, today: date) -> ImpliedMove | None:
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
        estimates: Callable[[str], Records] = yahoo_earnings_estimate,
        trend: Callable[[str], Records] = yahoo_eps_trend,
        revisions: Callable[[str], Records] = yahoo_eps_revisions,
        targets: Callable[[str], Mapping[str, object]] = yahoo_price_targets,
        actions: Callable[[str], Records] = yahoo_rating_actions,
    ) -> None:
        self._events: Final = events
        self._estimates: Final = estimates
        self._trend: Final = trend
        self._revisions: Final = revisions
        self._targets: Final = targets
        self._actions: Final = actions

    def detail(self, symbol: str, recent: int = RECENT_ACTIONS) -> EarningsDetail:
        """Rating actions run to hundreds of rows going back years; only the newest ones inform a day."""
        return EarningsDetail(
            symbol=symbol,
            events=_EVENTS.validate_python(self._events(symbol)),
            estimates=_ESTIMATES.validate_python(self._estimates(symbol)),
            trend=_TREND.validate_python(self._trend(symbol)),
            revisions=_REVISIONS.validate_python(self._revisions(symbol)),
            price_targets=_TARGETS.validate_python(self._targets(symbol)),
            recent_actions=_ACTIONS.validate_python(tuple(self._actions(symbol))[:recent]),
        )
