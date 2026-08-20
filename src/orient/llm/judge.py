"""Quality review of a finished summary, run at the point the summary is stored.

The proxy's post-call judge scores the text of an assistant message. When a summary travels as a
tool-call argument rather than as assistant text, that hook sees an empty string and passes
without reading anything, so the review has to be asked for explicitly at the boundary where the
prose actually is.

Asking the proxy rather than reimplementing the scoring keeps the criteria and their weights in
`proxy/config.yaml`, which is one place a human can read and change them.

A judge that cannot be reached returns `Passed`. A quality bar that turns into an outage is worse
than one that occasionally misses, and an unreachable judge is visible in the proxy's own logs.
"""

from dataclasses import dataclass
from typing import Final

import httpx
from pydantic import BaseModel, ConfigDict

APPLY_PATH: Final = "/guardrails/apply_guardrail"
BLOCKED: Final = (400, 422)
DETAIL_LENGTH: Final = 1200


@dataclass(frozen=True, slots=True)
class Passed:
    pass


@dataclass(frozen=True, slots=True)
class Blocked:
    """Why the summary was turned away, in the reviewer's own words, for the writer to act on."""

    detail: str


Verdict = Passed | Blocked


class _Error(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: str = ""


class _Body(BaseModel):
    model_config = ConfigDict(extra="ignore")

    error: _Error = _Error()


def _one_line(text: str) -> str:
    return " ".join(text.split())[:DETAIL_LENGTH]


class JudgeClient:
    def __init__(self, client: httpx.AsyncClient, guardrail: str) -> None:
        self._client: Final = client
        self._guardrail: Final = guardrail

    async def review(self, prose: str) -> Verdict:
        if not prose.strip():
            return Passed()
        try:
            response = await self._client.post(
                APPLY_PATH,
                json={"guardrail_name": self._guardrail, "text": prose, "language": "en"},
            )
        except httpx.HTTPError:
            return Passed()

        if response.status_code not in BLOCKED:
            return Passed()
        return Blocked(detail=_one_line(_Body.model_validate_json(response.content).error.message or response.text))
