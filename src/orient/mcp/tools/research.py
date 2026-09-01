"""Reaching outside the price data: the news, and what we ourselves said before."""

from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context
from pydantic import Field

from orient import correlation
from orient.domain.market import NewsFindings
from orient.llm.research import MAX_QUESTIONS
from orient.mcp.deps import ToolDeps


def register(server: MCPServer, deps: ToolDeps) -> None:
    @server.tool()
    async def search_news(
        questions: Annotated[
            tuple[str, ...],
            Field(
                description=(
                    "Every question you want answered, together. Ask full questions with the date "
                    "in them rather than tickers: 'why did semiconductor stocks fall on 13 August "
                    "2026' beats 'NVDA'. One subject per question, because two joined by 'and' "
                    "are searched as one phrase and find articles about neither. Name the market "
                    "as well as the sector: 'real estate' alone returns house prices, while 'the "
                    "real estate sector of the S&P 500' returns the session"
                ),
                min_length=1,
                max_length=MAX_QUESTIONS,
            ),
        ],
        context: Context,
    ) -> NewsFindings:
        """Answer several questions about a move from recent news, in one call.

        Ask everything you want to know at once. The questions are searched in parallel and read
        for you, so asking six costs the same round trip as asking one, and there is no reason to
        hold back on the second question. Depends on the measurements: you cannot ask a good
        question until you know what needs explaining.

        What comes back is somebody's claim about the market rather than a measurement. Use it to
        explain a move; never quote a figure out of it, because no figure in here was measured and
        the grounding check will reject it.
        """
        return await deps.research.investigate(questions, correlation.of(context))

    _ = search_news
