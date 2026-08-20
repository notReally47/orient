"""The write boundary, which is the only way a summary comes into existence.

Every guarantee the orchestrator used to hold in Python lives here now, so these tests are the
ones that would let an ungrounded summary reach the database if they stopped passing. They drive
the real tool through a real server, because a refusal has to arrive as a tool result a model can
read rather than an exception somebody remembered to catch.
"""

from dataclasses import replace
from typing import Final, cast

import httpx
import pytest
from mcp.types import CallToolResult, TextContent
from pydantic import TypeAdapter

from mcp import Client
from orient.llm.judge import JudgeClient
from orient.mcp.server import create_server
from tests.mcp.fakes import TODAY, tool_deps
from tests.store.fakes import FakePool

_STRUCTURED: Final[TypeAdapter[dict[str, object] | None]] = TypeAdapter(dict[str, object] | None)

SYMBOL: Final = "^GSPC"

GROUNDED: Final = """\
# The index gave back Monday's gain alongside its sector

## The big picture

It fell with the rest of the market rather than on anything of its own.

## What moved, and why

The sector led the decline, and nothing instrument specific explains the rest.
"""

INVENTED: Final = """\
# The index fell 41.93% on the day

## The big picture

It fell 41.93%, its worst session since the crash.
"""


_OUTCOME: Final[TypeAdapter[dict[str, object]]] = TypeAdapter(dict[str, object])


def _payload(result: CallToolResult) -> dict[str, object]:
    structured: Final = _STRUCTURED.validate_python(cast("object", result.structured_content))
    if structured is not None:
        return structured
    text: Final = " ".join(block.text for block in result.content if isinstance(block, TextContent))
    return _OUTCOME.validate_json(text)


async def _save(markdown: str, pool: FakePool | None = None) -> dict[str, object]:
    async with tool_deps(pool) as deps, Client(create_server(deps)) as client:
        result = await client.call_tool(
            "save_summary",
            {
                "symbol": SYMBOL,
                "session_date": TODAY.isoformat(),
                "level": "beginner",
                "markdown": markdown,
            },
        )
    return _payload(result)


async def test_a_grounded_summary_is_accepted_and_gets_an_id() -> None:
    saved: Final = await _save(GROUNDED)

    assert saved["outcome"] == "saved"
    assert saved["summary_id"]
    assert saved["sections"] == 2


async def test_a_figure_nobody_measured_is_refused_rather_than_stored() -> None:
    """The guarantee. A caller that skips this check cannot exist, because there is no other way
    to finish, and the refusal has to name the figure or the model cannot act on it."""
    refused: Final = await _save(INVENTED)

    assert refused["outcome"] == "refused"
    assert refused["reason"] == "grounding"
    assert refused["summary_id"] is None
    assert "41.93" in str(refused["figures"])


async def test_a_refusal_explains_itself_in_terms_the_model_can_act_on() -> None:
    refused: Final = await _save(INVENTED)

    detail: Final = str(refused["detail"])
    assert "41.93" in detail
    assert "Rewrite" in detail


async def test_a_refused_summary_writes_nothing_at_all() -> None:
    """A partial write would leave an instrument and a session row behind for prose that was
    never stored, and the next run would read them as though a summary existed."""
    pool: Final = FakePool()

    _ = await _save(INVENTED, pool)

    assert not any("INSERT INTO summaries" in query.text for query in pool.executed)
    assert not any("INSERT INTO instruments" in query.text for query in pool.executed)


async def test_an_accepted_summary_writes_the_instrument_the_session_and_the_summary() -> None:
    pool: Final = FakePool()

    _ = await _save(GROUNDED, pool)

    written: Final = " ".join(query.text for query in pool.executed)
    assert "INSERT INTO instruments" in written
    assert "INSERT INTO sessions" in written
    assert "INSERT INTO summaries" in written


async def test_the_summary_is_filed_under_the_session_that_actually_traded() -> None:
    """The date asked for is a request; the date measured is a fact, and the row carries the fact."""
    saved: Final = await _save(GROUNDED)

    assert saved["session_date"] == TODAY.isoformat()


@pytest.mark.parametrize("markdown", ["", "no headings at all, just a sentence."])
async def test_prose_without_the_spine_is_still_checked_rather_than_crashing(markdown: str) -> None:
    """The parser is deliberately forgiving, so a shapeless draft must reach the gate and be
    judged on its figures rather than blow up on its missing headings."""
    outcome: Final = await _save(markdown)

    assert outcome["outcome"] == "saved"
    assert outcome["sections"] == 0


async def test_the_profile_is_part_of_the_evidence() -> None:
    """A live run had "S&P 500" refused, because the instrument's own name is a numeral to a
    check that cannot tell a name from a figure and the profile was not in the evidence. 260 is
    the fake profile's 52-week high, and quoting it must be allowed for the same reason."""
    quoting: Final = GROUNDED.replace(
        "It fell with the rest of the market",
        "It sits below its 52-week high of 260",
    )

    assert (await _save(quoting))["outcome"] == "saved"


async def test_a_summary_the_reviewer_turns_down_is_refused() -> None:
    """Grounding checks the figures; the reviewer checks everything else. Both have to bind at
    the write boundary, because prose arriving as a tool argument never reaches a post-call hook."""

    def blocking(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/apply_guardrail"):
            return httpx.Response(422, json={"error": {"message": "compliance: it forecasts a price"}})
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * 4}]})

    async with tool_deps() as deps, httpx.AsyncClient(
        transport=httpx.MockTransport(blocking), base_url="http://proxy"
    ) as client:
        strict = replace(deps, judge=JudgeClient(client, "quality-judge"))
        async with Client(create_server(strict)) as mcp:
            result = await mcp.call_tool(
                "save_summary",
                {
                    "symbol": SYMBOL,
                    "session_date": TODAY.isoformat(),
                    "level": "beginner",
                    "markdown": GROUNDED,
                },
            )

    refused: Final = _payload(result)
    assert refused["outcome"] == "refused"
    assert refused["reason"] == "quality"
    assert "forecasts a price" in str(refused["detail"])
