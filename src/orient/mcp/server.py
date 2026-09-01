"""The MCP tool server.

`create_server` takes its dependencies and closes over them, so a test builds a server over
providers wired to fake fetchers and drives `call_tool` through the same validation the wire
uses. `serve` is the only place that constructs real clients, and it owns their lifetime.
"""

import sys
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from typing import Final, Literal

import httpx
from mcp.server import MCPServer
from pydantic import ConfigDict

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
from orient.serving import Listener, arguments, proxy_client
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

INSTRUCTIONS: Final = """\
Market data and prior analysis for writing a grounded market summary.

Every figure these tools return was measured, not inferred. A measurement the window was too
short to compute is left out of the answer rather than approximated, so a field that is absent is
one nothing measured. Absent is not zero, and it is not flat.

Breadth and sector contribution are counted across the sector series of the instrument's own
market, never across index constituents, because no constituent list is available. Say sector
when describing them.
"""

Lifespan = Callable[[MCPServer], AbstractAsyncContextManager[None]]
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


def create_server(deps: ToolDeps, name: str = SERVER_NAME, lifespan: Lifespan | None = None) -> MCPServer:
    """The one place tools are registered, so a test and the real process build the same surface."""
    server: Final = MCPServer(name=name, version=VERSION, instructions=INSTRUCTIONS, lifespan=lifespan)
    for register in REGISTRARS:
        register(server, deps)
    return server


class Options(Listener):
    """Where to bind, and how a client reaches it."""

    model_config = ConfigDict(extra="ignore")

    transport: Literal["stdio", "streamable-http"] = "stdio"


def parse(argv: list[str]) -> Options:
    parser: Final = arguments("market-summary-mcp", DEFAULT_PORT)
    _ = parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    return Options.model_validate(vars(parser.parse_args(argv)))


def main(argv: list[str] | None = None) -> int:
    args: Final = parse(sys.argv[1:] if argv is None else argv)
    settings: Final = Settings()  # pyright: ignore[reportCallIssue]  # every field comes from the environment

    pool: Final = create_pool(settings.database_url)
    auth: Final = {"Authorization": f"Bearer {settings.proxy_api_key}"}
    proxy: Final = httpx.AsyncClient(base_url=settings.proxy_base_url, headers=auth, timeout=httpx.Timeout(60.0))
    openai: Final = proxy_client(settings)

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

    server: Final = create_server(deps, lifespan=lifespan)

    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(transport="streamable-http", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
