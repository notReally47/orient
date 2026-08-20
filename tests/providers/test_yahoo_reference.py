"""Profile dispatch and the implied-move arithmetic.

The implied move is the one figure this system derives from options, so the strike it picks and
the scaling it applies both matter: a wrong strike quotes the wrong volatility, and unscaled
volatility is an annual number presented as a weekly one.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Final

import pytest

from orient.providers._untyped import Records
from orient.providers.yahoo.reference import YahooEarnings, YahooReference

TODAY: Final = date(2026, 8, 12)
EXPIRY: Final = "2026-08-19"


def _info(quote_type: str) -> Mapping[str, object]:
    return {"longName": "A Thing", "quoteType": quote_type, "currency": "USD"}


def _holdings(symbol: str) -> Records:
    del symbol
    return ({"symbol": "NVDA", "name": "NVIDIA", "weight": 0.07},)


def _weights(symbol: str) -> Mapping[str, object]:
    del symbol
    return {"technology": 0.35}


def _expiries(symbol: str) -> Sequence[str]:
    del symbol
    return (EXPIRY, "2026-09-18")


def _calls(symbol: str, expiry: str) -> Records:
    del symbol, expiry
    return (
        {"strike": 150.0, "implied_volatility": 0.90},
        {"strike": 200.0, "implied_volatility": 0.20},
        {"strike": 260.0, "implied_volatility": 0.70},
    )


def _reference(quote_type: str = "EQUITY") -> YahooReference:
    def info(symbol: str) -> Mapping[str, object]:
        del symbol
        return _info(quote_type)

    return YahooReference(info, _holdings, _weights, _expiries, _calls)


def _equity_info(symbol: str) -> Mapping[str, object]:
    del symbol
    return _info("EQUITY")


async def test_an_equity_profile_skips_the_fund_requests() -> None:
    profile: Final = await _reference("EQUITY").profile("AAPL")
    assert profile.asset_class == "equity"
    assert profile.holdings == ()
    assert profile.sector_weights == {}


async def test_a_fund_profile_carries_holdings_and_weights() -> None:
    profile: Final = await _reference("ETF").profile("SPY")
    assert profile.asset_class == "etf"
    assert profile.holdings[0].weight == pytest.approx(0.07)
    assert profile.sector_weights["technology"] == pytest.approx(0.35)


async def test_an_unknown_quote_type_leaves_the_asset_class_unset() -> None:
    """Guessing a class would send the writer to the wrong instrument skill."""
    assert (await _reference("SOMETHING_NEW").profile("???")).asset_class is None


async def test_the_implied_move_uses_the_strike_nearest_the_price() -> None:
    move: Final = await _reference().implied_move("AAPL", 205.0, TODAY)
    assert move is not None
    assert move.implied_volatility == pytest.approx(0.20)


async def test_the_implied_move_is_scaled_to_the_expiry_not_left_annual() -> None:
    """Seven days of a 20% annual volatility is well under 20%, and quoting 20% would be wrong."""
    move: Final = await _reference().implied_move("AAPL", 200.0, TODAY)
    assert move is not None
    assert move.expiry == date.fromisoformat(EXPIRY)
    assert move.implied_move_percent == pytest.approx(0.20 * (7 / 365) ** 0.5)


async def test_no_listed_expiry_means_no_figure_rather_than_a_zero() -> None:
    def none_listed(symbol: str) -> Sequence[str]:
        del symbol
        return ()

    reference: Final = YahooReference(_equity_info, _holdings, _weights, none_listed, _calls)
    assert await reference.implied_move("AAPL", 200.0, TODAY) is None


async def test_an_unpriced_chain_means_no_figure() -> None:
    def unpriced(symbol: str, expiry: str) -> Records:
        del symbol, expiry
        return ({"strike": 200.0, "implied_volatility": None},)

    reference: Final = YahooReference(_equity_info, _holdings, _weights, _expiries, unpriced)
    assert await reference.implied_move("AAPL", 200.0, TODAY) is None


async def test_a_nonsense_price_is_refused_rather_than_dividing_through() -> None:
    assert await _reference().implied_move("AAPL", 0.0, TODAY) is None


async def test_rating_actions_are_truncated_to_the_recent_ones() -> None:
    """The upstream frame runs to hundreds of rows going back years; only the newest inform a day."""

    def many(symbol: str) -> Records:
        del symbol
        return tuple({"graded_at": date(2026, 8, 1), "firm": f"Firm {index}"} for index in range(50))

    def empty(symbol: str) -> Records:
        del symbol
        return ()

    def targets(symbol: str) -> Mapping[str, object]:
        del symbol
        return {"mean": 240.0}

    earnings: Final = YahooEarnings(empty, empty, empty, empty, targets, many)
    assert len((await earnings.detail("AAPL", recent=5)).recent_actions) == 5
