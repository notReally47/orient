"""The write boundary, which is the only way a summary comes into existence.

Every guarantee the orchestrator used to hold in Python lives here now, so these tests are the
ones that would let an ungrounded summary reach the database if they stopped passing. They drive
the real tool through a real server, because a refusal has to arrive as a tool result a model can
read rather than an exception somebody remembered to catch.
"""

from dataclasses import replace
from datetime import date
from typing import Final, cast

import httpx
import pytest
from mcp.types import CallToolResult, TextContent
from pydantic import TypeAdapter

from mcp import Client
from orient.domain import grounding
from orient.domain.models import Calendar, Signals
from orient.llm.judge import JudgeClient
from orient.mcp.drafts import grounds
from orient.mcp.server import create_server
from tests.mcp.fakes import TODAY, bar_records, tool_deps
from tests.mcp.test_server import parsed
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


def _inserted_snapshot(pool: FakePool) -> dict[str, object]:
    """The signals `save_summary` handed the repository, read off the recorded INSERT."""
    write: Final = next(q for q in pool.executed if "INSERT INTO summaries" in q.text)
    parameters: Final = cast("dict[str, object]", write.parameters)
    return cast("dict[str, object]", getattr(parameters["signals_snapshot"], "obj", {}))


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


async def _save_with_glossary(markdown: str, glossary: list[dict[str, str]]) -> dict[str, object]:
    async with tool_deps() as deps, Client(create_server(deps)) as client:
        result = await client.call_tool(
            "save_summary",
            {
                "symbol": SYMBOL,
                "session_date": TODAY.isoformat(),
                "level": "beginner",
                "markdown": markdown,
                "page": {"glossary": glossary},
            },
        )
    return _payload(result)


async def _check_glossary(markdown: str, glossary: list[dict[str, str]]) -> dict[str, object]:
    async with tool_deps() as deps, Client(create_server(deps)) as client:
        result = await client.call_tool(
            "check_summary",
            {
                "symbol": SYMBOL,
                "session_date": TODAY.isoformat(),
                "markdown": markdown,
                "glossary": glossary,
            },
        )
    return _payload(result)


NAMES_ITS_WINDOW: Final = [
    {
        "term": "up/down volume ratio",
        "meaning": "Volume on rising days against volume on falling days, over a 60-day window.",
    },
    {
        "term": "close location",
        "meaning": "Where the close sat in the day's range, on a scale from 0.0 at the low to 1.0 at the high.",
    },
    {"term": "trend slope", "meaning": "The direction the 200-day moving average is itself moving."},
]

QUOTES_A_FIGURE: Final = [
    {"term": "trading activity", "meaning": "How busy the session was. Volume came in at 0.87 times its average."},
]


async def test_a_definition_may_name_the_window_the_measurement_is_taken_over() -> None:
    """The control test, and the one that caught a real regression. A digit ban rejected every
    one of these, and the model rewrote them as "a multi-week window" and "the long-term
    trendline", which is worse for the reader and was the check's own doing.
    """
    saved: Final = await _save_with_glossary(GROUNDED, NAMES_ITS_WINDOW)

    assert saved["outcome"] == "saved"


async def test_a_definition_quoting_a_figure_from_this_session_is_refused() -> None:
    """A definition is unchecked text beside checked text, so a measurement in one that could not
    appear in the other is a number the reader cannot tell apart from a measured one."""
    refused: Final = await _save_with_glossary(GROUNDED, QUOTES_A_FIGURE)

    assert refused["outcome"] == "refused"
    assert refused["reason"] == "faults"
    assert any(fault["kind"] == "unmeasured_definition" for fault in cast("list[dict[str, object]]", refused["faults"]))


async def test_the_cheap_check_finds_a_bad_definition_before_a_save_is_spent() -> None:
    """It used to be a schema validator on `save_summary` alone, so the only way to learn was to
    spend a save. `check_summary` is what a draft is supposed to be able to ask for free."""
    assert (await _check_glossary(GROUNDED, QUOTES_A_FIGURE))["ok"] is False
    assert (await _check_glossary(GROUNDED, NAMES_ITS_WINDOW))["ok"] is True


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
    assert refused["reason"] == "faults"
    assert "summary_id" not in refused
    assert "41.93" in str(refused["figures"])


async def test_a_refusal_explains_itself_in_terms_the_model_can_act_on() -> None:
    refused: Final = await _save(INVENTED)

    detail: Final = str(refused["detail"])
    assert "41.93" in detail
    assert "cite a measurement" in detail


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
    check that cannot tell a name from a figure and the profile was not in the evidence. 1.2 is
    the fake profile's beta, and quoting it must be allowed for the same reason."""
    quoting: Final = GROUNDED.replace(
        "It fell with the rest of the market",
        "It moves 1.2 times as far as the market",
    )

    assert (await _save(quoting))["outcome"] == "saved"


async def test_a_summary_the_reviewer_turns_down_is_refused() -> None:
    """Grounding checks the figures; the reviewer checks everything else. Both have to bind at
    the write boundary, because prose arriving as a tool argument never reaches a post-call hook."""

    def blocking(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/apply_guardrail"):
            return httpx.Response(422, json={"error": {"message": "compliance: it forecasts a price"}})
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * 4}]})

    async with (
        tool_deps() as deps,
        httpx.AsyncClient(transport=httpx.MockTransport(blocking), base_url="http://proxy") as client,
    ):
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


async def test_a_dead_vendor_surface_costs_its_evidence_and_not_the_summary() -> None:
    """A live run lost every summary because Yahoo's calendar rejected a stale crumb while its
    prices answered normally. One surface being down must narrow what may be quoted, not stop
    the writing."""

    class _Broken:
        async def entries(self, start: date, end: date, kinds: object = None) -> Calendar:
            del start, end, kinds
            message = "Invalid Crumb"
            raise RuntimeError(message)

    async with tool_deps() as deps, Client(create_server(replace(deps, calendars=_Broken()))) as client:
        result = await client.call_tool(
            "save_summary",
            {
                "symbol": SYMBOL,
                "session_date": TODAY.isoformat(),
                "level": "beginner",
                "markdown": GROUNDED,
            },
        )

    saved: Final = _payload(result)
    assert saved["outcome"] == "saved"


async def test_the_calls_a_save_makes_are_filed_under_the_run_that_asked_for_it() -> None:
    """Storing a summary costs three further proxy calls: the review, the extraction and the
    embeddings. Each is billed, and without the run's session each appears in the dashboard as a
    row belonging to nothing."""
    seen: Final[list[httpx.Request]] = []

    async with tool_deps(seen=seen) as deps, Client(create_server(deps)) as client:
        result = await client.call_tool(
            "save_summary",
            {
                "symbol": SYMBOL,
                "session_date": TODAY.isoformat(),
                "level": "beginner",
                "markdown": GROUNDED,
            },
            meta={"orient/session": "run-9"},
        )

    assert _payload(result)["outcome"] == "saved"
    reached: Final = {request.url.path for request in seen}
    assert "/guardrails/apply_guardrail" in reached
    assert {dict(request.headers).get("x-litellm-session-id") for request in seen} == {"run-9"}


async def test_the_stored_snapshot_carries_the_backdrop_the_prose_quotes() -> None:
    """A summary read back later renders from its own row. Without the backdrop in the snapshot,
    the sector and cross-asset panels have nothing to draw while the prose still cites them."""
    pool: Final = FakePool()

    saved: Final = await _save(GROUNDED, pool)

    assert saved["outcome"] == "saved"
    snapshot: Final = _inserted_snapshot(pool)
    assert snapshot["breadth"] is not None
    assert snapshot["cross_asset"] is not None


async def test_every_figure_the_signals_tool_hands_over_is_one_the_check_will_accept() -> None:
    """The writer and the grounding check must derive the measurements the same way.

    They did not once. The comparison against a benchmark and a sector reached the tool alone, so
    the writer was handed an excess return, quoted it, and was refused by a check that had rebuilt
    the evidence without it — three times in one run before the writer deleted the sentence. A
    feature can be working and unquotable at the same time, and only this catches that.
    """
    async with tool_deps() as deps:
        handed = await create_server(deps).call_tool(
            "compute_instrument_signals", {"symbol": "^GSPC", "session_date": TODAY.isoformat()}
        )
        against = await grounds(deps, "^GSPC", TODAY)

    assert against is not None
    allowed = against.evidence

    quotable: Final = grounding.measured((parsed(handed, Signals).model_dump(mode="json"),))
    assert quotable
    assert quotable <= allowed


async def test_a_summary_silent_about_a_move_that_happened_overnight_is_refused() -> None:
    """The instruction to report this has been in the writing skill since the first summary that
    skipped it, and three consecutive live runs skipped it anyway. A guideline the model reads and
    does not follow is not a control; a refusal is the one thing it demonstrably acts on."""
    gapped: Final = FakePool()

    async with tool_deps(gapped, bars=bar_records(count=3, gap=1.4)) as deps, Client(create_server(deps)) as client:
        result = await client.call_tool(
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
    assert refused["reason"] == "faults"
    assert refused["figures"] == ["shape.gap_share_of_move"]
    assert not any("INSERT INTO summaries" in query.text for query in gapped.executed)


async def test_the_same_summary_is_accepted_once_it_says_where_the_move_happened() -> None:
    """A refusal has to be fixable by writing the sentence, or it is just a wall.

    Citing the split is what settles it, not saying a word like "gapped": an English check passed a
    summary whose only mention of a session was a sentence about fixed income markets.
    """
    said: Final = GROUNDED.replace(
        "It fell with the rest of the market rather than on anything of its own.",
        "It opened {{shape.gap}} away and moved {{shape.intraday}} once trading began.",
    )

    async with tool_deps(bars=bar_records(count=3, gap=1.4)) as deps, Client(create_server(deps)) as client:
        result = await client.call_tool(
            "save_summary",
            {
                "symbol": SYMBOL,
                "session_date": TODAY.isoformat(),
                "level": "beginner",
                "markdown": said,
            },
        )

    assert _payload(result)["outcome"] == "saved"


async def test_the_writer_is_told_which_panels_it_asked_for_were_actually_drawn() -> None:
    """A dropped panel used to be silent, which is the one thing a tool per panel would have given
    that a set of arguments does not. Asking stays free; the writer just finds out afterwards."""
    async with tool_deps() as deps, Client(create_server(deps)) as client:
        result = await client.call_tool(
            "save_summary",
            {
                "symbol": SYMBOL,
                "session_date": TODAY.isoformat(),
                "level": "beginner",
                "markdown": GROUNDED,
                "page": {
                    "layout": [
                        {"name": "price", "section": "The big picture"},
                        {"name": "holdings", "section": "The big picture"},
                        {"name": "reactions", "section": "What moved, and why"},
                    ]
                },
            },
        )

    saved: Final = _payload(result)
    assert saved["outcome"] == "saved"
    assert saved["drawn"] == ["price"]
    assert saved["dropped"] == ["holdings", "reactions"]
