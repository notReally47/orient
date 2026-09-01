"""Chat completions through the proxy.

The orchestrator depends on `ChatModel` rather than on this implementation, so its tests script
answers instead of standing a transport up. Every answer is a value: a guardrail block and an
unreachable proxy are outcomes the caller matches on, not exceptions it has to remember to catch.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Protocol, assert_never

from openai import APIStatusError, AsyncOpenAI, OpenAIError, omit
from openai.types import CompletionUsage
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionFunctionToolParam,
    ChatCompletionMessage,
    ChatCompletionMessageFunctionToolCallParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionToolUnionParam,
    ChatCompletionUserMessageParam,
)
from openai.types.shared_params import ResponseFormatJSONSchema

from orient.domain.models import Frozen
from orient.llm.limiter import RateLimiter

GUARDRAIL_BLOCKED: Final = 422
FEEDBACK_LENGTH: Final = 1500
DETAIL_LENGTH: Final = 300

TRANSIENT: Final = frozenset({500, 502, 503, 504})

TRANSIENT_ATTEMPTS: Final = 4
TRANSIENT_WAITS: Final = (5.0, 15.0, 30.0)


class ToolCall(Frozen):
    id: str
    name: str
    arguments: str


class SystemMessage(Frozen):
    content: str


class UserMessage(Frozen):
    content: str


class AssistantMessage(Frozen):
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()


class ToolResult(Frozen):
    tool_call_id: str
    content: str


Message = SystemMessage | UserMessage | AssistantMessage | ToolResult


class ToolSchema(Frozen):
    """The input schema the MCP server generated, carried to the model unchanged."""

    name: str
    description: str
    parameters: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class Spend:
    """What one call cost. Which phase it was for is the caller's to say, not the transport's."""

    calls: int = 1
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True, slots=True)
class Answered:
    message: AssistantMessage
    spend: Spend


@dataclass(frozen=True, slots=True)
class Rejected:
    """A post-call guardrail blocked the answer. `feedback` is what the revise prompt restates."""

    feedback: str


@dataclass(frozen=True, slots=True)
class Unavailable:
    detail: str


Completion = Answered | Rejected | Unavailable


class ChatModel(Protocol):
    async def complete(
        self,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema] = (),
        guardrails: Sequence[str] = (),
        schema: Mapping[str, object] | None = None,
        tags: Sequence[str] = (),
        session: str | None = None,
    ) -> Completion: ...


def _as_param(message: Message) -> ChatCompletionMessageParam:
    match message:
        case SystemMessage():
            return ChatCompletionSystemMessageParam(role="system", content=message.content)
        case UserMessage():
            return ChatCompletionUserMessageParam(role="user", content=message.content)
        case ToolResult():
            return ChatCompletionToolMessageParam(
                role="tool",
                tool_call_id=message.tool_call_id,
                content=message.content,
            )
        case AssistantMessage() if not message.tool_calls:
            return ChatCompletionAssistantMessageParam(role="assistant", content=message.content)
        case AssistantMessage():
            return ChatCompletionAssistantMessageParam(
                role="assistant",
                content=message.content,
                tool_calls=[
                    ChatCompletionMessageFunctionToolCallParam(
                        id=call.id,
                        type="function",
                        function={"name": call.name, "arguments": call.arguments},
                    )
                    for call in message.tool_calls
                ],
            )
        case _:
            assert_never(message)


def _as_tool(schema: ToolSchema) -> ChatCompletionToolUnionParam:
    return ChatCompletionFunctionToolParam(
        type="function",
        function={
            "name": schema.name,
            "description": schema.description,
            "parameters": dict(schema.parameters),
        },
    )


def _answer(message: ChatCompletionMessage) -> AssistantMessage:
    """Custom tool calls are dropped: nothing here registers one, so an arriving call is noise."""
    calls: Final = tuple(
        ToolCall(id=call.id, name=call.function.name, arguments=call.function.arguments)
        for call in message.tool_calls or ()
        if call.type == "function"
    )
    return AssistantMessage(content=message.content or "", tool_calls=calls)


def _spent(usage: CompletionUsage | None) -> Spend:
    if usage is None:
        return Spend()
    return Spend(prompt_tokens=usage.prompt_tokens, completion_tokens=usage.completion_tokens)


def _one_line(text: str, limit: int) -> str:
    return " ".join(text.split())[:limit]


Headers = Callable[[], Mapping[str, str]]


def _extras(guardrails: Sequence[str], tags: Sequence[str], session: str | None) -> dict[str, object] | None:
    """Guardrails, tags and the session ride in the body rather than as SDK arguments.

    `litellm_session_id` is what the dashboard groups a conversation by, so every call of one run
    carrying the same value turns a wall of rows into one filterable session. Tags describe what
    a call was, and are the dimension `LiteLLM_DailyTagSpend` aggregates.
    """
    body: Final[dict[str, object]] = {}
    if guardrails:
        body["guardrails"] = list(guardrails)
    if tags:
        body["metadata"] = {"tags": list(tags)}
    if session:
        body["litellm_session_id"] = session
    return body or None


class ProxyChat:
    """Every call goes through the proxy, which is what puts it in one spend and trace record.

    `headers` supplies the outgoing trace context per call. It is a callable rather than a fixed
    mapping because the current span changes between phases, and injected rather than read from
    the global propagator so a test asserts what was sent without standing up a tracer.
    """

    def __init__(
        self,
        client: AsyncOpenAI,
        limiter: RateLimiter,
        headers: Headers,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client: Final = client
        self._limiter: Final = limiter
        self._headers: Final = headers
        self._sleep: Final = sleep

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
        """One turn. A refusal or an exhausted quota comes back as a value rather than an exception.

        `Unavailable` is the whole of the failure surface: the loop above decides whether to wait,
        tell the reader, or stop, and none of those choices belongs to a client.
        """
        for attempt in range(TRANSIENT_ATTEMPTS):
            await self._limiter.acquire()
            try:
                response = await self._client.chat.completions.create(
                    model=model,
                    messages=[_as_param(message) for message in messages],
                    tools=[_as_tool(entry) for entry in tools] if tools else omit,
                    response_format=omit if schema is None else _json_schema(schema),
                    extra_headers=dict(self._headers()),
                    extra_body=_extras(guardrails, tags, session),
                )
            except APIStatusError as exc:
                if exc.status_code == GUARDRAIL_BLOCKED:
                    return Rejected(feedback=_one_line(exc.response.text, FEEDBACK_LENGTH))
                if exc.status_code in TRANSIENT and attempt < TRANSIENT_ATTEMPTS - 1:
                    await self._sleep(TRANSIENT_WAITS[attempt])
                    continue
                return Unavailable(f"HTTP {exc.status_code}: {_one_line(exc.response.text, DETAIL_LENGTH)}")
            except OpenAIError as exc:
                return Unavailable(f"{type(exc).__name__}: {_one_line(str(exc), DETAIL_LENGTH)}")
            break
        else:  # pragma: no cover - the loop always returns or breaks
            return Unavailable("the model stayed unavailable")

        if not response.choices:
            return Unavailable("the model returned no choices")
        return Answered(message=_answer(response.choices[0].message), spend=_spent(response.usage))


def _json_schema(schema: Mapping[str, object]) -> ResponseFormatJSONSchema:
    """`strict` is left off: it demands a closed schema everywhere, which Gemini then rejects."""
    return ResponseFormatJSONSchema(
        type="json_schema",
        json_schema={"name": "answer", "schema": dict(schema)},
    )
