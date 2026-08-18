"""The tool surface, reached over MCP rather than imported.

The orchestrator is one client of the tool server, not its owner, and going over the wire is what
keeps that honest: the schemas the model sees are the ones the server generated, and a tool that
stops registering breaks here the same way it would break for Claude Code.

Every call answers with a value. A tool that raises, a name the server does not serve and
arguments that are not JSON are all outcomes the loop reports and continues from, because one bad
call is not a reason to abandon a run.
"""

import json
from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Final, Protocol, cast

from mcp.server import MCPServer
from mcp.types import CallToolResult, TextContent, Tool
from pydantic import TypeAdapter, ValidationError

from mcp import Client
from orient.llm.chat import ToolSchema

DETAIL_LENGTH: Final = 300

_ARGUMENTS: Final = TypeAdapter(dict[str, object])
_STRUCTURED: Final[TypeAdapter[dict[str, object] | None]] = TypeAdapter(dict[str, object] | None)

Target = str | MCPServer


@dataclass(frozen=True, slots=True)
class Succeeded:
    tool: str
    payload: str
    structured: Mapping[str, object] | None


@dataclass(frozen=True, slots=True)
class Refused:
    tool: str
    detail: str


Outcome = Succeeded | Refused


class ToolCatalog(Protocol):
    def schemas(self) -> tuple[ToolSchema, ...]: ...

    async def execute(self, name: str, arguments: str) -> Outcome: ...


def _one_line(text: str) -> str:
    return " ".join(text.split())[:DETAIL_LENGTH]


def _spoken(result: CallToolResult) -> str:
    """The text blocks, which are what a server puts an error message in."""
    return " ".join(block.text for block in result.content if isinstance(block, TextContent))


class McpTools:
    """Built by `connect`, which owns the session; the constructor takes what it discovered."""

    def __init__(self, client: Client, tools: Sequence[Tool]) -> None:
        self._client: Final = client
        self._schemas: Final = tuple(
            ToolSchema(
                name=tool.name,
                description=tool.description or tool.name,
                parameters=tool.input_schema,
            )
            for tool in tools
        )
        self._served: Final = frozenset(tool.name for tool in tools)

    def schemas(self) -> tuple[ToolSchema, ...]:
        return self._schemas

    async def execute(self, name: str, arguments: str) -> Outcome:
        if name not in self._served:
            return Refused(tool=name, detail=f"no such tool; served are {sorted(self._served)}")

        try:
            parsed = _ARGUMENTS.validate_json(arguments or "{}")
        except ValidationError:
            return Refused(tool=name, detail=f"arguments were not a JSON object: {_one_line(arguments)}")

        try:
            result = await self._client.call_tool(name, parsed)
        except Exception as exc:  # noqa: BLE001  # one failed tool is not a reason to end the run
            return Refused(tool=name, detail=f"{type(exc).__name__}: {_one_line(str(exc))}")

        if result.is_error:
            return Refused(tool=name, detail=_one_line(_spoken(result)) or "the tool reported an error")

        structured: Final = _STRUCTURED.validate_python(cast("object", result.structured_content))
        return Succeeded(
            tool=name,
            payload=json.dumps(structured, default=str) if structured is not None else _spoken(result),
            structured=structured,
        )


@asynccontextmanager
async def connect(target: Target) -> AsyncGenerator[McpTools, None]:
    """A URL in the container, an in-process server in a test: the same session either way."""
    async with Client(target) as client:
        listed = await client.list_tools()
        yield McpTools(client, listed.tools)
