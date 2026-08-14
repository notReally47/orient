"""The tool surface, driven through `call_tool` exactly as a client would.

The schema tests are the ones worth having. A tool whose arguments carry no descriptions still
registers and still answers, so the failure is silent: the model simply chooses arguments badly
and nobody can tell from a green suite.
"""

from dataclasses import replace
from typing import TYPE_CHECKING, Final, TypeVar, cast

import pytest
from pydantic import BaseModel, ConfigDict, TypeAdapter

if TYPE_CHECKING:
    from collections.abc import Mapping

from orient.domain.market import EarningsDetail, InstrumentProfile, MarketContext
from orient.domain.models import Signals
from orient.mcp.results import CalendarEntries, InstrumentMatches, KnowledgeResults, NewsResults
from orient.mcp.server import create_server
from tests.mcp.fakes import fund_reference, tool_deps

Model = TypeVar("Model", bound=BaseModel)


class _Schema(BaseModel):
    """The generated JSON schema, read through a model so its contents are not Any."""

    model_config = ConfigDict(extra="ignore")

    properties: dict[str, dict[str, object]] = {}


def parsed(result: object, model: type[Model]) -> Model:
    """Validate the payload back through the model the tool declared it would return.

    Stronger than reading keys off the dict: it proves the structured content actually
    round-trips into the declared output schema rather than merely resembling it.
    """
    structured: Final = cast("Mapping[str, object] | None", getattr(result, "structured_content", None))
    assert structured is not None
    return TypeAdapter(model).validate_python(structured)


EXPECTED_TOOLS: Final = frozenset(
    {
        "discover_instruments",
        "get_price_history",
        "compute_instrument_signals",
        "get_market_context",
        "get_instrument_profile",
        "get_earnings_detail",
        "get_calendar",
        "search_news",
        "search_knowledge",
    }
)


async def test_every_planned_tool_is_registered() -> None:
    """A tool that fails to register is invisible until a model tries to call it."""
    async with tool_deps() as deps:
        tools = await create_server(deps).list_tools()
    assert {tool.name for tool in tools} == EXPECTED_TOOLS


async def test_every_tool_describes_itself() -> None:
    async with tool_deps() as deps:
        tools = await create_server(deps).list_tools()
    assert all(tool.description for tool in tools)


async def test_every_argument_carries_a_description() -> None:
    """The SDK ignores a docstring Args block, so a missing Annotated Field fails silently."""
    async with tool_deps() as deps:
        tools = await create_server(deps).list_tools()

    undocumented = [
        f"{tool.name}.{argument}"
        for tool in tools
        for argument, schema in _Schema.model_validate(tool.input_schema).properties.items()
        if not schema.get("description")
    ]
    assert undocumented == []


async def test_every_tool_declares_an_output_schema() -> None:
    """Without one a caller gets text back and has to parse prose to find a number."""
    async with tool_deps() as deps:
        tools = await create_server(deps).list_tools()
    assert all(tool.output_schema for tool in tools)


async def test_discovery_merges_ticker_and_name_hits_without_duplicates() -> None:
    async with tool_deps() as deps:
        result = await create_server(deps).call_tool("discover_instruments", {"query": "apple"})

    symbols = [match.symbol for match in parsed(result, InstrumentMatches).matches]
    assert symbols == list(dict.fromkeys(symbols))
    assert "AAPL" in symbols
    assert "MSFT" in symbols


async def test_discovery_uses_the_screen_when_one_is_named() -> None:
    async with tool_deps() as deps:
        result = await create_server(deps).call_tool("discover_instruments", {"screen": "day_gainers"})

    assert [match.symbol for match in parsed(result, InstrumentMatches).matches] == ["NVDA"]


async def test_signals_come_back_computed_rather_than_as_raw_bars() -> None:
    async with tool_deps() as deps:
        result = await create_server(deps).call_tool("compute_instrument_signals", {"symbol": "^GSPC"})

    signals = parsed(result, Signals)
    assert signals.symbol == "^GSPC"
    assert signals.returns.one_day == pytest.approx(1 / 101)
    assert signals.trend.from_200_day is None


async def test_market_context_reports_breadth_as_sector_level() -> None:
    """The field is named sector_breadth so a writer cannot present it as index breadth."""
    async with tool_deps() as deps:
        result = await create_server(deps).call_tool("get_market_context", {})

    context = parsed(result, MarketContext)
    assert context.sector_breadth is not None
    assert context.sector_breadth.advancers + context.sector_breadth.decliners > 0
    assert len(context.sectors) == 11


async def test_market_context_takes_yields_from_the_series_provider() -> None:
    """Yahoo publishes no 2-year index, so the curve spread can only come from FRED."""
    async with tool_deps() as deps:
        result = await create_server(deps).call_tool("get_market_context", {})

    cross = parsed(result, MarketContext).cross_asset
    assert cross.yield_10y == pytest.approx(4.0)
    assert cross.spread_10s2s == pytest.approx(0.5)


async def test_a_profile_dispatches_on_asset_class() -> None:
    async with tool_deps() as deps:
        result = await create_server(deps).call_tool("get_instrument_profile", {"symbol": "AAPL"})

    profile = parsed(result, InstrumentProfile)
    assert profile.asset_class == "equity"
    assert profile.holdings == ()


async def test_a_fund_profile_carries_holdings_an_equity_never_fetches() -> None:
    """The dispatch is what saves an equity two requests it has no use for."""
    async with tool_deps() as deps:
        server = create_server(replace(deps, reference=fund_reference()))
        result = await server.call_tool("get_instrument_profile", {"symbol": "SPY"})

    profile = parsed(result, InstrumentProfile)
    assert profile.asset_class == "etf"
    assert profile.holdings[0].symbol == "NVDA"
    assert profile.sector_weights["technology"] == pytest.approx(0.35)


async def test_earnings_detail_omits_the_implied_move_until_a_price_is_given() -> None:
    async with tool_deps() as deps:
        server = create_server(deps)
        without = await server.call_tool("get_earnings_detail", {"symbol": "AAPL"})
        with_spot = await server.call_tool("get_earnings_detail", {"symbol": "AAPL", "spot": 200.0})

    assert parsed(without, EarningsDetail).implied_move is None
    move = parsed(with_spot, EarningsDetail).implied_move
    assert move is not None
    assert move.implied_volatility == pytest.approx(0.25)


async def test_the_calendar_merges_all_four_sources_soonest_first() -> None:
    async with tool_deps() as deps:
        result = await create_server(deps).call_tool("get_calendar", {"days": 7})

    kinds = [entry.kind for entry in parsed(result, CalendarEntries).entries]
    assert set(kinds) == {"earnings", "economic", "ipo", "split"}
    assert kinds[-1] == "ipo"


async def test_news_search_returns_articles_with_their_source() -> None:
    async with tool_deps() as deps:
        result = await create_server(deps).call_tool("search_news", {"query": "why did it fall"})

    assert parsed(result, NewsResults).articles[0].url == "https://example.test/a"


async def test_knowledge_search_strips_storage_identifiers() -> None:
    """A model has no use for a summary_id and should never be handed one to echo back."""
    async with tool_deps() as deps:
        result = await create_server(deps).call_tool("search_knowledge", {"query": "narrow breadth"})

    recalled = parsed(result, KnowledgeResults)
    assert recalled.claims == ()
    assert "summary_id" not in str(recalled)
