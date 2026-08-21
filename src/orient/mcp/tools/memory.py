"""What we measured before, and what we said about it.

The numeric layer answers with figures that were computed anyway, so a streak or a range is a
query rather than a stored fact and cannot go stale. The narrative layer answers with what a
previous summary asserted, which is the part no aggregation can reconstruct.
"""

from typing import Annotated, Final

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context
from pydantic import Field

from orient import correlation
from orient.domain.models import SIGNALS_VERSION
from orient.mcp.deps import ToolDeps
from orient.mcp.results import KnowledgeResults, PriorSession, RecalledClaim, Recollection

MAX_SESSIONS: Final = 20
MAX_CLAIMS: Final = 25


def register(server: MCPServer, deps: ToolDeps) -> None:
    @server.tool()
    async def recall_history(
        symbol: Annotated[str, Field(description="The instrument whose past sessions you want")],
        sessions: Annotated[
            int,
            Field(description="How many prior sessions of measurements to return", ge=1, le=MAX_SESSIONS),
        ] = 10,
    ) -> Recollection:
        """What this instrument has been doing lately, and what earlier summaries left open.

        Returns the measured figures for recent sessions alongside expectations a previous summary
        recorded and nothing has resolved yet. Call it early: a move only reads as unusual against
        what came before, and an open expectation is the one thing a summary is obliged to revisit.
        """
        recent = await deps.sessions.recent(symbol, SIGNALS_VERSION, sessions)
        open_claims = await deps.claims.open_for(symbol)
        return Recollection(
            symbol=symbol,
            sessions=tuple(PriorSession.of(signals) for signals in recent),
            open_items=tuple(RecalledClaim.of(claim) for claim in open_claims),
        )

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
        *,
        context: Context,
    ) -> KnowledgeResults:
        """Find earlier claims that resemble the situation in front of you now.

        This is for cross-time analogy, when you want to know when a situation last looked like
        this one. For recent history and open expectations, use `recall_history` instead.
        """
        vectors = await deps.embeddings.embed([query], correlation.of(context))
        if not vectors:
            return KnowledgeResults(query=query)
        claims = await deps.claims.similar(vectors[0], symbol=symbol, limit=limit)
        return KnowledgeResults(query=query, claims=tuple(RecalledClaim.of(claim) for claim in claims))

    _ = (recall_history, search_knowledge)
