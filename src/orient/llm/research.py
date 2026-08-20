"""Several news questions, answered in one round trip for the caller that asked them.

The expensive resource is not tokens, it is requests: the model provider's free tier meters
twenty per day per project per model. A research loop that spends one primary-model iteration per
question therefore costs a whole run's worth of budget to ask six things.

So the questions arrive together, the searches run concurrently against a provider that is not
metered that way, and one call to the fast model reads everything and answers. The primary model
spends one iteration and never sees the raw articles, which is most of the tokens as well.

The fast model draws on its own separate daily allowance, so the work moves to a budget that is
otherwise barely touched.
"""

from collections.abc import Sequence
from typing import Final

import anyio

from orient.domain.market import NewsArticle, NewsFindings, NewsSource
from orient.llm.chat import Answered, ChatModel, SystemMessage, UserMessage
from orient.llm.search import SearchClient, SearchError

PER_QUESTION: Final = 5
MAX_QUESTIONS: Final = 6
MAX_SOURCES: Final = 6

FRAMING: Final = """\
You are reading news articles so that somebody else does not have to.

Answer each question below from the articles supplied, in two or three sentences each. Say which
question you are answering. Where the articles do not answer one, say so in that many words rather
than reaching for what you already know: an unanswered question is a useful result and a guess is
not.

Attribute what you report. "Reuters reported that" is the register. Do not add analysis of your
own, and do not convert, compute or estimate any figure: whoever reads this cannot use your
numbers and will only have to strip them out.
"""


def _prompt(questions: Sequence[str], found: Sequence[tuple[str, tuple[NewsArticle, ...]]]) -> str:
    blocks: Final = "\n\n".join(
        f"<question>{question}</question>\n"
        + (
            "\n".join(
                f"[{article.published or 'undated'}] {article.title}\n{article.snippet or ''}" for article in articles
            )
            or "no articles came back"
        )
        for question, articles in found
    )
    return "Questions:\n" + "\n".join(f"- {q}" for q in questions) + f"\n\n{blocks}"


class Researcher:
    """Composes the search transport and the fast model. Neither knows about the other."""

    def __init__(self, search: SearchClient, chat: ChatModel, model: str, per_question: int = PER_QUESTION) -> None:
        self._search: Final = search
        self._chat: Final = chat
        self._model: Final = model
        self._per_question: Final = per_question

    async def investigate(self, questions: Sequence[str]) -> NewsFindings:
        asked: Final = tuple(dict.fromkeys(questions))[:MAX_QUESTIONS]
        results: Final[dict[str, tuple[NewsArticle, ...]]] = {}
        failed: Final[list[str]] = []

        async def one(question: str) -> None:
            try:
                results[question] = await self._search.news(question, self._per_question)
            except SearchError:
                failed.append(question)

        async with anyio.create_task_group() as group:
            for question in asked:
                group.start_soon(one, question)

        found: Final = tuple((question, results.get(question, ())) for question in asked)
        articles: Final = tuple(article for _, group_articles in found for article in group_articles if article.url)
        unique: Final = tuple({article.url: article for article in articles}.values())
        sources: Final = tuple(
            NewsSource(title=article.title, published=article.published) for article in unique[:MAX_SOURCES]
        )
        if not articles:
            return NewsFindings(questions=asked, findings="no articles came back", unanswered=asked)

        answer: Final = await self._chat.complete(
            model=self._model,
            messages=[SystemMessage(content=FRAMING), UserMessage(content=_prompt(asked, found))],
        )
        if not isinstance(answer, Answered):
            return NewsFindings(
                questions=asked,
                findings=_unread(found),
                sources=sources,
                unanswered=tuple(failed),
            )
        return NewsFindings(
            questions=asked,
            findings=answer.message.content,
            sources=sources,
            unanswered=tuple(failed),
        )


def _unread(found: Sequence[tuple[str, tuple[NewsArticle, ...]]]) -> str:
    """The fast model was unreachable, so the headlines travel unread rather than not at all."""
    return "\n".join(f"{question}: " + "; ".join(article.title for article in articles) for question, articles in found)
