"""The chat client, driven through the SDK against a mock transport.

The request body is asserted as well as the answer, because a guardrail that is never named and
a trace header that is never sent both look exactly like success from the caller's side.
"""

import json
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Final

import httpx2
import pytest
from openai import AsyncOpenAI
from pydantic import TypeAdapter

from orient.llm.chat import (
    TRANSIENT_ATTEMPTS,
    TRANSIENT_WAITS,
    Answered,
    AssistantMessage,
    ProxyChat,
    Rejected,
    SystemMessage,
    ToolCall,
    ToolResult,
    ToolSchema,
    Unavailable,
    UserMessage,
)
from orient.llm.limiter import RateLimiter

Handler = Callable[[httpx2.Request], httpx2.Response]

_BODY: Final = TypeAdapter(dict[str, object])
TRACEPARENT: Final = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"


async def _no_sleep(seconds: float) -> None:
    del seconds


def _completion(
    content: str | None = "ready",
    tool_calls: Sequence[Mapping[str, object]] = (),
    choices: int = 1,
) -> dict[str, object]:
    message: Final[Mapping[str, object]] = {"role": "assistant", "content": content} | (
        {"tool_calls": list(tool_calls)} if tool_calls else {}
    )
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": "primary-model",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}] * choices,
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }


def _responds(payload: object, status: int = 200) -> Handler:
    def handler(request: httpx2.Request) -> httpx2.Response:
        del request
        return httpx2.Response(status, content=json.dumps(payload).encode())

    return handler


class _Recorder:
    """Captures what actually went over the wire, which is the half a returned answer cannot show."""

    def __init__(self, payload: object) -> None:
        self._payload: Final = payload
        self.body: dict[str, object] = {}
        self.headers: Mapping[str, str] = {}

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.body = _BODY.validate_json(request.content)
        self.headers = dict(request.headers)
        return httpx2.Response(200, content=json.dumps(self._payload).encode())


@asynccontextmanager
async def _chat(handler: Handler) -> AsyncGenerator[ProxyChat, None]:
    async with AsyncOpenAI(
        api_key="sk-test",
        base_url="http://proxy/v1",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    ) as client:
        yield ProxyChat(
            client,
            RateLimiter(15, sleep=_no_sleep),
            lambda: {"traceparent": TRACEPARENT},
            sleep=_no_sleep,
        )


async def test_an_answer_carries_its_content_and_what_it_cost() -> None:
    async with _chat(_responds(_completion())) as chat:
        result = await chat.complete("primary-model", [UserMessage(content="hello")])

    assert isinstance(result, Answered)
    assert result.message.content == "ready"
    assert result.spend.calls == 1
    assert result.spend.prompt_tokens == 11
    assert result.spend.completion_tokens == 7


async def test_tool_calls_come_back_parsed() -> None:
    calls: Final[Sequence[Mapping[str, object]]] = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "get_market_context", "arguments": '{"symbol": "^GSPC"}'},
        }
    ]
    async with _chat(_responds(_completion(content=None, tool_calls=calls))) as chat:
        result = await chat.complete("primary-model", [UserMessage(content="what moved")])

    assert isinstance(result, Answered)
    assert result.message.content == ""
    assert result.message.tool_calls == (
        ToolCall(id="call_1", name="get_market_context", arguments='{"symbol": "^GSPC"}'),
    )


async def test_a_blocked_answer_is_a_rejection_carrying_its_feedback() -> None:
    """The judge blocks with 422. Losing the verdicts here would leave the revise loop nothing to say."""
    blocked: Final = {"error": {"message": "faithfulness 42/100: the 1.9% figure is not in the data"}}
    async with _chat(_responds(blocked, status=422)) as chat:
        result = await chat.complete("primary-model", [UserMessage(content="write it")])

    assert isinstance(result, Rejected)
    assert "faithfulness" in result.feedback
    assert "1.9%" in result.feedback


@pytest.mark.parametrize("status", [400, 429, 500, 503])
async def test_any_other_status_is_unavailable_rather_than_a_rejection(status: int) -> None:
    async with _chat(_responds({"error": "nope"}, status=status)) as chat:
        result = await chat.complete("primary-model", [UserMessage(content="hello")])

    assert isinstance(result, Unavailable)
    assert str(status) in result.detail


async def test_a_transport_failure_is_a_value_rather_than_an_exception() -> None:
    def explode(request: httpx2.Request) -> httpx2.Response:
        del request
        message = "All connection attempts failed"
        raise httpx2.ConnectError(message)

    async with _chat(explode) as chat:
        result = await chat.complete("primary-model", [UserMessage(content="hello")])

    assert isinstance(result, Unavailable)
    assert "connection" in result.detail.lower()


async def test_an_empty_choice_list_is_unavailable() -> None:
    async with _chat(_responds(_completion(choices=0))) as chat:
        result = await chat.complete("primary-model", [UserMessage(content="hello")])

    assert isinstance(result, Unavailable)


async def test_guardrails_the_schema_and_the_trace_reach_the_request() -> None:
    recorder: Final = _Recorder(_completion())
    async with _chat(recorder) as chat:
        _ = await chat.complete(
            "primary-model",
            [UserMessage(content="write it")],
            guardrails=["headroom-compression", "quality-judge"],
            schema={"type": "object", "properties": {"claims": {"type": "array"}}},
        )

    assert recorder.body["guardrails"] == ["headroom-compression", "quality-judge"]
    assert recorder.headers["traceparent"] == TRACEPARENT
    assert recorder.body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "answer", "schema": {"type": "object", "properties": {"claims": {"type": "array"}}}},
    }


async def test_no_guardrails_and_no_schema_leaves_both_off_the_request() -> None:
    """Naming a guardrail that was not asked for would apply a judge to a gather-phase call."""
    recorder: Final = _Recorder(_completion())
    async with _chat(recorder) as chat:
        _ = await chat.complete("fast-model", [UserMessage(content="hello")])

    assert "guardrails" not in recorder.body
    assert "response_format" not in recorder.body
    assert "tools" not in recorder.body


async def test_the_whole_transcript_survives_the_round_trip() -> None:
    """A tool result that loses its call id makes the model answer about the wrong tool."""
    recorder: Final = _Recorder(_completion())
    transcript: Final = [
        SystemMessage(content="you are an analyst"),
        UserMessage(content="summarise ^GSPC"),
        AssistantMessage(tool_calls=(ToolCall(id="call_1", name="get_calendar", arguments="{}"),)),
        ToolResult(tool_call_id="call_1", content='{"entries": []}'),
    ]

    async with _chat(recorder) as chat:
        _ = await chat.complete(
            "primary-model",
            transcript,
            tools=[ToolSchema(name="get_calendar", description="what is scheduled", parameters={"type": "object"})],
        )

    assert recorder.body["messages"] == [
        {"role": "system", "content": "you are an analyst"},
        {"role": "user", "content": "summarise ^GSPC"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "get_calendar", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"entries": []}'},
    ]
    assert recorder.body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "get_calendar",
                "description": "what is scheduled",
                "parameters": {"type": "object"},
            },
        }
    ]


async def test_a_model_that_says_not_right_now_is_asked_again() -> None:
    """A demand spike answers in milliseconds and passes. Throwing away eight turns of research
    for one of them wastes the quota those turns cost."""
    attempts: Final[list[int]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        del request
        attempts.append(1)
        if len(attempts) < 3:
            return httpx2.Response(503, content=b'{"error":{"message":"high demand"}}')
        return httpx2.Response(200, content=json.dumps(_completion()).encode())

    async with _chat(handler) as chat:
        result = await chat.complete("primary-model", [UserMessage(content="hello")])

    assert isinstance(result, Answered)
    assert len(attempts) == 3


async def test_a_model_that_stays_unavailable_gives_up_rather_than_looping() -> None:
    attempts: Final[list[int]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        del request
        attempts.append(1)
        return httpx2.Response(503, content=b'{"error":{"message":"high demand"}}')

    async with _chat(handler) as chat:
        result = await chat.complete("primary-model", [UserMessage(content="hello")])

    assert isinstance(result, Unavailable)
    assert len(attempts) == TRANSIENT_ATTEMPTS


async def test_a_spent_daily_allowance_is_not_retried() -> None:
    """A quota is still spent a second later, so asking again only burns time."""
    attempts: Final[list[int]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        del request
        attempts.append(1)
        return httpx2.Response(429, content=b'{"error":{"message":"quota"}}')

    async with _chat(handler) as chat:
        result = await chat.complete("primary-model", [UserMessage(content="hello")])

    assert isinstance(result, Unavailable)
    assert len(attempts) == 1


async def test_the_waits_cover_every_retry_the_budget_allows() -> None:
    """A backoff table shorter than the attempt count silently indexes off the end."""
    assert len(TRANSIENT_WAITS) == TRANSIENT_ATTEMPTS - 1


async def test_how_long_a_spike_can_last_before_the_run_is_given_up_on() -> None:
    """Records the tolerance rather than asserting a number for its own sake: a spike measured
    against this upstream ran about a minute, and the budget has to exceed that with room."""
    assert sum(TRANSIENT_WAITS) >= 45
