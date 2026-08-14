"""A full set of dependencies wired to canned records.

The providers are real: only the functions that would touch Yahoo, FRED, the proxy and Postgres
are replaced. A tool call therefore runs through the same validation and the same schema the
wire uses, which is the layer most likely to be wrong.
"""

import json
from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import date
from typing import Final

import httpx

from orient.domain.models import Observation
from orient.llm.embeddings import EmbeddingClient
from orient.llm.search import SearchClient
from orient.mcp.deps import ToolDeps
from orient.providers._untyped import Records
from orient.providers.yahoo import (
    YahooCalendars,
    YahooContext,
    YahooDiscovery,
    YahooEarnings,
    YahooPrices,
    YahooReference,
)
from orient.store.claims import ClaimRepository
from tests.store.fakes import FakePool, as_pool

TODAY: Final = date(2026, 8, 12)
DIMENSIONS: Final = 4


def bar_records(count: int = 3, close: float = 100.0) -> Records:
    return tuple(
        {
            "session_date": date(2026, 8, 10 + offset),
            "open": close,
            "high": close,
            "low": close,
            "close": close + offset,
            "volume": 1_000,
        }
        for offset in range(count)
    )


class _Series:
    def observations(self, series_id: str, start: date, end: date) -> tuple[Observation, ...]:
        del start, end
        return (Observation(observation_date=TODAY, value=4.0 if series_id == "DGS10" else 3.5),)


def _lookup(query: str, kind: str, count: int) -> Records:
    del kind, count
    return (
        {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "quote_type": "EQUITY",
            "exchange": "NMS",
            "industry": "Consumer Electronics",
            "price": 200.0,
            "change_percent": 1.5,
        },
        {"symbol": f"{query.upper()}.X", "name": "Other listing", "quote_type": "EQUITY"},
    )


def _search(query: str, count: int) -> Records:
    del query, count
    return (
        {"symbol": "AAPL", "name": "Apple Inc. (name match)", "quote_type": "EQUITY"},
        {"symbol": "MSFT", "name": "Microsoft", "quote_type": "EQUITY"},
    )


def _screen(key: str, count: int) -> Records:
    del key, count
    return ({"symbol": "NVDA", "name": "NVIDIA", "price": 900.0, "change_percent": 7.0},)


def _info(symbol: str) -> Mapping[str, object]:
    return {
        "longName": "Apple Inc.",
        "quoteType": "EQUITY",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "exchange": "NMS",
        "currency": "USD",
        "marketCap": 3_000_000_000_000,
        "beta": 1.2,
        "trailingPE": 30.0,
        "fiftyTwoWeekHigh": 260.0,
        "fiftyTwoWeekLow": 160.0,
        "longBusinessSummary": f"A description of {symbol}.",
    }


def _fund_info(symbol: str) -> Mapping[str, object]:
    del symbol
    return {"longName": "SPDR S&P 500 ETF", "quoteType": "ETF", "currency": "USD", "exchange": "PCX"}


def _holdings(symbol: str) -> Records:
    del symbol
    return ({"symbol": "NVDA", "name": "NVIDIA", "weight": 0.07},)


def _weights(symbol: str) -> Mapping[str, object]:
    del symbol
    return {"technology": 0.35, "financial_services": 0.13}


def _expiries(symbol: str) -> Sequence[str]:
    del symbol
    return ("2026-08-19", "2026-09-18")


def _calls(symbol: str, expiry: str) -> Records:
    del symbol, expiry
    return (
        {"strike": 180.0, "last_price": 22.0, "implied_volatility": 0.40, "in_the_money": True},
        {"strike": 200.0, "last_price": 5.0, "implied_volatility": 0.25, "in_the_money": False},
        {"strike": 220.0, "last_price": 1.0, "implied_volatility": 0.35, "in_the_money": False},
    )


def _earnings_events(symbol: str) -> Records:
    del symbol
    return ({"event_date": date(2026, 7, 30), "eps_estimate": 1.4, "reported_eps": 1.5, "surprise_percent": 7.1},)


def _estimates(symbol: str) -> Records:
    del symbol
    return ({"period": "0q", "average": 1.6, "low": 1.4, "high": 1.8, "analysts": 30, "growth": 0.1},)


def _trend(symbol: str) -> Records:
    del symbol
    return ({"period": "0q", "current": 1.6, "days_ago_7": 1.59, "days_ago_30": 1.55},)


def _revisions(symbol: str) -> Records:
    del symbol
    return ({"period": "0q", "up_last_7_days": 2, "down_last_7_days": 0},)


def _targets(symbol: str) -> Mapping[str, object]:
    del symbol
    return {"current": 200.0, "low": 150.0, "high": 300.0, "mean": 240.0, "median": 235.0}


def _actions(symbol: str) -> Records:
    del symbol
    return tuple(
        {"graded_at": date(2026, 8, day), "firm": "A Firm", "to_grade": "Buy", "action": "up"} for day in (1, 2, 3)
    )


def _status(region: str) -> Mapping[str, object]:
    del region
    return {"name": "US", "status": "closed", "open": "09:30", "close": "16:00", "timezone": "EST"}


def _companies(key: str) -> Records:
    del key
    return ({"symbol": "NVDA", "name": "NVIDIA", "rating": "Buy", "market_weight": 0.08},)


def _overview(key: str) -> Mapping[str, object]:
    del key
    return {"market_weight": 0.32, "companies_count": 800}


def _earnings_calendar(start: date, end: date) -> Records:
    del end
    return ({"symbol": "MSFT", "company": "Microsoft", "starts_at": start, "timing": "After close"},)


def _economic_calendar(start: date, end: date) -> Records:
    del end
    return ({"event": "CPI", "region": "US", "event_time": start},)


def _ipo_calendar(start: date, end: date) -> Records:
    del start, end
    return ({"symbol": "NEWCO", "company": "New Co", "exchange": "NMS", "event_date": None},)


def _splits_calendar(start: date, end: date) -> Records:
    del end
    return ({"symbol": "OLDCO", "company": "Old Co", "payable_on": start, "share_worth": "2 for 1"},)


def _prices() -> YahooPrices:
    def fetch_one(symbol: str, period: str) -> Records:
        del symbol, period
        return bar_records(count=3)

    def fetch_many(symbols: Sequence[str], period: str) -> Mapping[str, Records]:
        del period
        return {symbol: bar_records(count=3, close=100.0) for symbol in symbols}

    return YahooPrices(fetch_one, fetch_many)


def _proxy_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/embeddings"):
        payload: object = {"data": [{"index": 0, "embedding": [0.1] * DIMENSIONS}]}
    else:
        payload = {"results": [{"title": "Why it moved", "url": "https://example.test/a", "text": "Because."}]}
    return httpx.Response(200, content=json.dumps(payload).encode())


@asynccontextmanager
async def tool_deps(pool: FakePool | None = None) -> AsyncGenerator[ToolDeps, None]:
    store: Final = pool if pool is not None else FakePool()
    transport: Final = httpx.MockTransport(_proxy_handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
        yield ToolDeps(
            prices=_prices(),
            discovery=YahooDiscovery(_lookup, _search, _screen),
            reference=YahooReference(_info, _holdings, _weights, _expiries, _calls),
            earnings=YahooEarnings(_earnings_events, _estimates, _trend, _revisions, _targets, _actions),
            context=YahooContext(_status, _companies, _overview),
            calendars=YahooCalendars(_earnings_calendar, _economic_calendar, _ipo_calendar, _splits_calendar),
            series=_Series(),
            search=SearchClient(client, "exa-search"),
            claims=ClaimRepository(as_pool(store)),
            embeddings=EmbeddingClient(client, "embedding-model", DIMENSIONS),
            clock=lambda: TODAY,
        )


def fund_reference() -> YahooReference:
    """A profile call for an ETF, which is the branch that also fetches holdings and weights."""
    return YahooReference(_fund_info, _holdings, _weights, _expiries, _calls)
