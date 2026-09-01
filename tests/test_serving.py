"""Argv and the proxy client, the two things every entry point shares.

A host that defaults to loopback inside a container is a service nothing outside it can reach, and
a client that retries on its own spends the run's quota twice over while the proxy is still trying
to place the first attempt.
"""

from typing import Final

import pytest

from orient.config import Settings
from orient.mcp.server import DEFAULT_PORT as MCP_PORT
from orient.mcp.server import parse as parse_mcp
from orient.serving import DEFAULT_HOST, listener, proxy_client

EVERY_INTERFACE: Final = "0.0.0.0"  # noqa: S104  # what compose passes


def _settings() -> Settings:
    return Settings(_env_file=None)  # pyright: ignore[reportCallIssue]  # defaults are the contract here


def test_the_defaults_bind_loopback_for_a_local_run() -> None:
    where: Final = listener("orient-orchestrator", [], 8000)

    assert where.host == DEFAULT_HOST
    assert where.port == 8000


def test_the_container_can_bind_every_interface() -> None:
    where: Final = listener("orient-orchestrator", ["--host", EVERY_INTERFACE, "--port", "8080"], 8000)

    assert where.host == EVERY_INTERFACE
    assert where.port == 8080


def test_the_tool_server_takes_the_same_address_arguments_and_one_of_its_own() -> None:
    """It extends the shared parser rather than declaring a second `--host` that could drift."""
    assert parse_mcp([]).transport == "stdio"
    assert parse_mcp([]).host == DEFAULT_HOST
    assert parse_mcp([]).port == MCP_PORT

    chosen: Final = parse_mcp(["--transport", "streamable-http", "--host", EVERY_INTERFACE])
    assert (chosen.transport, chosen.host) == ("streamable-http", EVERY_INTERFACE)


def test_an_unknown_transport_is_refused_rather_than_carried_into_the_run() -> None:
    with pytest.raises(SystemExit):
        _ = parse_mcp(["--transport", "carrier-pigeon"])


def test_the_proxy_client_never_retries_because_the_proxy_already_does() -> None:
    """A retry here cannot pick a different deployment and cannot cancel the attempt it gave up
    on, so it doubles the prompts in flight against an account already answering slowly."""
    assert proxy_client(_settings()).max_retries == 0


def test_the_proxy_client_talks_to_the_configured_proxy_and_not_to_the_vendor() -> None:
    settings: Final = _settings()

    assert str(proxy_client(settings).base_url).startswith(settings.proxy_base_url)
