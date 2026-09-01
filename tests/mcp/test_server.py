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

from orient.domain.market import EarningsDetail, InstrumentProfile, MarketContext, NewsFindings
from orient.domain.models import Calendar, Signals
from orient.mcp.results import InstrumentMatches, KnowledgeResults
from orient.mcp.server import create_server
from tests.mcp.fakes import SYNTHESIS, TODAY, fund_reference, tool_deps

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
        "activate_skill",
        "read_skill_resource",
        "discover_instruments",
        "get_price_history",
        "compute_instrument_signals",
        "get_market_context",
        "get_instrument_profile",
        "get_earnings_detail",
        "get_calendar",
        "search_news",
        "recall_history",
        "search_knowledge",
        "find_similar_sessions",
        "check_summary",
        "save_summary",
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
        arguments = {"symbol": "^GSPC", "session_date": TODAY}
        result = await create_server(deps).call_tool("compute_instrument_signals", arguments)

    signals = parsed(result, Signals)
    assert signals.symbol == "^GSPC"
    assert signals.returns.one_day == round(1 / 101, 4)
    assert signals.trend.from_200_day is None


async def test_market_context_reports_breadth_as_sector_level() -> None:
    """The field is named sector_breadth so a writer cannot present it as index breadth."""
    async with tool_deps() as deps:
        result = await create_server(deps).call_tool("get_market_context", {"session_date": TODAY})

    context = parsed(result, MarketContext)
    assert context.sector_breadth is not None
    assert context.sector_breadth.advancers + context.sector_breadth.decliners > 0
    assert len(context.sectors) == 11


async def test_market_context_takes_yields_from_the_series_provider() -> None:
    """Yahoo publishes no 2-year index, so the curve spread can only come from FRED."""
    async with tool_deps() as deps:
        result = await create_server(deps).call_tool("get_market_context", {"session_date": TODAY})

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


async def test_the_calendar_answers_with_earnings_and_nothing_else_by_default() -> None:
    """Yahoo's other three surfaces cost more than they carry, so none of them is asked for.

    The economic one is the reason: it caps at twelve rows drawn from the last day of the window
    however long the window is, and has never returned a US release, so a week containing a CPI
    print reads as an empty week. IPO and split rows are share-class listings and micro-cap
    consolidations. The tool no longer offers them: an argument whose only working value is its
    default is a trap, and the model reads that argument list before it reads any skill.
    """
    async with tool_deps() as deps:
        result = await create_server(deps).call_tool("get_calendar", {"session_date": TODAY, "days": 7})

    kinds = {entry.kind for entry in parsed(result, Calendar).entries}
    assert kinds == {"earnings"}


async def test_the_calendar_offers_no_way_to_reach_the_surfaces_that_were_dropped() -> None:
    """The provider still takes `kinds`, because the tool is not the only caller. What must not
    exist is a tool argument the model can set to reach a surface known to answer badly."""
    async with tool_deps() as deps:
        tools = await create_server(deps).list_tools()

    calendar = next(tool for tool in tools if tool.name == "get_calendar")
    assert "kinds" not in _Schema.model_validate(calendar.input_schema).properties


async def test_news_search_answers_every_question_in_one_call() -> None:
    """Six questions cost one round trip, which is the whole reason the tool takes a list."""
    questions: Final = ("why did it fall", "what did the CPI print say", "did the sector move too")
    async with tool_deps() as deps:
        result = await create_server(deps).call_tool("search_news", {"questions": questions})

    findings: Final = parsed(result, NewsFindings)
    assert findings.questions == questions
    assert findings.findings == SYNTHESIS
    assert findings.sources[0].title == "Why it moved"


async def test_an_article_keeps_the_date_the_search_tool_gave_it() -> None:
    """The proxy answers `date` and Exa answers `publishedDate`. Reading one drops every date,
    and an undated article is one the writer cannot tell from last year's."""
    async with tool_deps() as deps:
        result = await create_server(deps).call_tool("search_news", {"questions": ("why did it fall",)})

    assert parsed(result, NewsFindings).sources[0].published == "2026-08-13T00:00:00.000Z"


async def test_knowledge_search_hands_back_the_claim_id_and_nothing_else_internal() -> None:
    """The claim id is the handle for settling an expectation, so it has to come back. The row it
    hangs off is storage detail a model has no use for."""
    async with tool_deps() as deps:
        result = await create_server(deps).call_tool("search_knowledge", {"query": "narrow breadth"})

    recalled = parsed(result, KnowledgeResults)
    assert recalled.claims == ()
    assert "summary_id" not in str(recalled)
