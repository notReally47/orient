"""News search through the proxy's search tool.

Going through the proxy rather than Exa's SDK is what keeps the cost and the trace of a news
lookup in the same place as every model call.
"""

from typing import Final

import httpx
from pydantic import BaseModel, ConfigDict, Field

from orient import correlation
from orient.domain.market import NewsArticle

DEFAULT_RESULTS: Final = 5

TAGS: Final = ("phase:research",)

CATEGORY: Final = "news"


class _Result(BaseModel):
    """`published` is read from either spelling: the proxy's search tool answers `date`, Exa's
    own API answers `publishedDate`, and reading only one silently drops every date."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    title: str = ""
    url: str = ""
    date: str | None = None
    published_date: str | None = Field(default=None, alias="publishedDate")
    text: str | None = None
    snippet: str | None = None

    @property
    def published(self) -> str | None:
        return self.date or self.published_date


class _Payload(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    results: list[_Result] = []
    data: list[_Result] = []

    @property
    def entries(self) -> list[_Result]:
        """Providers disagree on which key holds the rows, so both are read and the fuller wins."""
        return self.results or self.data


class SearchError(RuntimeError):
    """Raised at the boundary so a tool converts it into a typed outcome once."""


class SearchClient:
    def __init__(self, client: httpx.AsyncClient, tool_name: str) -> None:
        self._client: Final = client
        self._tool_name: Final = tool_name

    async def news(
        self,
        query: str,
        count: int = DEFAULT_RESULTS,
        session: str | None = None,
    ) -> tuple[NewsArticle, ...]:
        """Reporting about one question, restricted to news rather than to whatever ranks."""
        response: Final = await self._client.post(
            f"/v1/search/{self._tool_name}",
            json={"query": query, "max_results": count, "category": CATEGORY},
            headers={"x-litellm-tags": ",".join(TAGS), **correlation.headers(session)},
        )
        if not response.is_success:
            message = f"search returned HTTP {response.status_code}: {response.text[:200]}"
            raise SearchError(message)

        payload: Final = _Payload.model_validate_json(response.content)
        return tuple(
            NewsArticle(
                title=entry.title,
                url=entry.url,
                published=entry.published,
                snippet=_snippet(entry),
            )
            for entry in payload.entries
            if entry.url
        )


SNIPPET_LENGTH: Final = 600


def _snippet(entry: _Result) -> str | None:
    """Article bodies run to thousands of words, and only the opening travels.

    The length is set by what the reader can hold rather than by what an article contains. Six
    questions returning five articles each is thirty openings in one prompt, and measured against
    the fast model the same articles answer every question at this length and start coming back
    as "the articles do not say" at twice it. The answer is in the lede either way: what is lost
    beyond the first few hundred characters is background, not the cause of a session's move.
    """
    body: Final = entry.snippet or entry.text
    return None if body is None else body[:SNIPPET_LENGTH]
