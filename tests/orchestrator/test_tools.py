"""The bridge, driven against the real tool server running in this process.

`mcp.Client` accepts a server instance as well as a URL, so this is the whole path the container
takes: the schemas the model would see are the ones the server generated, and a call goes through
the same validation the wire does. A fake catalog here would test only the fake.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Final

import pytest

from orient.mcp.server import create_server
from orient.orchestrator.tools import McpTools, Refused, Succeeded, connect
from tests.mcp.fakes import tool_deps

if TYPE_CHECKING:
    import httpx

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
        "save_summary",
    }
)


@asynccontextmanager
async def _catalog() -> AsyncGenerator[McpTools, None]:
    async with tool_deps() as deps, connect(create_server(deps)) as tools:
        yield tools


async def test_the_catalog_is_every_tool_the_server_serves() -> None:
    async with _catalog() as tools:
        schemas = tools.schemas()
    assert {schema.name for schema in schemas} == EXPECTED_TOOLS


async def test_each_schema_carries_what_the_model_needs_to_choose() -> None:
    """A tool with no description or an unusable parameter schema still registers and still answers."""
    async with _catalog() as tools:
        schemas = tools.schemas()
    assert all(schema.description for schema in schemas)
    assert all(schema.parameters.get("type") == "object" for schema in schemas)


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("discover_instruments", '{"query": "apple"}'),
        ("get_price_history", '{"symbol": "AAPL", "session_date": "2026-08-12"}'),
        ("compute_instrument_signals", '{"symbol": "AAPL", "session_date": "2026-08-12"}'),
        ("get_market_context", '{"session_date": "2026-08-12"}'),
        ("get_instrument_profile", '{"symbol": "AAPL"}'),
        ("get_earnings_detail", '{"symbol": "AAPL"}'),
        ("get_calendar", '{"session_date": "2026-08-12"}'),
        ("search_news", '{"questions": ["why did the S&P 500 fall"]}'),
        ("search_knowledge", '{"query": "breadth narrow while volatility stayed low"}'),
    ],
)
async def test_every_tool_answers_within_the_schema_it_declared(tool: str, arguments: str) -> None:
    """The client validates structured content against the declared output schema.

    A field that serialises but is not in that schema passes an in-process call and fails on the
    wire, which is a failure nothing before this test could see.
    """
    async with _catalog() as tools:
        outcome = await tools.execute(tool, arguments)
    assert isinstance(outcome, Succeeded), outcome
    assert outcome.structured is not None


async def test_a_call_comes_back_as_structured_content() -> None:
    async with _catalog() as tools:
        outcome = await tools.execute("get_market_context", '{"session_date": "2026-08-12"}')
    assert isinstance(outcome, Succeeded)
    assert outcome.structured is not None
    assert "cross_asset" in outcome.structured
    assert "cross_asset" in outcome.payload


async def test_arguments_reach_the_tool() -> None:
    async with _catalog() as tools:
        arguments = '{"symbol": "AAPL", "session_date": "2026-08-12", "days": 5}'
        outcome = await tools.execute("get_price_history", arguments)
    assert isinstance(outcome, Succeeded)
    assert outcome.structured is not None
    assert outcome.structured["symbol"] == "AAPL"


async def test_an_unserved_tool_is_refused_and_the_served_ones_are_named() -> None:
    async with _catalog() as tools:
        outcome = await tools.execute("get_the_answer", "{}")
    assert isinstance(outcome, Refused)
    assert "get_market_context" in outcome.detail


async def test_arguments_that_are_not_json_are_refused_before_the_call() -> None:
    async with _catalog() as tools:
        outcome = await tools.execute("get_price_history", "symbol=AAPL")
    assert isinstance(outcome, Refused)
    assert "JSON" in outcome.detail


async def test_a_missing_required_argument_is_a_refusal_rather_than_a_raise() -> None:
    """One bad call is not a reason to abandon a run, so the loop gets a value it can report."""
    async with _catalog() as tools:
        outcome = await tools.execute("get_price_history", "{}")
    assert isinstance(outcome, Refused)
    assert outcome.detail


async def test_a_tool_call_carries_its_run_to_the_model_calls_the_tool_makes() -> None:
    """A tool that reaches the proxy spends budget the dashboard should file under the run that
    caused it. Only the caller knows which run that is, and it travels as request metadata rather
    than as an argument, so it is never something the model can set, omit or invent."""
    seen: Final[list[httpx.Request]] = []

    async with tool_deps(seen=seen) as deps, connect(create_server(deps)) as tools:
        outcome = await tools.execute("search_news", '{"questions": ["why did it fall"]}', "run-42")

    assert isinstance(outcome, Succeeded)
    assert seen, "the tool never reached the proxy"
    assert {dict(request.headers).get("x-litellm-session-id") for request in seen} == {"run-42"}


async def test_a_tool_called_outside_a_run_names_no_session() -> None:
    """The header is absent rather than empty, so an unattributed call cannot be grouped with one."""
    seen: Final[list[httpx.Request]] = []

    async with tool_deps(seen=seen) as deps, connect(create_server(deps)) as tools:
        _ = await tools.execute("search_news", '{"questions": ["why did it fall"]}')

    assert all("x-litellm-session-id" not in dict(request.headers) for request in seen)
