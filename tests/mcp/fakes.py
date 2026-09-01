"""A full set of dependencies wired to canned records.

The providers are real: only the functions that would touch Yahoo, FRED, the proxy and Postgres
are replaced. A tool call therefore runs through the same validation and the same schema the
wire uses, which is the layer most likely to be wrong.
"""

import json
from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Final

import httpx

from orient.domain.models import Observation
from orient.llm.chat import Answered, AssistantMessage, Completion, Message, Spend, ToolSchema
from orient.llm.embeddings import EmbeddingClient
from orient.llm.judge import JudgeClient
from orient.llm.research import Researcher
from orient.llm.search import SearchClient
from orient.mcp.deps import ToolDeps
from orient.providers._untyped import Records
from orient.providers.cache import CachedPrices
from orient.providers.yahoo import (
    YahooCalendars,
    YahooDiscovery,
    YahooEarnings,
    YahooMarket,
    YahooPrices,
    YahooReference,
)
from orient.skills.loader import Skills
from orient.store.bars import BarRepository
from orient.store.claims import ClaimRepository
from orient.store.instruments import InstrumentRepository
from orient.store.sessions import SessionRepository
from orient.store.summaries import SummaryRepository
from tests.store.fakes import FakePool, as_pool

EASTERN: Final = timezone(timedelta(hours=-4), "EDT")
TODAY: Final = date(2026, 8, 12)
DIMENSIONS: Final = 4


def bar_records(count: int = 3, close: float = 100.0, gap: float = 0.0) -> Records:
    """A plain rising series, where each session opens where the last one closed.

    Opening every bar at the same base made each of them gap by a full day's move, which is not
    what an ordinary session looks like and is not what these fixtures are for: the disclosure
    check reads the split between the gap and the session, and a fixture that gaps by construction
    fires it on every test that stores a summary. `gap` is for the tests that want one.
    """
    return tuple(
        {
            "session_date": date(2026, 8, 10 + offset),
            "open": close + offset - 1 + gap if offset else close,
            "high": close + offset + max(gap, 0.0),
            "low": close + offset - 1 + min(gap, 0.0) if offset else close,
            "close": close + offset,
            "volume": 1_000,
        }
        for offset in range(count)
    )


SYNTHESIS: Final = "Reuters reported that wholesale inflation cooled."


class _Synthesiser:
    """The fast model, scripted. The point under test is the fan-out, not what a model says."""

    async def complete(
        self,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema] = (),
        guardrails: Sequence[str] = (),
        schema: Mapping[str, object] | None = None,
        tags: Sequence[str] = (),
        session: str | None = None,
    ) -> Completion:
        del model, messages, tools, guardrails, schema, tags, session
        return Answered(message=AssistantMessage(content=SYNTHESIS), spend=Spend())


class _Series:
    async def observations(self, series_id: str, start: date, end: date) -> tuple[Observation, ...]:
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
    """The payload yfinance builds: the bounds parsed into datetimes, the zone nested by its offset."""
    del region
    return {
        "id": "us",
        "name": "U.S. Markets",
        "status": "closed",
        "open": datetime(2026, 8, 12, 9, 30, tzinfo=EASTERN),
        "close": datetime(2026, 8, 12, 16, 0, tzinfo=EASTERN),
        "timezone": {"gmtoffset": -14400000, "short": "EDT", "long": "Eastern Daylight Time"},
        "tz": EASTERN,
    }


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
    """Yahoo carries the two sides as numbers rather than as a ready-made ratio string."""
    del end
    return ({"symbol": "OLDCO", "company": "Old Co", "payable_on": start, "old_share_worth": 1, "share_worth": 2},)


def _prices(bars: Records | None = None) -> YahooPrices:
    def fetch_one(symbol: str, start: date, end: date) -> Records:
        del symbol, start, end
        return bars if bars is not None else bar_records(count=3)

    def fetch_many(symbols: Sequence[str], start: date, end: date) -> Mapping[str, Records]:
        del start, end
        return {symbol: bar_records(count=3, close=100.0) for symbol in symbols}

    return YahooPrices(fetch_one, fetch_many)


def _proxy_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/apply_guardrail"):
        return httpx.Response(200, content=b'{"guardrail_name": "quality-judge"}')
    if request.url.path.endswith("/embeddings"):
        payload: object = {"data": [{"index": 0, "embedding": [0.1] * DIMENSIONS}]}
    else:
        payload = {
            "results": [
                {
                    "title": "Why it moved",
                    "url": "https://example.test/a",
                    "snippet": "Because inflation cooled.",
                    "date": "2026-08-13T00:00:00.000Z",
                }
            ]
        }
    return httpx.Response(200, content=json.dumps(payload).encode())


@asynccontextmanager
async def tool_deps(
    pool: FakePool | None = None,
    seen: list[httpx.Request] | None = None,
    bars: Records | None = None,
) -> AsyncGenerator[ToolDeps, None]:
    """`seen` collects every request that reached the proxy, for asserting what a call carried.

    `bars` replaces the plain rising series for a test that needs a particular kind of session.
    """
    store: Final = pool if pool is not None else FakePool()

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return _proxy_handler(request)

    transport: Final = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
        prices = CachedPrices(_prices(bars), BarRepository(as_pool(store)))
        synthesiser = _Synthesiser()
        yield ToolDeps(
            prices=prices,
            discovery=YahooDiscovery(_lookup, _search, _screen),
            reference=YahooReference(_info, _holdings, _weights, _expiries, _calls),
            earnings=YahooEarnings(_earnings_events, _revisions, _targets, _actions),
            market=YahooMarket(prices, _Series(), _status, lambda: TODAY),
            calendars=YahooCalendars(_earnings_calendar, _economic_calendar, _ipo_calendar, _splits_calendar),
            research=Researcher(SearchClient(client, "exa-search"), synthesiser, "fast-model"),
            skills=Skills(),
            chat=synthesiser,
            fast_model="fast-model",
            claims=ClaimRepository(as_pool(store)),
            judge=JudgeClient(client, "quality-judge"),
            embeddings=EmbeddingClient(client, "embedding-model", DIMENSIONS),
            instruments=InstrumentRepository(as_pool(store)),
            sessions=SessionRepository(as_pool(store)),
            summaries=SummaryRepository(as_pool(store)),
            clock=lambda: TODAY,
        )


def fund_reference() -> YahooReference:
    """A profile call for an ETF, which is the branch that also fetches holdings and weights."""
    return YahooReference(_fund_info, _holdings, _weights, _expiries, _calls)
