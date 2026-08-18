"""Starting the orchestrator: argv, the real dependencies, and uvicorn.

The only place real clients are constructed, and it owns their lifetime. Everything below it takes
what it needs as an argument.
"""

import argparse
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Final

import httpx
import uvicorn
from openai import AsyncOpenAI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import BaseModel, ConfigDict

from orient.config import Settings
from orient.llm.chat import ProxyChat
from orient.llm.embeddings import EmbeddingClient
from orient.llm.limiter import RateLimiter
from orient.orchestrator import telemetry
from orient.orchestrator.app import create_app
from orient.orchestrator.deps import RunDeps
from orient.orchestrator.skills import Skills
from orient.orchestrator.tools import connect
from orient.store.claims import ClaimRepository
from orient.store.instruments import InstrumentRepository
from orient.store.pool import create_pool
from orient.store.runs import RunRepository
from orient.store.sessions import SessionRepository
from orient.store.summaries import SummaryRepository

SERVICE_NAME: Final = "orient-orchestrator"
DEFAULT_PORT: Final = 8000
DEFAULT_HOST: Final = "127.0.0.1"


class Options(BaseModel):
    """argparse hands back an untyped namespace, so it is validated rather than indexed."""

    model_config = ConfigDict(extra="ignore")

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT


def parse(argv: list[str]) -> Options:
    parser: Final = argparse.ArgumentParser(prog="orient-orchestrator")
    _ = parser.add_argument("--host", default=DEFAULT_HOST)
    _ = parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return Options.model_validate(vars(parser.parse_args(argv)))


@asynccontextmanager
async def build(settings: Settings) -> AsyncGenerator[RunDeps, None]:
    pool: Final = create_pool(settings.database_url)
    auth: Final = {"Authorization": f"Bearer {settings.proxy_api_key}"}
    timeout: Final = httpx.Timeout(settings.request_timeout_seconds)
    limiter: Final = RateLimiter(settings.requests_per_minute)

    async with (
        httpx.AsyncClient(base_url=settings.proxy_base_url, headers=auth, timeout=timeout) as proxy,
        AsyncOpenAI(
            base_url=f"{settings.proxy_base_url}/v1",
            api_key=settings.proxy_api_key,
            timeout=settings.request_timeout_seconds,
        ) as openai,
        connect(settings.mcp_url) as tools,
    ):
        await pool.open(wait=True)
        try:
            yield RunDeps(
                settings=settings,
                chat=ProxyChat(openai, limiter, telemetry.outgoing),
                tools=tools,
                skills=Skills(),
                embeddings=EmbeddingClient(proxy, settings.embedding_model, settings.embedding_dimensions),
                instruments=InstrumentRepository(pool),
                sessions=SessionRepository(pool),
                summaries=SummaryRepository(pool),
                claims=ClaimRepository(pool),
                runs=RunRepository(pool),
                trace_id=telemetry.current_trace_id,
                span=telemetry.span,
            )
        finally:
            await pool.close()


def main(argv: list[str] | None = None) -> int:
    args: Final = parse(sys.argv[1:] if argv is None else argv)
    settings: Final = Settings()  # pyright: ignore[reportCallIssue]  # every field comes from the environment

    telemetry.configure(SERVICE_NAME, settings.otlp_endpoint)
    application: Final = create_app(lambda: build(settings))
    FastAPIInstrumentor.instrument_app(application)

    uvicorn.run(application, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
