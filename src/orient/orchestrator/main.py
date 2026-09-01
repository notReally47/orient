"""Starting the orchestrator: argv, the real dependencies, and uvicorn.

The only place real clients are constructed, and it owns their lifetime. Everything below it takes
what it needs as an argument.
"""

import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Final

import uvicorn
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from orient.config import Settings
from orient.llm.chat import ProxyChat
from orient.llm.limiter import RateLimiter
from orient.orchestrator import telemetry
from orient.orchestrator.app import create_app
from orient.orchestrator.deps import RunDeps
from orient.orchestrator.tools import connect
from orient.serving import listener, proxy_client
from orient.skills.loader import Skills
from orient.store.pool import create_pool
from orient.store.summaries import SummaryRepository

SERVICE_NAME: Final = "orient-orchestrator"
DEFAULT_PORT: Final = 8000


@asynccontextmanager
async def build(settings: Settings) -> AsyncGenerator[RunDeps, None]:
    """Every real dependency a run needs, opened together and closed together.

    The only place real clients are constructed. Everything below takes what it needs as an
    argument, which is what makes the layers testable without patching module state.
    """
    pool: Final = create_pool(settings.database_url)
    limiter: Final = RateLimiter(settings.requests_per_minute)

    async with proxy_client(settings) as openai, connect(settings.mcp_url) as tools:
        await pool.open(wait=True)
        try:
            yield RunDeps(
                settings=settings,
                chat=ProxyChat(openai, limiter, telemetry.outgoing),
                tools=tools,
                skills=Skills(),
                summaries=SummaryRepository(pool),
                trace_id=telemetry.current_trace_id,
                span=telemetry.span,
            )
        finally:
            await pool.close()


def main(argv: list[str] | None = None) -> int:
    where: Final = listener("orient-orchestrator", sys.argv[1:] if argv is None else argv, DEFAULT_PORT)
    settings: Final = Settings()  # pyright: ignore[reportCallIssue]  # every field comes from the environment

    telemetry.configure(SERVICE_NAME, settings.otlp_endpoint)
    application: Final = create_app(lambda: build(settings))
    FastAPIInstrumentor.instrument_app(application)

    uvicorn.run(application, host=where.host, port=where.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
