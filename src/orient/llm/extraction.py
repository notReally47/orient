"""Turning accepted prose into records the knowledge bank can query.

This runs after the summary has passed both checks, not inside the write call, so nothing is ever
recorded from a draft that was later revised away. It runs on the fast model because reading
finished prose back is a cheaper job than writing it.

The answer is JSON, and it is validated rather than indexed: an extraction that does not fit the
schema costs the run its annotations, never a malformed row in `claims`.
"""

from collections.abc import Mapping
from datetime import date
from typing import Final

from pydantic import TypeAdapter, ValidationError

from orient.domain.models import Annotation, ClaimKind, Frozen

FENCE: Final = "```"


class ExtractedClaim(Frozen):
    kind: ClaimKind
    statement: str
    attribution: str | None = None
    target_date: date | None = None
    mentioned_symbols: tuple[str, ...] = ()


class Extraction(Frozen):
    annotations: tuple[Annotation, ...] = ()
    claims: tuple[ExtractedClaim, ...] = ()


_ADAPTER: Final = TypeAdapter(Extraction)
SCHEMA: Final[Mapping[str, object]] = Extraction.model_json_schema()


def _unfenced(text: str) -> str:
    """Models wrap JSON in a code fence often enough that refusing one would cost real extractions."""
    stripped: Final = text.strip()
    if not stripped.startswith(FENCE):
        return stripped
    inner: Final = stripped.removeprefix(FENCE).removesuffix(FENCE)
    return inner.partition("\n")[2].strip() if inner.startswith("json") else inner.strip()


def parse(text: str) -> Extraction:
    """An unreadable answer yields nothing rather than raising: the summary is already accepted."""
    try:
        return _ADAPTER.validate_json(_unfenced(text))
    except ValidationError:
        return Extraction()
