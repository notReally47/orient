"""What all three entry points need to start: an address to bind, and a client for the proxy.

The GUI, the orchestrator and the tool server are separate processes with separate arguments, and
they were each carrying their own copy of the same two decisions. A default host that differs
between them is invisible until one container cannot be reached, and a retry policy that differs
between them is invisible until a run costs twice what it should.
"""

import argparse
from collections.abc import Sequence
from typing import Final

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict

from orient.config import Settings

DEFAULT_HOST: Final = "127.0.0.1"


class Listener(BaseModel):
    """Where a service binds. argparse hands back an untyped namespace, so it is validated."""

    model_config = ConfigDict(extra="ignore")

    host: str = DEFAULT_HOST
    port: int


def arguments(prog: str, default_port: int) -> argparse.ArgumentParser:
    """A parser carrying `--host` and `--port`, for a caller that has more of its own to add."""
    parser: Final = argparse.ArgumentParser(prog=prog)
    _ = parser.add_argument("--host", default=DEFAULT_HOST)
    _ = parser.add_argument("--port", type=int, default=default_port)
    return parser


def listener(prog: str, argv: Sequence[str], default_port: int) -> Listener:
    return Listener.model_validate(vars(arguments(prog, default_port).parse_args(list(argv))))


def proxy_client(settings: Settings) -> AsyncOpenAI:
    """The OpenAI-shaped client every process talks to the proxy through.

    Retrying is the proxy's job, not this client's. The SDK retries twice by default, and a retry
    here cannot pick a different Gemini project, cannot see a deployment's cooldown, and does not
    cancel the attempt it gave up on: the upstream call runs to completion regardless. What it
    does is put a second and third copy of the same prompt in flight against an account that was
    already answering slowly. The proxy's `num_retries` knows the deployments and is the one layer
    that should have this.
    """
    return AsyncOpenAI(
        base_url=f"{settings.proxy_base_url}/v1",
        api_key=settings.proxy_api_key,
        timeout=settings.request_timeout_seconds,
        max_retries=0,
    )
