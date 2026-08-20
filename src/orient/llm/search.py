"""News search through the proxy's search tool.

Going through the proxy rather than Exa's SDK is what keeps the cost and the trace of a news
lookup in the same place as every model call.
"""

from typing import Final

import httpx
from pydantic import BaseModel, ConfigDict, Field

from orient.domain.market import NewsArticle

DEFAULT_RESULTS: Final = 5


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

    async def news(self, query: str, count: int = DEFAULT_RESULTS) -> tuple[NewsArticle, ...]:
        response: Final = await self._client.post(
            f"/v1/search/{self._tool_name}",
            json={"query": query, "max_results": count},
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


SNIPPET_LENGTH: Final = 1200


def _snippet(entry: _Result) -> str | None:
    """Article bodies run to thousands of words. Only the opening travels, and it goes to the
    fast model to be read rather than to the writer, so it can afford to be longer than a quote."""
    body: Final = entry.snippet or entry.text
    return None if body is None else body[:SNIPPET_LENGTH]
