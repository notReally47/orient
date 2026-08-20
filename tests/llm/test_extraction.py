"""Extraction runs after the summary is already accepted, so it may never cost the run.

The rule under test: an answer that does not fit the schema loses the annotations, never produces
a malformed row in `claims`.
"""

from typing import Final

import pytest
from pydantic import TypeAdapter

from orient.llm.extraction import SCHEMA, Extraction, parse

_OBJECT: Final = TypeAdapter(dict[str, object])

ANSWER: Final = """\
{
  "annotations": [{"term": "breadth", "definition": "how many sectors rose against how many fell"}],
  "claims": [
    {
      "kind": "attribution", "attribution": "the sector fell with it",
      "statement": "Energy led the decline",
      "attribution": "crude fell 3%",
      "mentioned_symbols": ["XLE"]
    },
    {"kind": "expectation", "statement": "CPI lands on Thursday", "target_date": "2026-08-20"}
  ]
}
"""


def test_a_plain_answer_parses_into_annotations_and_claims() -> None:
    extracted: Final = parse(ANSWER)
    assert extracted.annotations[0].term == "breadth"
    assert [claim.kind for claim in extracted.claims] == ["attribution", "expectation"]
    assert extracted.claims[0].mentioned_symbols == ("XLE",)


@pytest.mark.parametrize("fence", ["```json\n{body}\n```", "```\n{body}\n```"])
def test_a_fenced_answer_parses(fence: str) -> None:
    """Models wrap JSON in a fence often enough that refusing one would cost real extractions."""
    assert parse(fence.format(body=ANSWER)) == parse(ANSWER)


@pytest.mark.parametrize(
    "unreadable",
    [
        "I could not find any claims.",
        "",
        '{"claims": [{"kind": "prediction", "statement": "it will rise"}]}',
        '{"annotations": "not a list"}',
    ],
)
def test_an_unreadable_answer_yields_nothing_rather_than_raising(unreadable: str) -> None:
    assert parse(unreadable) == Extraction()


def test_the_schema_names_both_halves_so_the_model_knows_what_to_return() -> None:
    properties: Final = _OBJECT.validate_python(SCHEMA["properties"])
    assert set(properties) == {"annotations", "claims"}
