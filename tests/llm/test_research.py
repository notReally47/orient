"""Batched news research: the fan-out, and what happens when a piece of it fails.

The unit under test is the round-trip arithmetic. Six questions must cost one call to the fast
model, not six, because the provider's daily budget is counted in requests.
"""

from collections.abc import Mapping, Sequence
from typing import Final

import httpx

from orient.llm.chat import (
    Answered,
    AssistantMessage,
    Completion,
    Message,
    Spend,
    ToolSchema,
    Unavailable,
)
from orient.llm.research import Researcher
from orient.llm.search import SearchClient

SYNTHESIS: Final = "Reuters reported that wholesale inflation cooled."


class _Chat:
    def __init__(self, answer: Completion | None = None) -> None:
        self.calls: Final[list[tuple[str, str]]] = []
        self._answer: Final = answer or Answered(message=AssistantMessage(content=SYNTHESIS), spend=Spend())

    async def complete(
        self,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema] = (),
        guardrails: Sequence[str] = (),
        schema: Mapping[str, object] | None = None,
    ) -> Completion:
        del tools, guardrails, schema
        self.calls.append((model, " ".join(message.content for message in messages)))
        return self._answer


def _searching(counter: list[str], *, failing: bool = False) -> SearchClient:
    def handler(request: httpx.Request) -> httpx.Response:
        counter.append(str(request.url))
        if failing:
            return httpx.Response(500, content=b"boom")
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Why it moved",
                        "url": "https://example.test/a",
                        "snippet": "Because inflation cooled.",
                        "date": "2026-08-13T00:00:00.000Z",
                    }
                ]
            },
        )

    client: Final = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://proxy")
    return SearchClient(client, "exa-search")


async def test_many_questions_cost_one_call_to_the_fast_model() -> None:
    """The whole point. Six searches are cheap; six model round trips are a third of a day's budget."""
    searched: Final[list[str]] = []
    chat: Final = _Chat()
    questions: Final = ("why did it fall", "what did CPI say", "did the sector move", "was it broad")

    findings: Final = await Researcher(_searching(searched), chat, "fast-model").investigate(questions)

    assert len(searched) == len(questions)
    assert len(chat.calls) == 1
    assert chat.calls[0][0] == "fast-model"
    assert findings.findings == SYNTHESIS


async def test_every_question_reaches_the_reader_that_answers_them() -> None:
    searched: Final[list[str]] = []
    chat: Final = _Chat()

    _ = await Researcher(_searching(searched), chat, "fast-model").investigate(("first one", "second one"))

    _, prompt = chat.calls[0]
    assert "first one" in prompt
    assert "second one" in prompt


async def test_a_repeated_question_is_asked_once() -> None:
    searched: Final[list[str]] = []

    findings: Final = await Researcher(_searching(searched), _Chat(), "fast-model").investigate(
        ("same thing", "same thing", "other thing")
    )

    assert len(searched) == 2
    assert findings.questions == ("same thing", "other thing")


async def test_a_dead_fast_model_still_hands_over_the_headlines() -> None:
    """Losing the synthesis must not lose the research: the caller gets less, not nothing."""
    searched: Final[list[str]] = []
    chat: Final = _Chat(Unavailable("proxy is down"))

    findings: Final = await Researcher(_searching(searched), chat, "fast-model").investigate(("why",))

    assert "Why it moved" in findings.findings
    assert findings.sources[0].title == "Why it moved"


async def test_a_search_that_fails_is_named_rather_than_hidden() -> None:
    searched: Final[list[str]] = []
    chat: Final = _Chat()

    findings: Final = await Researcher(_searching(searched, failing=True), chat, "fast-model").investigate(
        ("why did it fall",)
    )

    assert findings.unanswered == ("why did it fall",)
    assert chat.calls == []


async def test_a_source_keeps_the_date_the_provider_sent() -> None:
    searched: Final[list[str]] = []

    findings: Final = await Researcher(_searching(searched), _Chat(), "fast-model").investigate(("why",))

    assert findings.sources[0].published == "2026-08-13T00:00:00.000Z"


async def test_a_source_carries_no_url() -> None:
    """A model cannot follow a link. On a live search the URLs were 72% of the tool result and
    the findings they pointed at were 22%, so the link is cost without a reader."""
    searched: Final[list[str]] = []

    findings: Final = await Researcher(_searching(searched), _Chat(), "fast-model").investigate(("why",))

    assert not hasattr(findings.sources[0], "url")
