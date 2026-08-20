"""Skills, served in tiers, so a model loads instructions when it decides it needs them.

The catalog is also published as MCP resources. The two primitives differ in who may reach for
them: a resource is application-controlled, which suits a catalog a harness reads once at
startup, and a tool is model-controlled, which is the only thing that makes on-demand activation
the model's decision rather than the harness's. Both are backed by the same loader.
"""

from typing import Annotated, Final

from mcp.server import MCPServer
from pydantic import Field

from orient.mcp.deps import ToolDeps
from orient.skills.loader import Body, Listing, SkillError, as_activation

SKILL_SCHEME: Final = "skill"


class _UnknownSkillError(ValueError):
    """Raised so the SDK reports a bad skill name as a tool error rather than a server fault."""


def register(server: MCPServer, deps: ToolDeps) -> None:
    catalog: Final[tuple[Listing, ...]] = deps.skills.catalog()
    known: Final = tuple(listing.name for listing in catalog)

    @server.tool()
    async def activate_skill(
        name: Annotated[str, Field(description=f"Which skill to load. One of: {', '.join(known)}")],
    ) -> str:
        """Load a skill's full instructions, having decided from the catalog that you need them.

        Returns the instructions and a list of the files bundled with the skill. Those files are
        not loaded with it: read one with `read_skill_resource` when the instructions tell you to.
        """
        if name not in known:
            message = f"no skill named {name!r}; the tree serves {', '.join(known)}"
            raise _UnknownSkillError(message)
        body: Final[Body] = deps.skills.body(name)
        return as_activation(body)

    @server.tool()
    async def read_skill_resource(
        skill: Annotated[str, Field(description=f"Which skill the file belongs to. One of: {', '.join(known)}")],
        path: Annotated[str, Field(description="The file, exactly as the skill's instructions spelled it")],
    ) -> str:
        """Read one file bundled with a skill, when that skill's instructions point at it.

        Read the one the instructions name for the situation in front of you, not all of them.
        """
        try:
            return deps.skills.resource(skill, path)
        except SkillError as exc:
            raise _UnknownSkillError(str(exc)) from exc

    for listing in catalog:
        _publish(server, deps, listing)

    _ = (activate_skill, read_skill_resource)


def _publish(server: MCPServer, deps: ToolDeps, listing: Listing) -> None:
    """One resource per skill, so a client that never calls a tool can still find the tree."""
    name: Final = listing.name

    @server.resource(
        f"{SKILL_SCHEME}://{name}",
        name=name,
        description=listing.description,
        mime_type="text/markdown",
    )
    def read() -> str:
        return as_activation(deps.skills.body(name))

    _ = read
