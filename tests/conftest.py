"""Every async test runs on a selector event loop.

psycopg refuses to run async on the proactor loop Windows defaults to, raising an
InterfaceError that `psycopg_pool` swallows and retries, so the real cause surfaces
much later as a pool timeout. Pinning the loop keeps Windows and Linux on the same
one. pytest-asyncio's `event_loop_policy` fixture is deprecated, and `filterwarnings`
is set to error, so this hook is the supported route.
"""

import asyncio
from collections.abc import Callable, Mapping

import pytest

LoopFactory = Callable[[], asyncio.AbstractEventLoop]


def pytest_asyncio_loop_factories(config: pytest.Config, item: pytest.Item) -> Mapping[str, LoopFactory]:
    del config, item
    return {"selector": asyncio.SelectorEventLoop}
