"""Finding an instrument to research."""

from typing import Annotated

from mcp.server import MCPServer
from pydantic import Field

from orient.domain.models import AssetClass
from orient.mcp.deps import ToolDeps
from orient.mcp.results import InstrumentMatches

MAX_MATCHES = 50


def register(server: MCPServer, deps: ToolDeps) -> None:
    @server.tool()
    async def discover_instruments(
        query: Annotated[
            str,
            Field(description="A ticker fragment or company name such as 'AAPL'. Ignored when screen is set"),
        ] = "",
        screen: Annotated[
            str | None,
            Field(description="A predefined screen instead of a search, such as 'day_gainers' or 'day_losers'"),
        ] = None,
        limit: Annotated[int, Field(description="Most matches to return", ge=1, le=MAX_MATCHES)] = 10,
        asset_class: Annotated[
            AssetClass | None,
            Field(description="Restrict to one kind of instrument. Every kind when unset"),
        ] = None,
    ) -> InstrumentMatches:
        """Find tradeable instruments, either by searching or by listing a predefined screen.

        Searching looks up the ticker and the name together and merges the two, so it does not
        matter which of them the user typed; it covers equities, ETFs, indices, futures,
        currencies and crypto. Pass screen instead when the question is what is moving today
        rather than which instrument someone means.
        """
        if screen:
            matches = await deps.discovery.by_screen(screen, limit)
            return InstrumentMatches(query=screen, matches=matches[:limit])

        matches = await deps.discovery.anything(query, limit, asset_class)
        return InstrumentMatches(query=query, matches=matches[:limit])

    _ = discover_instruments
