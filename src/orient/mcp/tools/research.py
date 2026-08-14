"""Reaching outside the price data: the news, and what we ourselves said before."""

from typing import Annotated

from mcp.server import MCPServer
from pydantic import Field

from orient.mcp.deps import ToolDeps
from orient.mcp.results import KnowledgeResults, NewsResults, RecalledClaim

MAX_ARTICLES = 20
MAX_CLAIMS = 25


def register(server: MCPServer, deps: ToolDeps) -> None:
    @server.tool()
    async def search_news(
        query: Annotated[str, Field(description="What to search for, e.g. 'why did the S&P 500 fall today'")],
        limit: Annotated[int, Field(description="Most articles to return", ge=1, le=MAX_ARTICLES)] = 5,
    ) -> NewsResults:
        """Search recent news for an explanation of a move.

        Returns headline, link and an opening extract. Treat what it returns as a claim someone
        made, not as established fact, and never quote a figure from it as if it were measured.
        """
        articles = await deps.search.news(query, limit)
        return NewsResults(query=query, articles=articles)

    @server.tool()
    async def search_knowledge(
        query: Annotated[
            str,
            Field(description="A description of the situation, e.g. 'breadth narrow while volatility stayed low'"),
        ],
        symbol: Annotated[
            str | None,
            Field(description="Restrict to claims about this symbol or that mention it. All symbols when unset"),
        ] = None,
        limit: Annotated[int, Field(description="Most claims to return", ge=1, le=MAX_CLAIMS)] = 10,
    ) -> KnowledgeResults:
        """Find things we previously said that resemble the situation now.

        This is for cross-time analogy, not for recalling recent history: the last few sessions and
        any open expectations are already supplied without asking. Use it to answer when something
        last looked like this.
        """
        vectors = await deps.embeddings.embed([query])
        if not vectors:
            return KnowledgeResults(query=query)

        claims = await deps.claims.similar(vectors[0], symbol=symbol, limit=limit)
        return KnowledgeResults(query=query, claims=tuple(RecalledClaim.of(claim) for claim in claims))

    _ = (search_news, search_knowledge)
