"""The MCP tool server.

`create_server` takes its dependencies and closes over them, so a test builds a server over
providers wired to fake fetchers and drives `call_tool` through the same validation the wire
uses. `serve` is the only place that constructs real clients, and it owns their lifetime.
"""

import argparse
import sys
from collections.abc import AsyncGenerator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Final, Literal

import httpx
from mcp.server import MCPServer
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict

from orient.config import Settings
from orient.llm.chat import ProxyChat
from orient.llm.embeddings import EmbeddingClient
from orient.llm.judge import JudgeClient
from orient.llm.limiter import RateLimiter
from orient.llm.research import Researcher
from orient.llm.search import SearchClient
from orient.mcp.deps import ToolDeps
from orient.mcp.tools import discovery, market, memory, persistence, reference, research, skills
from orient.orchestrator import telemetry
from orient.providers.cache import CachedPrices
from orient.providers.fred import FredProvider
from orient.providers.yahoo import (
    YahooCalendars,
    YahooDiscovery,
    YahooEarnings,
    YahooMarket,
    YahooPrices,
    YahooReference,
)
from orient.skills.loader import Skills
from orient.store.bars import BarRepository
from orient.store.claims import ClaimRepository
from orient.store.instruments import InstrumentRepository
from orient.store.pool import create_pool
from orient.store.sessions import SessionRepository
from orient.store.summaries import SummaryRepository

SERVER_NAME: Final = "market-summary"
VERSION: Final = "0.1.0"
DEFAULT_PORT: Final = 9000
# The SDK binds loopback unless told otherwise, which is invisible until a container cannot be
# reached from outside itself.
DEFAULT_HOST: Final = "127.0.0.1"

INSTRUCTIONS: Final = """\
Market data and prior analysis for writing a grounded market summary.

Every figure these tools return was measured, not inferred. A window too short to compute comes
back null rather than approximated, so a null means unknown and must not be filled in.

Breadth and sector contribution are counted across the eleven sector ETFs, never across index
constituents, because no constituent list is available. Say sector when describing them.
"""

Registrar = Callable[[MCPServer, ToolDeps], None]

REGISTRARS: Final[tuple[Registrar, ...]] = (
    skills.register,
    discovery.register,
    market.register,
    reference.register,
    research.register,
    memory.register,
    persistence.register,
)


def create_server(deps: ToolDeps, name: str = SERVER_NAME) -> MCPServer:
    server: Final = MCPServer(name=name, version=VERSION, instructions=INSTRUCTIONS)
    for register in REGISTRARS:
        register(server, deps)
    return server


class Options(BaseModel):
    """argparse hands back an untyped namespace, so it is validated rather than indexed."""

    model_config = ConfigDict(extra="ignore")

    transport: Literal["stdio", "streamable-http"] = "stdio"
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT


def parse(argv: list[str]) -> Options:
    parser: Final = argparse.ArgumentParser(prog="market-summary-mcp")
    _ = parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    _ = parser.add_argument("--host", default=DEFAULT_HOST)
    _ = parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return Options.model_validate(vars(parser.parse_args(argv)))


def main(argv: list[str] | None = None) -> int:
    args: Final = parse(sys.argv[1:] if argv is None else argv)
    settings: Final = Settings()  # pyright: ignore[reportCallIssue]  # every field comes from the environment

    pool: Final = create_pool(settings.database_url)
    auth: Final = {"Authorization": f"Bearer {settings.proxy_api_key}"}
    proxy: Final = httpx.AsyncClient(base_url=settings.proxy_base_url, headers=auth, timeout=httpx.Timeout(60.0))
    openai: Final = AsyncOpenAI(
        base_url=f"{settings.proxy_base_url}/v1",
        api_key=settings.proxy_api_key,
        timeout=settings.request_timeout_seconds,
    )

    @asynccontextmanager
    async def lifespan(server: MCPServer) -> AsyncGenerator[None, None]:
        del server
        async with AsyncExitStack() as stack:
            await pool.open(wait=True)
            _ = stack.push_async_callback(pool.close)
            _ = await stack.enter_async_context(proxy)
            _ = await stack.enter_async_context(openai)
            yield None

    bars: Final = BarRepository(pool)
    prices: Final = CachedPrices(YahooPrices(), bars)
    chat: Final = ProxyChat(openai, RateLimiter(settings.requests_per_minute), telemetry.outgoing)
    deps: Final = ToolDeps(
        prices=prices,
        discovery=YahooDiscovery(),
        reference=YahooReference(),
        earnings=YahooEarnings(),
        market=YahooMarket(prices, FredProvider()),
        calendars=YahooCalendars(),
        research=Researcher(SearchClient(proxy, settings.search_tool_name), chat, settings.fast_model),
        skills=Skills(),
        chat=chat,
        fast_model=settings.fast_model,
        judge=JudgeClient(proxy, settings.judge_guardrail),
        embeddings=EmbeddingClient(proxy, settings.embedding_model, settings.embedding_dimensions),
        instruments=InstrumentRepository(pool),
        sessions=SessionRepository(pool),
        summaries=SummaryRepository(pool),
        claims=ClaimRepository(pool),
    )

    server: Final = MCPServer(
        name=SERVER_NAME,
        version=VERSION,
        instructions=INSTRUCTIONS,
        lifespan=lifespan,
    )
    for register in REGISTRARS:
        register(server, deps)

    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(transport="streamable-http", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
