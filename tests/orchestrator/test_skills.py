"""The loader, and the packaged tree it loads.

Two things matter. Every asset class and level a run can ask for must resolve, since a missing
file is a run that dies after the prefetch has already been paid for. And progressive loading has
to actually be progressive: a currency pair that pulls in the equities guidance is paying for
instructions that contradict the ones it needs.
"""

from pathlib import Path
from typing import Final

import pytest

from orient.domain.models import AssetClass, ReadingLevel
from orient.orchestrator.skills import SkillError, Skills, parse, rendered

ASSET_CLASSES: Final[tuple[AssetClass, ...]] = (
    "equity",
    "etf",
    "index",
    "future",
    "currency",
    "crypto",
    "fund",
)
LEVELS: Final[tuple[ReadingLevel, ...]] = ("beginner", "intermediate", "advanced")

SAMPLE: Final = """\
---
name: A skill
description: What it is for, including a colon: like this one
---

The body, which the loader hands to the model.
"""


@pytest.mark.parametrize("asset_class", ASSET_CLASSES)
def test_every_asset_class_resolves_to_a_guide(asset_class: AssetClass) -> None:
    loaded: Final = Skills().research(asset_class)
    assert len(loaded) == 2
    assert all(skill.body for skill in loaded)


@pytest.mark.parametrize("level", LEVELS)
def test_every_level_resolves_to_structure_compliance_and_a_guide(level: ReadingLevel) -> None:
    loaded: Final = Skills().writing(level)
    assert len(loaded) == 3
    assert all(skill.body for skill in loaded)


def test_researching_one_asset_class_never_loads_another() -> None:
    text: Final = rendered(Skills().research("currency"))
    assert "Currencies" in text
    assert "Equities" not in text


def test_writing_one_level_never_loads_another() -> None:
    text: Final = rendered(Skills().writing("advanced"))
    assert "Advanced level" in text
    assert "Beginner level" not in text


def test_compliance_is_loaded_at_every_level() -> None:
    """The rules it carries are not negotiable by reading level."""
    assert all("Compliance" in rendered(Skills().writing(level)) for level in LEVELS)


def test_frontmatter_and_body_are_separated() -> None:
    skill: Final = parse(SAMPLE, "sample.md")
    assert skill.name == "A skill"
    assert skill.description == "What it is for, including a colon: like this one"
    assert skill.body == "The body, which the loader hands to the model."


def test_rendered_names_each_block_so_the_model_can_attribute_an_instruction() -> None:
    text: Final = rendered(Skills().writing("beginner"))
    assert text.count("# writing") == 1
    assert "# Compliance" in text


def test_a_missing_skill_is_a_deployment_fault(tmp_path: Path) -> None:
    with pytest.raises(SkillError, match="no skill at"):
        _ = Skills(tmp_path).load("writing/SKILL.md")


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("no fence at all\n", "a body with no frontmatter"),
        ("---\nname: x\ndescription: y\n", "a fence that never closes"),
        ("---\nname: x\n---\n\nbody\n", "frontmatter missing a description"),
        ("---\nname: x\ndescription: y\nextra: z\n---\n\nbody\n", "an unrecognised key"),
    ],
)
def test_a_malformed_skill_fails_loudly(tmp_path: Path, text: str, why: str) -> None:
    del why
    target: Final = tmp_path / "writing"
    target.mkdir()
    _ = (target / "SKILL.md").write_text(text, encoding="utf-8")
    with pytest.raises(SkillError):
        _ = Skills(tmp_path).load("writing/SKILL.md")
