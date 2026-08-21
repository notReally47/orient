"""The run a call belongs to, carried from the orchestrator to every model call it causes.

The proxy dashboard groups spend and logs by session, and a run is one session. The orchestrator's
own turns carry it in the request body, which the chat endpoint reads. The rest of a run's model
calls are made by the tool server rather than the orchestrator -- news synthesis, claim
extraction, embeddings and the quality review all happen behind a tool -- and without the same
value they land in the dashboard as unattributed rows beside the run that caused them.

Two hops carry it. Orchestrator to tool server is MCP request metadata, which is not part of a
tool's input schema, so the session is never something the model can set, omit or invent. Tool
server to proxy is an HTTP header, which is the only channel the search, embeddings and guardrail
endpoints have: they take no `litellm_session_id` body field the way chat completions do.
"""

from typing import Final

from mcp.server.mcpserver.context import Context
from mcp.types import RequestParamsMeta

SESSION_KEY: Final = "orient/session"
SESSION_HEADER: Final = "x-litellm-session-id"


def carried(session: str | None) -> RequestParamsMeta | None:
    """What a tool call is stamped with, or nothing when the caller is not part of a run."""
    return {SESSION_KEY: session} if session else None


def of(context: Context) -> str | None:
    """The session a tool call arrived under, read back on the server side.

    A tool can be reached without a request wrapped around it, by a test calling the server
    directly or a harness embedding the tools in-process. Such a call belongs to no session, and
    the model calls it causes are attributed to nothing rather than to the wrong run.
    """
    try:
        meta = context.request_context.meta
    except ValueError:
        return None
    carried_value: Final = (meta or {}).get(SESSION_KEY)
    return carried_value if isinstance(carried_value, str) and carried_value else None


def headers(session: str | None) -> dict[str, str]:
    """The session as a request header, which is how a non-chat proxy endpoint reads it."""
    return {SESSION_HEADER: session} if session else {}
